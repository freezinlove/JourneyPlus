import { useEffect, useState, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Compass } from "lucide-react";
import { BrandMark, NavIcon } from "./Icons";
import { api, ApiError } from "./api";
import type { Identity } from "./contracts";
import { Notice, Modal } from "./UI";
import { Holdings } from "./Holdings";
import { News, Reader } from "./News";
import { Chat } from "./Chat";
import s from "./App.module.css";
export default function App() {
  const client = useQueryClient(),
    nav = useNavigate(),
    loc = useLocation();
  const [theme, setTheme] = useState(
      localStorage.getItem("jp-theme") || "light",
    ),
    [epoch, setEpoch] = useState(0),
    [newOpen, setNewOpen] = useState(false);
  const lastIdentity = useRef<string | undefined>(undefined);
  const me = useQuery({
    queryKey: ["identity", epoch],
    queryFn: async () => {
      const identity = await api<Identity>("/auth/me");
      if (lastIdentity.current && lastIdentity.current !== identity.id)
        client.removeQueries({
          predicate: (q) => q.queryKey[0] !== "identity",
        });
      lastIdentity.current = identity.id;
      return identity;
    },
    retry: false,
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("jp-theme", theme);
  }, [theme]);
  useEffect(() => {
    const reset = () => {
      client.clear();
      setEpoch((x) => x + 1);
      void client.invalidateQueries();
    };
    window.addEventListener("session-expired", reset);
    const channel = new BroadcastChannel("journeyplus-account");
    channel.onmessage = reset;
    return () => {
      window.removeEventListener("session-expired", reset);
      channel.close();
    };
  }, [client]);
  if (me.isPending)
    return <main className={s.login}>正在连接 JourneyPlus…</main>;
  if (me.error) {
    if (me.error instanceof ApiError && me.error.status === 401)
      return (
        <Login
          onSuccess={() => {
            client.clear();
            setEpoch((x) => x + 1);
          }}
        />
      );
    return (
      <main className={s.login}>
        <Notice error={me.error} retry={() => me.refetch()} />
      </main>
    );
  }
  const params = new URLSearchParams(loc.search),
    activity = params.get("activity_id");
  const page =
    loc.pathname === "/holdings"
      ? "holdings"
      : activity
        ? "reader"
        : loc.pathname === "/news" ||
            loc.pathname === "/knowledge" ||
            loc.pathname === "/briefs"
          ? "news"
          : "chat";
  const secondary = page === "holdings" || page === "reader";
  const back = () => {
    if (window.history.state?.idx > 0) nav(-1);
    else nav(page === "reader" ? "/news" : "/");
  };
  const open = (id: string, version?: string) =>
    nav(
      `/news?activity_id=${encodeURIComponent(id)}${version ? `&version_ref=${encodeURIComponent(version)}` : ""}`,
    );
  return (
    <div className={s.app} key={`${me.data?.id}:${epoch}`}>
      <div className={s.brand}>
        <BrandMark />
        JourneyPlus
      </div>
      <nav className={s.rail} aria-label="主导航">
        {secondary ? (
          <button
            className={`${s.icon} ${s.back}`}
            onClick={back}
            aria-label="返回"
          >
            <NavIcon name="back" />
          </button>
        ) : (
          <>
            <div className={s.segment}>
              <button
                className={s.icon}
                aria-label="对话"
                aria-current={page === "chat" ? "page" : undefined}
                onClick={() => nav("/")}
              >
                <NavIcon name="chat" />
              </button>
              <button
                className={s.icon}
                aria-label="会籍新闻"
                aria-current={page === "news" ? "page" : undefined}
                onClick={() => nav("/news")}
              >
                <NavIcon name="news" />
              </button>
            </div>
            <button
              className={`${s.icon} ${s.account}`}
              aria-label="我的会籍"
              onClick={() => nav("/holdings")}
            >
              <NavIcon name="account" />
            </button>
          </>
        )}
      </nav>
      {page === "chat" && (
        <button
          className={`${s.icon} ${s.new}`}
          onClick={() => setNewOpen(true)}
          aria-label="新对话"
        >
          <NavIcon name="new" />
        </button>
      )}
      {newOpen && (
        <Modal title="开始新对话" onClose={() => setNewOpen(false)}>
          <p>新对话会替换当前短期工作区。</p>
          <button
            className={`${s.primary} ${s.fullWidth}`}
            onClick={() => {
              setNewOpen(false);
              window.dispatchEvent(new Event("new-conversation"));
            }}
          >
            开始新对话
          </button>
        </Modal>
      )}
      <div className={s.topFade} />
      <div className={s.bottomFade} />
      <div hidden={page !== "chat"} className={s.chatHost}>
        <Chat openActivity={open} />
      </div>
      {page === "news" && <News open={open} />}
      {page === "reader" && activity && (
        <Reader
          id={activity}
          version={params.get("version_ref") || undefined}
        />
      )}
      {page === "holdings" && (
        <Holdings
          username={me.data!.username}
          theme={theme}
          setTheme={setTheme}
          logout={async () => {
            await api("/auth/logout", {});
            new BroadcastChannel("journeyplus-account").postMessage("logout");
            client.clear();
            setEpoch((x) => x + 1);
          }}
        />
      )}
    </div>
  );
}
function Login({ onSuccess }: { onSuccess: () => void }) {
  const [error, setError] = useState<unknown>(),
    [pending, setPending] = useState(false);
  return (
    <main className={s.login}>
      <Compass size={36} />
      <h1>欢迎来到 JourneyPlus</h1>
      <p>从已有会籍，找到你的下一程。</p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setPending(true);
          setError(null);
          try {
            await api("/auth/login", {
              username: f.get("username"),
              password: f.get("password"),
            });
            onSuccess();
          } catch (err) {
            setError(err);
          } finally {
            setPending(false);
          }
        }}
      >
        <label>
          账号
          <input name="username" autoComplete="username" required />
        </label>
        <label>
          密码
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </label>
        {!!error && <Notice error={error} />}
        <button className={s.primary} disabled={pending}>
          {pending ? "正在登录…" : "登录"}
        </button>
      </form>
    </main>
  );
}
