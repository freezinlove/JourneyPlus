import { useLayoutEffect, useRef, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "./api";
import type { CatalogNode } from "./contracts";
import type { Route, Step } from "./contracts";
import s from "./App.module.css";
// Only lay out already computed paths; never infer a business relationship.
export function layout(routes: Route[]) {
  const nodes = new Map<
      string,
      {
        id: string;
        label: string;
        level: number;
        steps: Step[];
        x: number;
        y: number;
      }
    >(),
    edges: { from: string; to: string; step: Step }[] = [];
  for (const r of routes) {
    const steps = r.step_refs.map((ref) => r.steps[ref]).filter(Boolean);
    steps.forEach((step, i) => {
      const from = step.from_tier_id || step.from || "public",
        to = step.to_tier_id || step.to;
      if (!nodes.has(from))
        nodes.set(from, {
          id: from,
          label: step.from || "公开申请",
          level: i,
          steps: [],
          x: 0,
          y: 0,
        });
      if (!nodes.has(to))
        nodes.set(to, {
          id: to,
          label: step.to,
          level: i + 1,
          steps: [],
          x: 0,
          y: 0,
        });
      const target = nodes.get(to)!;
      target.level = Math.max(target.level, i + 1);
      if (!target.steps.some((s) => s.ref === step.ref))
        target.steps.push(step);
      if (!edges.some((e) => e.step.ref === step.ref))
        edges.push({ from, to, step });
    });
  }
  const levels = new Map<number, number>();
  for (const n of nodes.values()) {
    const row = levels.get(n.level) || 0;
    n.x = n.level * 260 + 16;
    n.y = row * 128 + 24;
    levels.set(n.level, row + 1);
  }
  return {
    nodes: [...nodes.values()],
    edges,
    width: Math.max(360, ...[...nodes.values()].map((n) => n.x + 192)),
    height: Math.max(152, ...[...nodes.values()].map((n) => n.y + 112)),
  };
}
export function Graph({
  routes,
  select,
}: {
  routes: Route[];
  select: (steps: Step[]) => void;
}) {
  const g = layout(routes);
  const [mobile, setMobile] = useState(matchMedia("(max-width:600px)").matches);
  const [originWidth, setOriginWidth] = useState(126);
  const originRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [availableWidth, setAvailableWidth] = useState(754);
  const catalogs = useQueries({
    queries: g.nodes.map((n) => ({
      queryKey: ["graph-catalog", n.label],
      queryFn: () =>
        api<{ nodes: CatalogNode[] }>(
          `/v1/membership-catalog?limit=20&q=${encodeURIComponent(n.label)}`,
        ),
      staleTime: 300000,
    })),
  });
  const catalogNodes = catalogs.flatMap((c) => c.data?.nodes || []);
  const names = (label: string) => {
    const uncertain = g.nodes.find(n => n.label === label)?.steps.find(s => s.mapping_status === "UNCONFIRMED");
    if (uncertain?.target_program_name) return { program: uncertain.target_program_name, tier: "可能获得：" + uncertain.possible_target_tiers?.join(" 或 ") };
    const found = catalogNodes.find((n) => `${n.program} ${n.tier}` === label);
    return found
      ? { program: found.program, tier: found.tier }
      : { program: label, tier: "" };
  };
  useLayoutEffect(() => {
    const q = matchMedia("(max-width:600px)");
    const change = () => setMobile(q.matches);
    q.addEventListener("change", change);
    return () => q.removeEventListener("change", change);
  }, []);
  useLayoutEffect(() => {
    if (!originRef.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setOriginWidth(entry.target.getBoundingClientRect().width),
    );
    observer.observe(originRef.current);
    return () => observer.disconnect();
  }, [routes]);
  useLayoutEffect(() => {
    if (!viewportRef.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setAvailableWidth(entry.contentRect.width),
    );
    observer.observe(viewportRef.current);
    return () => observer.disconnect();
  }, []);
  const targetWidth = mobile
    ? 168
    : Math.min(304, Math.max(170, availableWidth - originWidth - 110));
  const counts = g.nodes.reduce((m, n) => {
    m.set(n.level, (m.get(n.level) || 0) + 1);
    return m;
  }, new Map<number, number>());
  const maxRows = Math.max(1, ...counts.values());
  const hasUnconfirmed = g.edges.some(e => e.step.mapping_status === "UNCONFIRMED");
  const rowSpacing = hasUnconfirmed ? 200 : mobile ? 156 : 100;
  const height = mobile
    ? Math.max(290, (maxRows - 1) * rowSpacing + (hasUnconfirmed ? 190 : 134))
    : maxRows * rowSpacing - 16;
  const seen = new Map<number, number>();
  const positions = g.nodes.map((n) => {
    const row = seen.get(n.level) || 0;
    seen.set(n.level, row + 1);
    const x = mobile
      ? n.level === 0
        ? 14
        : 224 + (n.level - 1) * 275
      : n.level === 0
        ? 0
        : originWidth + 110 + (n.level - 1) * (targetWidth + 110);
    const y = mobile
      ? n.steps.length
        ? 36 + row * rowSpacing
        : (height - ((counts.get(n.level) || 1) - 1) * rowSpacing - 74) / 2 + row * rowSpacing
      : row * rowSpacing + (maxRows - (counts.get(n.level) || 1)) * rowSpacing / 2;
    return { ...n, x, y: !mobile && !n.steps.length ? y + 6.5 : y };
  });
  const width =
    Math.max(
      ...positions.map(
        (n) =>
          n.x + (n.steps.length ? targetWidth : mobile ? 126 : originWidth),
      ),
    ) + (mobile ? 14 : 0);
  return (
    <div className={s.graph}>
      <div className={s.graphHint}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 12h16M8 8l-4 4 4 4m8-8 4 4-4 4" />
        </svg>
        左右滑动查看路径
      </div>
      <div
        ref={viewportRef}
        className={s.graphScroll}
        tabIndex={0}
        aria-label="会籍匹配路径"
      >
        <div className={s.graphScene} style={{ width, height }}>
          <svg
            width={width}
            height={height}
            className={s.lines}
            aria-hidden="true"
          >
            {g.edges.map((e, i) => {
              const a = positions.find((n) => n.id === e.from)!,
                b = positions.find((n) => n.id === e.to)!;
              const x =
                  a.x +
                  (a.steps.length ? targetWidth : mobile ? 126 : originWidth),
                y = a.y + (mobile ? 37 : a.steps.length ? 42 : 35.5),
                tx = b.x,
                ty = b.y + (mobile ? 37 : 42),
                siblings = positions.filter((n) => n.level === a.level),
                lane = siblings.findIndex((n) => n.id === a.id),
                bend = x + 26 + (siblings.length > 1 ? lane * Math.min(18, 48 / (siblings.length - 1)) : 4);
              return (
                <g key={i} strokeDasharray={e.step.mapping_status === "UNCONFIRMED" ? "6 5" : undefined}>
                  <path
                    d={
                      y === ty
                        ? `M${x} ${y} H${tx}`
                        : `M${x} ${y} H${bend - 12} Q${bend} ${y} ${bend} ${y + (ty < y ? -14 : 14)} V${ty + (ty < y ? 12 : -12)} Q${bend} ${ty} ${bend + 12} ${ty} H${tx}`
                    }
                  />
                  {!a.steps.length && (
                    <circle cx={x + (mobile ? 0 : 3)} cy={y} r="3" />
                  )}
                  {mobile && (
                    <path
                      d={`M${tx - 7} ${ty - 4} L${tx} ${ty} L${tx - 7} ${ty + 4}`}
                    />
                  )}
                </g>
              );
            })}
          </svg>
          {g.edges.map((e, i) => {
            const b = positions.find((n) => n.id === e.to)!;
            const paid = e.step.paid ?? e.step.cost?.paid;
            return (
              (
                <span
                  className={s.edgeFee}
                  key={i}
                  style={{
                    left: b.x - (mobile ? 52 : 8),
                    top: b.y + (mobile ? 16 : 18),
                  }}
                >
                  {e.step.mapping_status === "UNCONFIRMED" ? "等级待确认" : paid === true ? "付费申请" : paid === false ? "免费申请" : "费用待核实"}
                </span>
              )
            );
          })}
          {positions.map((n) => {
            const name = names(n.label);
            const content = (
              <>
                <span>
                  <strong>{name.program}</strong>
                  {name.tier && <small>{name.tier}</small>}
                </span>
                {n.steps.length > 0 && <span className={s.go}>↗</span>}
              </>
            );
            return n.steps.length ? (
              <button
                key={n.id}
                className={s.node}
                style={{ left: n.x, top: n.y, width: targetWidth, ...(n.steps.some(s => s.mapping_status === "UNCONFIRMED") ? { height: "auto", minHeight: mobile ? 74 : 84 } : {}) }}
                aria-label={`${n.label}，查看申请详情`}
                onClick={() => select(n.steps)}
              >
                {content}
              </button>
            ) : (
              <div
                ref={
                  n === positions.find((p) => !p.steps.length)
                    ? originRef
                    : undefined
                }
                key={n.id}
                className={`${s.node} ${s.origin}`}
                style={{ left: n.x, top: n.y }}
              >
                {content}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
