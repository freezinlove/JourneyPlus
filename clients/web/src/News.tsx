import { useLayoutEffect, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api, readable, safeUrl } from "./api";
import type { Activity } from "./contracts";
import { Notice } from "./UI";
import s from "./App.module.css";
const dateText = (value: string, full = false) => {
  const date = new Date(value);
  return value && !Number.isNaN(+date)
    ? full
      ? date.toLocaleString("zh-CN", {
          timeZone: "Asia/Shanghai",
          hour12: false,
        })
      : date.toLocaleDateString("zh-CN", { timeZone: "Asia/Shanghai" })
    : "更新时间未提供";
};
const lifecycle = (value: string) =>
  (
    ({
      EXPIRED: "已结束",
      STALE: "资料已过期",
      ARCHIVED: "已归档",
      UPCOMING: "尚未开始",
      CLOSED: "已结束",
    }) as Record<string, string>
  )[value];
export function News({
  open,
}: {
  open: (id: string, version?: string) => void;
}) {
  const query = useInfiniteQuery({
    queryKey: ["news"],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<{ activities: Activity[]; has_more: boolean }>(
        `/v2/activities?view=cards&limit=20&offset=${pageParam}`,
      ),
    getNextPageParam: (page, all) =>
      page.has_more
        ? all.reduce((n, p) => n + p.activities.length, 0)
        : undefined,
  });
  const entries = query.data?.pages.flatMap((p) => p.activities) || [];
  return (
    <main className={`${s.page} ${s.journal}`} aria-label="会籍新闻">
      <h1>会籍新闻</h1>
      {query.isPending && <p>正在读取新闻…</p>}
      {query.error && (
        <Notice error={query.error} retry={() => query.refetch()} />
      )}
      {entries.map((a) => (
        <button key={a.ref} className={s.newsRow} onClick={() => open(a.ref)}>
          <div>
            <h2>{a.name || "活动资料"}</h2>
            <p>{a.card?.summary || "暂无摘要"}</p>
            {(a.is_current === false ||
              lifecycle(a.card?.lifecycle_status)) && (
              <span className={s.rowTag}>
                {[
                  a.is_current === false ? "历史版本" : "",
                  lifecycle(a.card?.lifecycle_status),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            )}
          </div>
          <time dateTime={a.updated_at}>
            {dateText(a.updated_at)}　↗
          </time>
        </button>
      ))}
      {!query.isPending && !query.error && !entries.length && (
        <p className={s.journalEnd}>暂时没有已发布活动。</p>
      )}
      {query.hasNextPage ? (
        <p className={s.journalEnd}>
          <button
            className={s.pill}
            disabled={query.isFetchingNextPage}
            onClick={() => query.fetchNextPage()}
          >
            加载更多
          </button>
        </p>
      ) : (
        entries.length > 0 && (
          <p className={s.journalEnd}>已展示全部活动简报。</p>
        )
      )}
    </main>
  );
}
export function Links({ urls, label }: { urls: string[]; label?: string }) {
  return (
    <>
      {[...new Set(urls)]
        .filter((u) => safeUrl(u))
        .map((url, i) => (
          <p key={url}>
            <a href={safeUrl(url)} target="_blank" rel="noopener noreferrer">
              {label ? `${label}${urls.length > 1 ? ` ${i + 1}` : ""}` : url} ↗
            </a>
          </p>
        ))}
    </>
  );
}
export function Reader({ id, version }: { id: string; version?: string }) {
  const query = useQuery({
    queryKey: ["brief", id, version],
    queryFn: async () => {
      const suffix = version
        ? `?version_ref=${encodeURIComponent(version)}`
        : "";
      const [brief, activity] = await Promise.all([
        api<any>(`/v2/activities/${encodeURIComponent(id)}/brief${suffix}${suffix ? "&" : "?"}include_relationship=false`),
        api<any>(`/v2/activities/${encodeURIComponent(id)}${suffix}`),
      ]);
      return { ...brief, activity };
    },
  });
  return (
    <main className={`${s.page} ${s.reader}`}>
      {query.isPending ? (
        <p>正在读取简报…</p>
      ) : query.error ? (
        <Notice error={query.error} retry={() => query.refetch()} />
      ) : (
        <Brief key={`${id}:${version || "current"}`} data={query.data} relationship={<BriefRelationship id={id} version={query.data.activity.version_ref} />} />
      )}
    </main>
  );
}
function BriefRelationship({ id, version }: { id: string; version?: string }) {
  const query = useQuery({
    queryKey: ["brief-relationship", id, version],
    queryFn: ({ signal }) => api<Relationship>(
      `/v2/activities/${encodeURIComponent(id)}/relationship${version ? `?version_ref=${encodeURIComponent(version)}` : ""}`,
      undefined, "GET", signal,
    ),
  });
  if (query.error) return <Notice error={query.error} retry={() => query.refetch()} />;
  return query.data ? <RelationshipCards data={query.data} /> : <div className={s.relationshipState} role="status">正在查看与你的会籍的关系…</div>;
}
type Relationship = { status: string; text: string; path?: string[]; path_labels?: string[] };
function RelationshipCards({ data }: { data?: Relationship }) {
  const labels = data?.path_labels || [];
  const viewport = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [data]);
  const naturalWidth = labels.length * 170 + Math.max(0, labels.length - 1) * 46;
  const scale = width ? Math.min(1, width / naturalWidth) : 1;
  if (!data?.path?.length || labels.length !== data.path.length || labels.length < 2)
    return <div className={s.relationshipState}>{data?.text || "暂未计算"}</div>;
  return <>
    <div ref={viewport} className={s.relationshipViewport}>
    <div className={s.relationshipPath} aria-label="我的会籍匹配路径"
      style={{ width: Math.max(width, naturalWidth), zoom: scale }}>
      {labels.map((label, index) => {
        const split = label.lastIndexOf(" · ");
        const program = split < 0 ? label : label.slice(0, split);
        const tier = split < 0 ? "" : label.slice(split + 3);
        return <div className={s.relationshipStep} key={`${index}:${label}`}>
          {index > 0 && <span className={s.relationshipArrow} aria-hidden="true">→</span>}
          <div className={s.relationshipNode}>
            <span className={s.relationshipLabel}>{index === 0 ? "我的会籍" : index === labels.length - 1 ? "目标会籍" : "中间会籍"}</span>
            <strong>{program}</strong>
            {tier && <small>{tier}</small>}
          </div>
        </div>;
      })}
    </div>
    </div>
    <p className={s.relationshipNote}>仍需满足对应方案的地区和其他申请条件。</p>
  </>;
}
const unique = (values: string[]) => [...new Set(values.filter(Boolean))];
function compactTier(value: string, target: string) {
  const raw = value || "通用";
  return (
    (target || "")
      .split(/[,/]/)
      .map((x) => x.trim())
      .filter(Boolean)
      .find((x) => raw.toLocaleLowerCase().endsWith(x.toLocaleLowerCase())) ||
    raw
  );
}
/** Same fields and row/column semantics as product/static/brief_view.js. */
export function MappingTable({ data: d }: { data: any }) {
  const mappings = d.facts?.status_mappings || (d.options || []).flatMap((o: any) =>
    (o.mappings || []).map((m: any) => ({ ...m,
      source_program: m.source_program || m.from_program,
      source_tiers: m.source_tiers || m.from_tiers || [],
      target_tier: m.target_tier || m.to_tier,
    })));
  const targets = unique(
    mappings.map((m: any) => compactTier(m.target_tier, d.target_status)),
  );
  const programs = unique(
    mappings.map((m: any) => m.source_program || "其他会籍"),
  );
  if (!mappings.length) return <p>原文没有可展示的会籍映射表。</p>;
  return (
    <div className={s.table}>
      <table>
        <thead>
          <tr>
            <th scope="col">现有会籍项目</th>
            {targets.map((t) => (
              <th scope="col" key={t}>
                匹配至 {t}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {programs.map((program) => (
            <tr key={program}>
              <th scope="row">{program}</th>
              {targets.map((target) => (
                <td key={target}>
                  {mappings
                    .filter(
                      (m: any) =>
                        (m.source_program || "其他会籍") === program &&
                        compactTier(m.target_tier, d.target_status) === target,
                    )
                    .map((m: any, i: number) => (
                      <div key={i}>
                        {i > 0 && <hr />}
                        {(m.source_tiers || []).map((tier: string) => (
                          <div key={tier}>{tier}</div>
                        ))}
                        {m.availability === "UNAVAILABLE"
                          ? "不可用"
                          : !m.source_tiers?.length
                            ? "未说明原等级"
                            : ""}
                        {m.availability === "CONDITIONAL" && (
                          <small>有条件／可选</small>
                        )}
                        {m.availability === "UNKNOWN" && (
                          <small>可用性待确认</small>
                        )}
                        {m.conflict && <small>信息有冲突</small>}
                        {(m.conditions || m.conflict_note) && (
                          <details>
                            <summary>条件说明</summary>
                            {unique([m.conditions, m.conflict_note]).map(
                              (note) => (
                                <p key={note}>{readable(note)}</p>
                              ),
                            )}
                          </details>
                        )}
                      </div>
                    ))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function PriceTable({ data: d }: { data: any }) {
  const routes = d.routes || [];
  const targets = unique(
    routes.flatMap((r: any) =>
      (r.prices || []).map((p: any) => p.target_tier || "通用"),
    ),
  );
  if (!routes.length || !targets.length)
    return <p>原文没有可展示的匹配费用表。</p>;
  return (
    <div className={s.table}>
      <table>
        <thead>
          <tr>
            <th scope="col">申请方式</th>
            {targets.map((t) => (
              <th key={t} scope="col">
                {t}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {routes.map((r: any, i: number) => (
            <tr key={i}>
              <th scope="row">
                {r.scope || "默认申请方式"}
                {unique([r.region, r.eligibility, r.cost, r.conflict_note])
                  .filter((x) => x !== r.scope)
                  .map((note) => (
                    <small key={note}>{note}</small>
                  ))}
                {r.conflict && <small>信息有冲突</small>}
              </th>
              {targets.map((t) => {
                const prices = (r.prices || []).filter(
                  (p: any) => (p.target_tier || "通用") === t,
                );
                return (
                  <td key={t}>
                    {!prices.length
                      ? "—"
                      : prices.map((p: any, j: number) => (
                          <div key={j}>
                            {p.amount != null ? (
                              <>
                                <strong>
                                  {`${p.currency || ""} ${String(p.amount).replace(/\.0+$/, "")}`.trim()}
                                </strong>
                                {p.availability === "CONDITIONAL" && (
                                  <small>
                                    有条件／可选费用
                                    {p.raw_text ? `：${p.raw_text}` : ""}
                                  </small>
                                )}
                                {p.availability === "UNKNOWN" && (
                                  <small>可用性待确认</small>
                                )}
                              </>
                            ) : (
                              (
                                {
                                  UNAVAILABLE: "不可用",
                                  CONDITIONAL: "有条件",
                                  UNKNOWN: "费用待核实",
                                } as Record<string, string>
                              )[p.availability] ||
                              p.raw_text ||
                              "费用待核实"
                            )}
                          </div>
                        ))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function ThirdPartySupplements({ activity }: { activity?: any }) {
  const supplements = (activity?.facts?.article_supplements || []).flatMap(
    (supplement: any) => {
      const highlights = unique((supplement.highlights || []).map(
        (point: unknown) => typeof point === "string" ? point :
          point && typeof point === "object" && "text" in point && typeof point.text === "string" ? point.text : "",
      )).map(text => text.trim()).filter(Boolean);
      if (!highlights.length) return [];
      const source = (activity.sources || []).find(
        (item: any) => item.document_version_ref === supplement.source_document_ref,
      );
      return [{ highlights, url: source?.url ? safeUrl(source.url) : undefined }];
    },
  );
  if (!supplements.length) return null;
  return <section>
    <h2>第三方补充</h2>
    {supplements.map((supplement: { highlights: string[]; url: string | undefined }, index: number) => (
      <div key={index}>
        {supplement.highlights.map(text => <p key={text}>{text}</p>)}
        {supplement.url && <div className={s.sourceLine}>
          <a href={supplement.url} target="_blank" rel="noopener noreferrer">
            来源：{sourceLabel(supplement.url)}
          </a>
          <span>↗</span>
        </div>}
      </div>
    ))}
  </section>;
}
export function Brief({
  data: d,
  relationship,
}: {
  data: any;
  relationship?: import("react").ReactNode;
}) {
  const activity = d.activity;
  const baseSummary = d.brief?.summary || activity?.card?.summary || d.summary || "";
  const applicationLinks = unique((d.action_links || []).map((url: string) => {
    try { return new URL(url).href; } catch { return url; }
  })).filter(url => safeUrl(url));
  return (
    <>
      <div className={s.readerMeta}>
        {d.program || activity?.name} / {d.brief ? "会籍简报" : "活动资料"}
      </div>
      <h1>{d.brief?.title || activity?.name || `${d.program} 会籍匹配活动`}</h1>
      <p className={s.lede}>{baseSummary}</p>
      {lifecycle(d.lifecycle_status) && (
        <p role="status">{lifecycle(d.lifecycle_status)}</p>
      )}
      <div className={s.readerSummary}>
        <div>
          <span>付费情况</span>
          <strong>{d.fee?.label || "费用待确认"}</strong>
        </div>
        <div>
          <span>简报更新于（北京时间）</span>
          {d.brief_updated_at ? dateText(d.brief_updated_at, true) : "尚未生成"}
        </div>
      </div>
      <section>
        <h2>和我的关系</h2>
        {relationship || <RelationshipCards data={d.relationship} />}
      </section>
      <ThirdPartySupplements activity={activity} />
      <section>
        <h2>申请入口</h2>
        {applicationLinks.length ? (
          <div>
            {applicationLinks
              .map((url, i) => (
                <a
                  key={url}
                  className={s.primary}
                  href={safeUrl(url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  前往申请页面{applicationLinks.length > 1 ? ` ${i + 1}` : ""}
                  <span>↗</span>
                </a>
              ))}
          </div>
        ) : (
          <p>暂无申请入口。</p>
        )}
      </section>
      <section>
        <details className={s.tableDisclosure}>
          <summary><h2>会籍匹配表</h2></summary>
          <MappingTable data={d} />
        </details>
      </section>
      <section>
        <details className={s.tableDisclosure}>
          <summary><h2>价格表</h2></summary>
          <PriceTable data={d} />
        </details>
      </section>
      <section>
        <h2>原文链接</h2>
        {d.source_links?.length ? (
          unique(d.source_links)
            .filter((url) => safeUrl(url))
            .map((url) => (
              <div className={s.sourceLine} key={url}>
                <a
                  href={safeUrl(url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {sourceLabel(url)}
                </a>
                <span>↗</span>
              </div>
            ))
        ) : (
          <p>暂无来源链接。</p>
        )}
      </section>
    </>
  );
}
function sourceLabel(link: string) {
  try {
    const u = new URL(link);
    return /\/faq\/?$/i.test(u.pathname)
      ? "官方 FAQ"
      : /\/terms\/?$/i.test(u.pathname)
        ? "官方条款"
        : u.pathname === "/"
          ? "官方活动页"
          : u.hostname + u.pathname;
  } catch {
    return link;
  }
}
