import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { Holding, CatalogNode } from "./contracts";
import { Modal, Notice } from "./UI";
import s from "./App.module.css";
export function Holdings({
  username,
  theme,
  setTheme,
  logout,
}: {
  username: string;
  theme: string;
  setTheme: (s: string) => void;
  logout: () => Promise<void>;
}) {
  const client = useQueryClient(),
    [editing, setEditing] = useState<Holding | null | undefined>(),
    [error, setError] = useState<unknown>();
  const list = useQuery({
    queryKey: ["holdings"],
    queryFn: () => api<Holding[]>("/v1/status-holdings"),
  });
  return (
    <main className={s.page}>
      <header className={s.heading}>
        <h1>我的会籍</h1>
        <button className={s.primary} onClick={() => setEditing(null)}>
          ＋ 添加会籍
        </button>
      </header>
      {list.isPending && <p>正在读取会籍…</p>}
      {list.error && <Notice error={list.error} retry={() => list.refetch()} />}
      {list.data?.length === 0 && (
        <p className={s.empty}>添加已有会籍，让每条路径从你出发。</p>
      )}
      <ul className={s.membershipList}>
        {list.data?.map((h) => (
          <li key={h.id} className={s.holding}>
            <div className={s.holdingInfo}>
              <strong>{h.program_display_name}</strong>
              <span>{h.tier_display_name}</span>
              <p>
                {h.valid_until
                  ? `有效期至 ${h.valid_until.replaceAll("-", " / ")}${h.valid_until < new Date().toLocaleDateString("en-CA") ? " · 已过期" : ""}`
                  : "有效期未设置"}
              </p>
            </div>
            <button onClick={() => setEditing(h)}>编辑</button>
          </li>
        ))}
      </ul>
      <div className={s.settings}>
        <span>外观</span>
        <div className={s.appearance}>
          {["light", "dark"].map((t) => (
            <button
              key={t}
              aria-pressed={theme === t}
              onClick={() => setTheme(t)}
            >
              {t === "light" ? "浅色" : "深色"}
            </button>
          ))}
        </div>
      </div>
      <div className={s.accountActions}>
        <button className={s.logout} onClick={() => logout().catch(setError)}>
          退出登录
        </button>
        <small>{username}</small>
      </div>
      {!!error && <Notice error={error} />}{" "}
      {editing !== undefined && (
        <Editor
          holding={editing}
          close={() => setEditing(undefined)}
          saved={() => {
            void client.invalidateQueries({ queryKey: ["holdings"] });
            setEditing(undefined);
          }}
        />
      )}
    </main>
  );
}
function Editor({
  holding,
  close,
  saved,
}: {
  holding: Holding | null;
  close: () => void;
  saved: () => void;
}) {
  const [q, setQ] = useState(""),
    [selected, setSelected] = useState(
      holding ? `${holding.program_key}\t${holding.tier_key}` : "",
    ),
    [date, setDate] = useState(holding?.valid_until || "");
  const catalog = useQuery({
    queryKey: ["catalog", q],
    queryFn: ({ signal }) =>
      api<{ nodes: CatalogNode[] }>(
        `/v1/membership-catalog?limit=500&q=${encodeURIComponent(q)}`,
        undefined,
        "GET",
        signal,
      ),
  });
  const mutation = useMutation({
    mutationFn: async (remove: boolean) => {
      if (remove)
        return api(`/v1/status-holdings/${holding!.id}`, undefined, "DELETE");
      const [program_key, tier_key] = selected.split("\t");
      return api(
        "/v1/status-holdings" + (holding ? `/${holding.id}` : ""),
        { program_key, tier_key, valid_until: date || null },
        holding ? "PATCH" : "POST",
      );
    },
    onSuccess: saved,
  });
  return (
    <Modal title={holding ? "编辑会籍" : "添加会籍"} onClose={close}>
      <form
        className={s.form}
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate(false);
        }}
      >
        <label>
          搜索项目
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="航司或酒店名称"
          />
        </label>
        <label>
          会籍等级
          <select
            required
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">选择会籍</option>
            {holding &&
              !catalog.data?.nodes.some(
                (n) => `${n.program_key}\t${n.tier_key}` === selected,
              ) && (
                <option value={`${holding.program_key}\t${holding.tier_key}`}>
                  {holding.program_display_name} · {holding.tier_display_name}
                </option>
              )}
            {catalog.data?.nodes.map((n) => (
              <option
                key={`${n.program_key}:${n.tier_key}`}
                value={`${n.program_key}\t${n.tier_key}`}
              >
                {n.program} · {n.tier}
              </option>
            ))}
          </select>
        </label>
        {catalog.isPending && <small>正在搜索…</small>}
        {catalog.error && <Notice error={catalog.error} />}
        <label>
          有效期（可选）
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        {mutation.error && <Notice error={mutation.error} />}
        <div className={s.formActions}>
          {holding && (
            <button
              type="button"
              className={s.remove}
              disabled={mutation.isPending}
              onClick={() => {
                if (confirm("删除这条会籍？")) mutation.mutate(true);
              }}
            >
              删除会籍
            </button>
          )}
          <button type="button" className={s.subtle} onClick={close}>
            取消
          </button>
          <button
            className={s.primary}
            disabled={!selected || mutation.isPending}
          >
            保存
          </button>
        </div>
      </form>
    </Modal>
  );
}
