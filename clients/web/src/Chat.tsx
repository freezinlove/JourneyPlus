import { useCallback, useEffect, useRef, useState } from "react";
import { StreamText } from "./StreamText";
import { ArrowUp, Square } from "lucide-react";
import { api, ApiError } from "./api";
import { terminal, type Workspace, type Message } from "./contracts";
import { Presentation } from "./Presentation";
import { Notice } from "./UI";
import { BrandMark } from "./Icons";
import s from "./App.module.css";
export function Chat({
  openActivity,
}: {
  openActivity: (id: string, v?: string) => void;
}) {
  const [ws, setWs] = useState<Workspace>(),
    [messages, setMessages] = useState<Message[]>([]),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(""),
    [error, setError] = useState<unknown>(),
    [draft, setDraft] = useState("");
  const current = useRef<Workspace | undefined>(undefined),
    stream = useRef<EventSource | undefined>(undefined),
    run = useRef(""),
    generation = useRef(0),
    input = useRef<HTMLTextAreaElement>(null),
    scroll = useRef<HTMLDivElement>(null),
    bottom = useRef(true),
    pending = useRef<
      | {
          text: string;
          subject_refs: string[];
          client_message_id: string;
          expected_revision: number;
        }
      | undefined
    >(undefined);
  const hydrate = useCallback(async (id: string) => {
    const token = generation.current;
    const data = await api<Workspace>(`/v3/agent/workspaces/${id}`);
    if (token !== generation.current) return data;
    current.current = data;
    setWs(data);
    setMessages(data.messages);
    return data;
  }, []);
  const subscribe = useCallback(
    (id: string, rid: string, seq = 0) => {
      stream.current?.close();
      run.current = rid;
      setBusy(true);
      setProgress("正在思考…");
      const token = generation.current;
      const source = new EventSource(
        `/v3/agent/workspaces/${id}/runs/${rid}/events?after=${seq}`,
      );
      stream.current = source;
      source.onmessage = (e) => {
        if (token !== generation.current) return;
        const event = JSON.parse(e.data),
          p = event.payload;
        if (event.type === "text_delta") setProgress("");
        if (event.type === "text_delta")
          setMessages((old) => {
            const found = old.find((m) => m.id === p.message_id);
            return found
              ? old.map((m) =>
                  m.id === p.message_id
                    ? {
                        ...m,
                        content: [
                          {
                            type: "text",
                            text: (m.content[0]?.text || "") + p.text,
                          },
                        ],
                      }
                    : m,
                )
              : [
                  ...old,
                  {
                    id: p.message_id,
                    role: "assistant",
                    content: [{ type: "text", text: p.text }],
                  },
                ];
          });
        if (event.type === "presentation.created")
          setMessages((old) => [
            ...old,
            {
              id: p.presentation_ref,
              role: "assistant",
              content: [],
              attachments: { presentation_refs: [p.presentation_ref] },
            },
          ]);
        if (event.type === "tool.started") setProgress(p.label);
        if (event.type === "resource.notice") setProgress(p.message);
        if (event.type === "operation.applied")
          setMessages((old) => [
            ...old,
            {
              id: p.operation_ref,
              role: "assistant",
              content: [{ type: "text", text: p.summary }],
            },
          ]);
        if (
          ["completed", "partial", "canceled", "failed"].includes(event.type)
        ) {
          source.close();
          setBusy(false);
          setProgress(
            event.type === "failed"
              ? "本轮未完成，可重试。"
              : event.type === "canceled"
                ? "已停止，已完成的操作保留。"
                : "",
          );
          void hydrate(id).catch(setError);
        }
      };
      source.onerror = () => {
        if (token !== generation.current) return;
        setProgress("连接中断，正在恢复…");
        void api<Workspace>(`/v3/agent/workspaces/${id}`)
          .then((data) => {
            if (token !== generation.current) return;
            const r = data.runs.find((x) => x.run_id === rid);
            if (r && terminal(r.status)) {
              source.close();
              setBusy(false);
              setProgress("");
              void hydrate(id);
            }
          })
          .catch((e) => {
            source.close();
            setBusy(false);
            setError(e);
          });
      };
    },
    [hydrate],
  );
  const start = useCallback(
    async (fresh = false) => {
      const token = ++generation.current;
      stream.current?.close();
      current.current = undefined;
      setWs(undefined);
      setMessages([]);
      setError(null);
      setProgress("");
      setBusy(true);
      pending.current = undefined;
      try {
        const data = await api<Workspace>(
          fresh ? "/v3/agent/workspaces" : "/v3/agent/workspaces/current",
          fresh ? {} : undefined,
        );
        if (token !== generation.current) return;
        await hydrate(data.id);
        if (token !== generation.current) return;
        const w = current.current!;
        const active = w.runs.find((r) => !terminal(r.status));
        if (active) subscribe(w.id, active.run_id, active.last_seq);
        else setBusy(false);
      } catch (e) {
        setError(e);
        setBusy(false);
      }
    },
    [hydrate, subscribe],
  );
  useEffect(() => {
    void start();
    const fresh = () => void start(true);
    window.addEventListener("new-conversation", fresh);
    return () => {
      generation.current++;
      stream.current?.close();
      window.removeEventListener("new-conversation", fresh);
    };
  }, [start]);
  useEffect(() => {
    const area = scroll.current;
    const content = area?.firstElementChild;
    if (!area || !content) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (bottom.current) area.scrollTop = area.scrollHeight;
      });
    });
    observer.observe(content);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);
  useEffect(() => {
    const el = input.current;
    if (!el) return;
    const resize = () => {
      if (!el.getClientRects().length) return;
      el.style.height = "26px";
      const height = Math.min(156, Math.max(26, el.scrollHeight));
      el.style.height = height + "px";
      el.closest("form")?.setAttribute("data-multiline", String(height > 26));
      el.style.overflowY = el.scrollHeight > 156 ? "auto" : "hidden";
      scroll.current?.style.setProperty(
        "--composer-space",
        Math.max(100, height + 66) + "px",
      );
    };
    resize();
    let previousWidth = 0;
    const observer = new ResizeObserver(([entry]) => {
      if (previousWidth !== entry.contentRect.width) {
        previousWidth = entry.contentRect.width;
        resize();
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [draft]);
  async function send(text: string, refs: string[] = []) {
    if (busy || !current.current || !text.trim()) return;
    const w = current.current;
    const token = generation.current;
    setBusy(true);
    setProgress("正在思考…");
    bottom.current = true;
    setError(null);
    const retrying = pending.current?.text === text;
    const body = retrying
      ? pending.current!
      : {
          text,
          subject_refs: refs,
          client_message_id: crypto.randomUUID(),
          expected_revision: w.revision,
        };
    pending.current = body;
    try {
      if (!retrying) {
        const latest = await api<Workspace>(`/v3/agent/workspaces/${w.id}`);
        body.expected_revision = latest.revision;
      }
      const result = await api<{ run_id: string; status: string }>(
        `/v3/agent/workspaces/${w.id}/runs`,
        body,
      );
      if (token !== generation.current) return;
      pending.current = undefined;
      setDraft("");
      bottom.current = true;
      const snapshot = await hydrate(w.id);
      if (token !== generation.current) return;
      const active = snapshot.runs.find((r) => r.run_id === result.run_id);
      if (terminal(active?.status || result.status)) { setBusy(false); setProgress(""); }
      else subscribe(w.id, result.run_id, active?.last_seq || 0);
    } catch (e) {
      if (token !== generation.current) return;
      setBusy(false);
      setProgress("");
      setError(e);
      if (e instanceof ApiError && e.status === 409) {
        pending.current = undefined;
        await hydrate(w.id);
      }
      if (e instanceof ApiError && e.status === 410) await start();
    }
  }
  const empty = !messages.some((message) => message.role !== "tool") && !busy;
  return (
    <>
      <div
        ref={scroll}
        className={s.chatScroll}
        onScroll={() => {
          const el = scroll.current!;
          bottom.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 100;
        }}
      >
        <div className={s.conversation}>
          {ws?.next_cursor && (
            <button
              className={s.pill}
              onClick={async () => {
                try {
                  const older = await api<Workspace>(
                    `/v3/agent/workspaces/${ws.id}?cursor=${encodeURIComponent(ws.next_cursor!)}`,
                  );
                  setMessages((m) => [...older.messages, ...m]);
                  setWs((w) =>
                    w ? { ...w, next_cursor: older.next_cursor } : w,
                  );
                } catch (e) {
                  setError(e);
                }
              }}
            >
              加载更早消息
            </button>
          )}
          {messages
            .filter((m) => m.role !== "tool")
            .map((m) => (
              <article
                key={m.id}
                className={m.role === "user" ? s.userMessage : s.answer}
              >
                {m.role === "assistant" && (
                  <small className={s.speaker}>
                    <BrandMark />
                    JourneyPlus
                  </small>
                )}
                {m.content
                  .filter((p) => p.type === "text")
                  .map((p, i) => (
                    <StreamText key={i} text={p.text || ""} live={busy && m.role === "assistant" && m === messages[messages.length - 1]} />
                  ))}
                {m.attachments?.operations?.map((o, i) => (
                  <p key={i}>{o.summary}</p>
                ))}
                {m.attachments?.presentation_refs?.map((ref) => (
                  <Presentation
                    key={ref}
                    wid={ws!.id}
                    reference={ref}
                    send={send}
                    openActivity={openActivity}
                  />
                ))}
                {m.metadata?.interrupted && (
                  <small>回答已中断，已有内容保留。</small>
                )}
              </article>
            ))}
          {progress && (
            <p className={s.processing} role="status" aria-live="polite" data-active={busy}>
              {busy && <span className={s.processingDot} aria-hidden="true" />}
              {progress}
            </p>
          )}
          {!!error && (
            <Notice
              error={error}
              retry={() => (current.current ? send(draft) : start())}
            />
          )}
        </div>
      </div>
      <form
        className={`${s.composer} ${empty ? s.composerEmpty : ""}`}
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        {empty && (
          <h1 className={s.emptyPrompt}>想用你的会籍，开启怎样的下一程？</h1>
        )}
        <textarea
          ref={input}
          disabled={!ws}
          rows={1}
          aria-label="消息"
          value={draft}
          maxLength={16000}
          placeholder="说说你持有的会籍，或想了解的匹配机会…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              void send(draft);
            }
          }}
        />
        {busy ? (
          <button
            type="button"
            aria-label="停止回答"
            onClick={async () => {
              if (current.current && run.current) {
                try {
                  await api(
                    `/v3/agent/workspaces/${current.current.id}/runs/${run.current}/cancel`,
                    { idempotency_key: `cancel:${run.current}` },
                  );
                  setProgress("正在停止…");
                } catch (e) {
                  setError(e);
                }
              }
            }}
          >
            <Square size={16} />
          </button>
        ) : (
          <button aria-label="发送" disabled={!ws || !draft.trim()}>
            <ArrowUp size={20} />
          </button>
        )}
      </form>
    </>
  );
}
