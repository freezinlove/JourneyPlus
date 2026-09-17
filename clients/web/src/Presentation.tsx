import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, readable } from "./api";
import type { Presentation as Payload, Step } from "./contracts";
import { StreamText } from "./StreamText";
import { Graph } from "./Graph";
import { Modal, Notice } from "./UI";
import { Links, MappingTable } from "./News";
import s from "./App.module.css";
export function Presentation({
  wid,
  reference,
  live = false,
  send,
  openActivity,
}: {
  wid: string;
  reference: string;
  live?: boolean;
  send: (t: string, refs?: string[]) => void;
  openActivity: (id: string, v?: string) => void;
}) {
  const query = useQuery({
    queryKey: ["artifact", wid, reference],
    queryFn: () =>
      api<{ payload: Payload }>(
        `/v3/agent/workspaces/${wid}/artifacts/${reference.replace("artifact:", "").split("#")[0]}`,
      ),
  });
  const [completedAnswer, setCompletedAnswer] = useState<string>();
  const [steps, setSteps] = useState<Step[]>(),
    [object, setObject] = useState<any>();
  useEffect(() => {
    if (query.data)
      void api(
        `/v3/agent/workspaces/${wid}/presentations/${reference.replace("artifact:", "")}/feedback`,
        { event_id: `rendered:${reference}`, status: "RENDERED" },
      ).catch(() => {});
  }, [query.data, wid, reference]);
  if (query.isPending) return <p>正在读取展示结果…</p>;
  if (query.error)
    return <Notice error={query.error} retry={() => query.refetch()} />;
  async function focus(objectRef?: string) {
    if (!objectRef) return;
    try {
      const w = await api<{ revision: number }>(`/v3/agent/workspaces/${wid}`);
      await api(`/v3/agent/workspaces/${wid}/focus`, {
        presentation_ref: reference,
        object_ref: objectRef,
        expected_revision: w.revision,
      });
    } catch {
      /* Detail remains readable during concurrent runs. */
    }
  }
  const p = query.data!.payload;
  const showBlocks = !live || !p.answer?.trim() || completedAnswer === p.answer;
  return (
    <>
      {p.answer && <StreamText text={p.answer} live={live} onComplete={setCompletedAnswer} />}
      {showBlocks && <div className={live ? s.presentationReveal : undefined}>
      {p.blocks.map((b, i) => (
        <section key={i}>
          {b.title && <h3>{b.title}</h3>}
          {b.reason && <p>{b.reason}</p>}
          {b.type === "route_graph" ? (
            <>
              <Graph
                routes={b.payload.objects.map((o) => o.data)}
                select={(chosen) => {
                  setSteps(chosen);
                  void focus(chosen[0]?.ref);
                }}
              />
              <div className={s.followup}>
                <button
                  className={s.pill}
                  onClick={() =>
                    send(
                      "帮我查看这些会籍匹配的申请经验",
                      b.payload.objects.map((o) => o.ref),
                    )
                  }
                >
                  查看申请经验
                </button>
              </div>
            </>
          ) : b.type === "mapping_table" ? (
            b.payload.objects.map((o) => (
              <MappingTable key={o.ref} data={o.data} />
            ))
          ) : b.type === "comparison" ? (
            <div className={s.table}>
              <table>
                <thead>
                  <tr>
                    <th>方案</th>
                    {b.columns?.map((c) => (
                      <th key={c}>
                        {(
                          {
                            cost: "费用",
                            steps: "步骤",
                            conditions: "条件",
                            challenge: "挑战",
                            eligibility: "资格",
                            window: "申请窗口",
                            validity: "有效期",
                          } as Record<string, string>
                        )[c] || c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.payload.objects.map((o) => (
                    <tr key={o.ref}>
                      <td>
                        <button
                          onClick={() =>
                            setSteps(
                              o.data.step_refs.map((r) => o.data.steps[r]),
                            )
                          }
                        >
                          {o.data.from} → {o.data.to}
                        </button>
                      </td>
                      {b.columns?.map((c) => (
                        <td key={c}>
                          {c === "cost"
                            ? o.data.paid
                              ? "付费"
                              : "免费"
                            : c === "steps"
                              ? o.data.step_count
                              : readable(
                                  o.data.comparison_values?.[c] || o.data[c],
                                )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            b.payload.objects.map((o) => (
              <button
                key={o.ref}
                className={s.result}
                onClick={() =>
                  o.data.activity_ref
                    ? openActivity(o.data.activity_ref, o.data.version_ref)
                    : o.data.ref && o.data.version_ref
                      ? openActivity(o.data.ref, o.data.version_ref)
                      : setObject(o.data)
                }
              >
                <strong>
                  {o.data.name || o.data.title || o.data.to || "资料详情"} ↗
                </strong>
                <p>
                  {o.data.card?.summary ||
                    o.data.text ||
                    o.data.evidence_excerpt ||
                    o.data.summary ||
                    ""}
                </p>
              </button>
            ))
          )}
          {b.payload.research?.map((r) => (
            <button
              className={s.result}
              key={r.ref}
              onClick={() => setObject(r.data)}
            >
              公开申请经验 ↗
            </button>
          ))}
        </section>
      ))}
      {p.next_steps?.map((n) => (
        <button
          className={s.pill}
          key={n.label}
          onClick={() => send(n.message, n.subject_refs)}
        >
          {n.label}
        </button>
      ))}
      </div>}
      {steps && (
        <Modal
          title={steps[0]?.to || "申请路径"}
          onClose={() => setSteps(undefined)}
        >
          {steps.map((step) => (
            <StepDetail
              key={step.ref}
              step={step}
              openActivity={(id, version) => {
                setSteps(undefined);
                openActivity(id, version);
              }}
            />
          ))}
        </Modal>
      )}
      {object && (
        <Modal
          title={object.name || object.title || "资料详情"}
          onClose={() => setObject(undefined)}
        >
          <p>
            {readable(
              object.text ||
                object.reports ||
                object.evidence_excerpt ||
                object.facts ||
                object,
            )}
          </p>
          {object.url && <Links urls={[object.url]} label="原始资料" />}
        </Modal>
      )}
    </>
  );
}
function StepDetail({
  step,
  openActivity,
}: {
  step: Step;
  openActivity: (id: string, v?: string) => void;
}) {
  const query = useQuery({
    queryKey: ["step", step.activity_ref, step.version_ref],
    queryFn: () =>
      api<any>(
        `/v2/activities/${step.activity_ref}?version_ref=${step.version_ref}&view=path_detail`,
      ),
  });
  return (
    <section>
      <p>
        {step.from || "公开申请"} → {step.to}
      </p>
      <p>
        {step.paid === true
          ? "付费申请"
          : step.paid === false
            ? "免费申请"
            : query.data?.fee?.label}
      </p>
      {query.error && <Notice error={query.error} />}
      <Links urls={query.data?.action_links || []} label="申请入口" />
      <button
        className={`${s.primary} ${s.fullWidth}`}
        onClick={() => openActivity(step.activity_ref, step.version_ref)}
      >
        查看对应版本简报 ↗
      </button>
    </section>
  );
}
