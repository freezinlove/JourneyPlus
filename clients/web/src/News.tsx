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
        api<any>(`/v2/activities/${encodeURIComponent(id)}/brief${suffix}`),
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
        <Brief data={query.data} pinned={!!version} />
      )}
    </main>
  );
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
  const mappings = d.facts?.status_mappings || [];
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
                                  UNKNOWN: "未公布",
                                } as Record<string, string>
                              )[p.availability] ||
                              p.raw_text ||
                              "未公布"
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
export function Brief({
  data: d,
  pinned = false,
}: {
  data: any;
  pinned?: boolean;
}) {
  const activity = d.activity;
  return (
    <>
      <div className={s.readerMeta}>
        {d.program || activity?.name} / {d.brief ? "会籍简报" : "活动资料"}
      </div>
      <h1>{d.brief?.title || activity?.name || `${d.program} 会籍匹配活动`}</h1>
      <p className={s.lede}>
        {d.brief?.summary || activity?.card?.summary || d.summary}
      </p>
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
        <div>
          <span>读取版本</span>
          {pinned ? "指定版本" : "当前版本"}
        </div>
      </div>
      <section>
        <h2>和我的关系</h2>
        <p>{d.relationship?.text || "暂未计算"}</p>
      </section>
      <section>
        <h2>申请入口</h2>
        {d.action_links?.length ? (
          <div>
            {unique(d.action_links)
              .filter((url) => safeUrl(url))
              .map((url, i) => (
                <a
                  key={url}
                  className={s.primary}
                  href={safeUrl(url)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  前往申请页面{d.action_links.length > 1 ? ` ${i + 1}` : ""}
                  <span>↗</span>
                </a>
              ))}
          </div>
        ) : (
          <p>暂无申请入口。</p>
        )}
      </section>
      {activity &&
        [
          "eligibility",
          "challenge_requirements",
          "application_start",
          "deadline",
          "status_validity",
          "caveats",
        ].some((key) => activity.facts?.[key]) && (
          <section>
            <h2>申请前了解</h2>
            {[
              ["eligibility", "申请资格"],
              ["challenge_requirements", "挑战要求"],
              ["application_start", "申请开始"],
              ["deadline", "申请截止"],
              ["status_validity", "会籍有效期"],
              ["caveats", "注意事项"],
            ]
              .filter(([key]) => activity.facts?.[key])
              .map(([key, label]) => (
                <div key={key}>
                  <h3 className={s.factLabel}>{label}</h3>
                  <p>{readable(activity.facts[key])}</p>
                </div>
              ))}
          </section>
        )}
      <section>
        <h2>完整映射表</h2>
        <MappingTable data={d} />
      </section>
      <section>
        <h2>价格表</h2>
        <PriceTable data={d} />
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
