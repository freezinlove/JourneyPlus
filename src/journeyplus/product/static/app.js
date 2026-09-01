const app = document.querySelector("#app");

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const api = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败（${response.status}）`);
  return payload;
};

const hero = (eyebrow, title, copy, action = "") => `
  <section class="hero">
    <div><p class="eyebrow">${escapeHtml(eyebrow)}</p><h1>${escapeHtml(title)}</h1><p>${escapeHtml(copy)}</p></div>
    ${action}
  </section>`;

const badge = (text, kind = "") => `<span class="badge ${kind}">${escapeHtml(text)}</span>`;
const dateText = (value) => value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(value)) : "未设置";

async function holdingsPage() {
  app.innerHTML = hero(
    "START HERE",
    "先告诉我你已经拥有的会籍",
    "只从规范化目录中选择。每个项目保存一个当前等级；再次添加同一项目会直接替换等级。",
  ) + `
    <section class="grid two">
      <div class="card">
        <h2>添加或替换会籍</h2>
        <form id="holding-form" class="grid">
          <label>搜索项目或等级<input id="catalog-query" autocomplete="off" placeholder="例如 Hilton Gold / 万豪白金"></label>
          <label>选择规范化会籍<select id="catalog-select" required><option>正在加载目录…</option></select></label>
          <label>有效期（可不填）<input id="valid-until" type="date"></label>
          <button type="submit">保存会籍</button>
          <p id="form-message" class="muted" role="status"></p>
        </form>
      </div>
      <div><h2>当前持有</h2><div id="holding-list" class="grid"></div></div>
    </section>`;

  const select = document.querySelector("#catalog-select");
  const query = document.querySelector("#catalog-query");
  let nodes = [];
  let timer;

  const loadCatalog = async () => {
    const payload = await api(`/v1/membership-catalog?q=${encodeURIComponent(query.value)}&limit=200`);
    nodes = payload.nodes;
    select.innerHTML = nodes.length
      ? nodes.map((node, index) => `<option value="${index}">${escapeHtml(node.program)} · ${escapeHtml(node.tier)}</option>`).join("")
      : "<option value=''>没有匹配的规范化会籍</option>";
  };

  const loadHoldings = async () => {
    const rows = await api("/v1/status-holdings");
    document.querySelector("#holding-list").innerHTML = rows.length
      ? rows.map((row) => `
        <article class="card holding">
          <div><strong>${escapeHtml(row.program_display_name)}</strong><span class="tier">${escapeHtml(row.tier_display_name)}</span><div class="muted">有效期：${dateText(row.valid_until)}</div></div>
          <button class="danger" data-delete="${row.id}">删除</button>
        </article>`).join("")
      : `<div class="empty"><h2>还没有会籍</h2><p>添加一项后，匹配图会从它开始一路展开。</p></div>`;
    document.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", async () => {
      await api(`/v1/status-holdings/${button.dataset.delete}`, { method: "DELETE" });
      await loadHoldings();
    }));
  };

  query.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => loadCatalog().catch(showError), 180);
  });
  document.querySelector("#holding-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const node = nodes[Number(select.value)];
    if (!node) return;
    const message = document.querySelector("#form-message");
    try {
      await api("/v1/status-holdings", {
        method: "POST",
        body: JSON.stringify({
          program_key: node.program_key,
          tier_key: node.tier_key,
          valid_until: document.querySelector("#valid-until").value || null,
        }),
      });
      message.textContent = "已保存；同项目的旧等级（如有）已替换。";
      await loadHoldings();
    } catch (error) { message.textContent = error.message; message.className = "error"; }
  });
  await Promise.all([loadCatalog(), loadHoldings()]);
}

const GRAPH_CARD_WIDTH = 220;
const GRAPH_CARD_HEIGHT = 116;
const GRAPH_HORIZONTAL_STEP = 248;
const GRAPH_LEVEL_GAP = 64;
const GRAPH_PADDING = 32;

const membershipCategory = (categories = []) => {
  if (categories.includes("AIRLINE")) return { icon: "✈", label: "航空会籍" };
  if (categories.includes("HOTEL")) return { icon: "◆", label: "酒店会籍" };
  return { icon: "◎", label: "常旅客会籍" };
};

function buildNearestMembershipTree(roots) {
  const nodeById = new Map();
  const adjacency = new Map();
  const edgeByKey = new Map();
  const rootNodeIds = [];

  const collect = (occurrence) => {
    const nodeId = occurrence.node.id;
    if (!nodeById.has(nodeId)) nodeById.set(nodeId, occurrence.node);
    occurrence.children.forEach((edge) => {
      const edgeKey = `${edge.source_node_id}\u0000${edge.target_node_id}`;
      if (!edgeByKey.has(edgeKey)) {
        edgeByKey.set(edgeKey, edge);
        if (!adjacency.has(edge.source_node_id)) adjacency.set(edge.source_node_id, []);
        adjacency.get(edge.source_node_id).push(edge);
      }
      collect(edge.child);
    });
  };
  roots.forEach((root) => {
    if (!rootNodeIds.includes(root.node.id)) rootNodeIds.push(root.node.id);
    collect(root);
  });

  // Multi-source breadth-first traversal: the first time a node is reached is
  // its nearest path. Later arrivals and all cycle/back edges stay out of the UI.
  const depthById = new Map();
  const parentEdgeById = new Map();
  const queue = [];
  rootNodeIds.forEach((nodeId) => {
    depthById.set(nodeId, 0);
    queue.push(nodeId);
  });
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const sourceId = queue[cursor];
    (adjacency.get(sourceId) || []).forEach((edge) => {
      if (depthById.has(edge.target_node_id)) return;
      depthById.set(edge.target_node_id, depthById.get(sourceId) + 1);
      parentEdgeById.set(edge.target_node_id, edge);
      queue.push(edge.target_node_id);
    });
  }

  const sequence = { value: 1 };
  const records = new Map();
  queue.forEach((nodeId) => records.set(nodeId, {
    id: `membership-node-${sequence.value++}`,
    nodeId,
    node: nodeById.get(nodeId),
    depth: depthById.get(nodeId),
    edgeFromParent: parentEdgeById.get(nodeId) || null,
    children: [],
    x: 0,
    y: 0,
  }));
  records.forEach((record) => {
    if (!record.edgeFromParent) return;
    records.get(record.edgeFromParent.source_node_id)?.children.push(record);
  });
  return {
    roots: rootNodeIds.map((nodeId) => records.get(nodeId)).filter(Boolean),
    records,
  };
}

function layoutMembershipForest(roots) {
  const nearestTree = buildNearestMembershipTree(roots);
  const nodes = [];
  const edges = [];
  let leafCursor = 0;
  let maxDepth = 0;

  const place = (node) => {
    maxDepth = Math.max(maxDepth, node.depth);
    node.children.forEach((child) => place(child));
    if (node.children.length) {
      const first = node.children[0];
      const last = node.children[node.children.length - 1];
      node.centerX = (first.centerX + last.centerX) / 2;
    } else {
      node.centerX = GRAPH_PADDING + (leafCursor + .5) * GRAPH_HORIZONTAL_STEP;
      leafCursor += 1;
    }
    node.x = node.centerX - GRAPH_CARD_WIDTH / 2;
    node.y = GRAPH_PADDING + node.depth * (GRAPH_CARD_HEIGHT + GRAPH_LEVEL_GAP);
    nodes.push(node);
    node.children.forEach((child) => edges.push({
      source: node,
      target: child,
      edge: child.edgeFromParent,
    }));
  };
  nearestTree.roots.forEach((root, index) => {
    if (index) leafCursor += .5;
    place(root);
  });
  const width = Math.max(
    720,
    GRAPH_PADDING * 2 + Math.max(1, leafCursor) * GRAPH_HORIZONTAL_STEP,
  );
  const height = Math.max(
    360,
    GRAPH_PADDING * 2 + (maxDepth + 1) * GRAPH_CARD_HEIGHT
      + maxDepth * GRAPH_LEVEL_GAP,
  );
  return { nodes, edges, width, height, maxDepth };
}

function graphNodeCard(node, rootIds) {
  const category = membershipCategory(node.node.categories);
  const isRoot = rootIds.has(node.nodeId);
  const state = isRoot ? "我的起点" : node.children.length ? "有后续路径" : "本图终点";
  const footer = node.children.length
    ? `${node.children.length} 条最近下一跳`
    : `距起点 ${node.depth} 跳`;
  return `<article
      id="${node.id}"
      class="membership-node${isRoot ? " is-root" : node.children.length ? "" : " is-terminal"}"
      style="left:${node.x}px;top:${node.y}px"
      role="treeitem"
      aria-label="${escapeHtml(`${node.node.program} ${node.node.tier}，${state}`)}"
    >
      <div class="membership-node__topline">
        <span class="membership-kind"><span aria-hidden="true">${category.icon}</span>${category.label}</span>
        <span class="node-state">${escapeHtml(state)}</span>
      </div>
      <h3>${escapeHtml(node.node.program)}</h3>
      <strong class="membership-tier">${escapeHtml(node.node.tier)}</strong>
      <div class="membership-node__footer"><span>${escapeHtml(footer)}</span></div>
    </article>`;
}

function graphFeeLabel(item, feeByEdge) {
  const labels = feeByEdge.get(`${item.edge.source_node_id}\u0000${item.edge.target_node_id}`) || [];
  if (!labels.length) return "";
  const label = labels.join(" / ");
  const left = item.target.centerX;
  const top = item.source.y + GRAPH_CARD_HEIGHT + (GRAPH_LEVEL_GAP - 26) / 2;
  return `<span class="graph-fee-label" style="left:${left}px;top:${top}px" title="${escapeHtml(labels.length > 1 ? `不同申请路线或地区的明确费用：${label}` : `明确费用：${label}`)}">${escapeHtml(label)}</span>`;
}

function renderMembershipGraph(roots, edgeFees = []) {
  const layout = layoutMembershipForest(roots);
  const feeByEdge = new Map(edgeFees.map((item) => [
    `${item.source_node_id}\u0000${item.target_node_id}`,
    item.labels,
  ]));
  const rootIds = new Set(layout.nodes.filter((node) => !node.edgeFromParent).map((node) => node.nodeId));
  const paths = layout.edges.map((item) => {
    const sourceX = item.source.centerX;
    const sourceY = item.source.y + GRAPH_CARD_HEIGHT;
    const targetX = item.target.centerX;
    const targetY = item.target.y;
    const bendY = sourceY + (targetY - sourceY) * .5;
    return `<path class="graph-link" d="M ${sourceX} ${sourceY} C ${sourceX} ${bendY}, ${targetX} ${bendY}, ${targetX} ${targetY}" marker-end="url(#graph-arrow)"/>`;
  }).join("");
  const cards = layout.nodes.map((item) => graphNodeCard(item, rootIds)).join("");
  const feeLabels = layout.edges.map((item) => graphFeeLabel(item, feeByEdge)).join("");
  return {
    nodeCount: layout.nodes.length,
    edgeCount: layout.edges.length,
    maxDepth: layout.maxDepth,
    html: `<div class="membership-graph" role="tree" aria-label="从已有会籍出发的最近匹配路径">
    <div class="membership-graph__canvas" style="width:${layout.width}px;height:${layout.height}px">
      <svg class="membership-graph__links" width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" aria-hidden="true">
        <defs><marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z"/></marker></defs>
        ${paths}
      </svg>
      ${feeLabels}${cards}
    </div>
  </div>`,
  };
}

function opportunityCard(item) {
  const path = item.path ? item.path.join(" → ") : "暂未映射到持有会籍路径";
  return `<article class="card opportunity-card">
    <div class="badges">${badge(item.source === "STATUSMATCH_OFFICIAL" ? "官方项目" : "普通文章")}${item.conflict ? badge("有冲突", "warn") : ""}</div>
    <h2>${escapeHtml(item.program)}${item.target_status ? ` · ${escapeHtml(item.target_status)}` : ""}</h2>
    <p>${escapeHtml(item.summary)}</p><p class="muted">${escapeHtml(path)}</p>
    ${item.deadline ? `<p>截止：${escapeHtml(item.deadline)}</p>` : ""}
    <a class="button secondary" href="/opportunities/${item.opportunity_id}">查看全部路线</a>
  </article>`;
}

async function matchesPage() {
  const payload = await api("/v1/personalized-matches");
  const graphView = payload.holdings.length
    ? renderMembershipGraph(payload.forest.roots, payload.edge_fees || [])
    : null;
  const graph = payload.holdings.length ? `
    <section class="card graph-panel">
      <div class="graph-panel__heading"><div><h2>最近匹配路径</h2><p class="muted">${graphView.nodeCount} 个唯一会籍 · ${graphView.edgeCount} 条最近路径 · 最远 ${graphView.maxDepth} 跳</p></div><p class="graph-hint"><span aria-hidden="true">↔</span> 横向滚动查看全部分支</p></div>
      <div class="graph-legend" aria-label="图例"><span><i class="legend-dot root"></i>我的会籍</span><span><i class="legend-dot available"></i>有后续路径</span><span><i class="legend-dot terminal"></i>本图终点</span><span><i class="legend-line"></i>最近路径</span><span><i class="legend-fee">USD</i>明确费用</span></div>
      ${graphView.html}
    </section>` : `<section class="empty"><h2>还没有可达图起点</h2><p>添加持有会籍后，系统会从它开始展开完整路径。下方仍保留没有来源会籍映射的公开匹配/挑战。</p><a class="button" href="/holdings">去添加会籍</a></section>`;
  const opportunities = `
    <section><div class="hero"><div><h2>匹配与挑战机会</h2><p>所有 STATUS_MATCH 机会放在同一列表，不再分人为类别。</p></div></div>
      <div class="grid three">${payload.opportunities.map(opportunityCard).join("") || '<div class="empty">当前没有可展示的匹配机会。</div>'}</div>
    </section>`;
  app.innerHTML = hero(
    "PERSONALIZED PATHS",
    "从你的会籍出发，找最近路径",
    "每个会籍只出现一次，只保留离当前会籍最近的到达路径。地区不会过滤机会。",
    '<a class="button secondary" href="/holdings">调整我的会籍</a>',
  ) + graph + opportunities;
  const graphViewport = document.querySelector(".membership-graph");
  const firstRoot = graphViewport?.querySelector(".membership-node.is-root");
  if (graphViewport && firstRoot) {
    graphViewport.scrollLeft = Math.max(
      0,
      firstRoot.offsetLeft + firstRoot.offsetWidth / 2 - graphViewport.clientWidth / 2,
    );
  }
}

function briefCard(item) {
  return `<article class="card brief-card">
    <div class="badges">${badge(item.opportunity_kind === "STATUS_MATCH" ? "匹配/挑战" : "其他机会", item.opportunity_kind === "OTHER" ? "neutral" : "")}${item.reachable ? badge("当前可达") : ""}</div>
    <h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.summary)}</p>
    <p class="muted">${escapeHtml(item.program)}${item.target_status ? ` · ${escapeHtml(item.target_status)}` : ""} · 更新于 ${dateText(item.updated_at)}</p>
    ${item.eligibility ? `<p><strong>资格：</strong>${escapeHtml(item.eligibility)}</p>` : ""}
    ${item.challenge_requirements ? `<p><strong>挑战要求：</strong>${escapeHtml(item.challenge_requirements)}</p>` : ""}
    ${item.deadline ? `<p><strong>截止：</strong>${escapeHtml(item.deadline)}</p>` : ""}
    ${item.price_summaries.length ? `<ul>${item.price_summaries.map((price) => `<li>${escapeHtml(price)}</li>`).join("")}</ul>` : ""}
    <div class="badges">${item.china_advisories.map((value) => badge(advisoryText(value), value === "EXPLICITLY_EXCLUDED" ? "warn" : "neutral")).join("")}</div>
    ${item.key_points.length ? `<ul>${item.key_points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ul>` : ""}
    <a class="button secondary" href="/opportunities/${item.opportunity_id}">查看详情</a>
  </article>`;
}

async function briefsPage() {
  app.innerHTML = hero(
    "ALL BRIEFS",
    "机会简报",
    "这里展示现有官方和普通文章的全部简报，包括 OTHER；类型只影响个性化匹配图，不影响简报生成与展示。",
  ) + `<section class="card"><form id="brief-search" class="toolbar"><label>搜索<input id="brief-query" placeholder="项目、等级或关键词"></label><label><span>范围</span><span><input id="reachable-only" type="checkbox" style="width:auto;min-height:auto"> 仅当前可达</span></label><button>筛选</button></form></section><section id="brief-list" class="grid two" style="margin-top:1rem"></section>`;
  const load = async () => {
    const q = document.querySelector("#brief-query").value;
    const only = document.querySelector("#reachable-only").checked;
    const payload = await api(`/v1/briefs?q=${encodeURIComponent(q)}&reachable_only=${only}`);
    document.querySelector("#brief-list").innerHTML = payload.items.map(briefCard).join("") || '<div class="empty"><h2>没有匹配的简报</h2><p>清空搜索条件后再试。</p></div>';
  };
  document.querySelector("#brief-search").addEventListener("submit", (event) => { event.preventDefault(); load().catch(showError); });
  await load();
}

const advisoryText = (value) => ({
  EXPLICITLY_INCLUDED: "中国地区明确包含",
  EXPLICITLY_EXCLUDED: "中国地区可能不适用；仅提醒，不阻止查看或申请",
  NOT_EXPLICIT: "规则未明确中国地区；仅提醒，不阻止查看或申请",
}[value] || value);

function routeCard(route) {
  const prices = route.prices.length ? `<div class="price-list">${route.prices.map((price) => `<div class="price"><span>${escapeHtml(price.target_tier || "通用")}</span><strong>${price.amount == null ? escapeHtml(price.availability) : `${escapeHtml(price.currency)} ${escapeHtml(price.amount)}`}</strong><small>${escapeHtml(price.raw_text)}</small></div>`).join("")}</div>` : `<p class="muted">费用未结构化；请参考原始费用文本与证据。</p>`;
  return `<article class="card route-card"><div class="badges">${badge(route.scope)}${route.conflict ? badge("有冲突", "warn") : ""}</div><h3>${escapeHtml(route.eligibility || "资格要求未明确")}</h3><p class="notice">${escapeHtml(advisoryText(route.china_advisory))}</p>${prices}${route.cost ? `<p>原始费用：${escapeHtml(route.cost)}</p>` : ""}${route.action_link ? `<a class="button" href="${escapeHtml(route.action_link)}" target="_blank" rel="noopener">前往申请入口</a>` : ""}</article>`;
}

function factsBlock(facts) {
  const labels = { eligibility: "资格", challenge_requirements: "挑战要求", region: "地区", application_start: "申请开始", deadline: "截止时间", cost: "费用原文", status_validity: "会籍有效期", action_link: "入口", caveats: "限制与注意事项" };
  return `<dl class="facts">${Object.entries(labels).map(([key, label]) => `<div class="fact"><dt>${label}</dt><dd>${escapeHtml(facts[key]?.value || "未明确")}</dd></div>`).join("")}</dl>`;
}

async function opportunityPage() {
  const id = document.body.dataset.opportunityId;
  const detail = await api(`/v1/match-opportunities/${id}`);
  app.innerHTML = hero(
    detail.opportunity_kind === "STATUS_MATCH" ? "STATUS MATCH" : "OTHER OPPORTUNITY",
    `${detail.program}${detail.target_status ? ` · ${detail.target_status}` : ""}`,
    detail.summary,
    '<a class="button secondary" href="javascript:history.back()">返回</a>',
  ) + `
    <section class="grid"><div class="card"><div class="badges">${badge(detail.source)}${badge(detail.lifecycle_status, "neutral")}</div>${detail.path ? `<p><strong>匹配路径：</strong>${escapeHtml(detail.path.join(" → "))}</p>` : '<p class="muted">此机会暂未映射到当前持有会籍路径。</p>'}<h2>结构化事实</h2>${factsBlock(detail.facts)}</div>
    <div><h2>申请路线与价格</h2><div class="grid two">${detail.routes.map(routeCard).join("") || '<div class="empty">当前没有可验证的申请路线。</div>'}</div></div>
    ${detail.brief ? `<article class="card brief-card"><h2>${escapeHtml(detail.brief.title)}</h2><p>${escapeHtml(detail.brief.summary)}</p>${detail.brief.key_points?.length ? `<ul>${detail.brief.key_points.map((point) => `<li>${escapeHtml(point.text)}</li>`).join("")}</ul>` : ""}</article>` : ""}
    ${detail.source_links.length ? `<section class="card"><h2>证据与原文</h2><div class="source-list">${detail.source_links.map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(link)}</a>`).join("")}</div></section>` : ""}</section>`;
}

function showError(error) {
  app.innerHTML = `<section class="empty error"><h2>暂时无法读取</h2><p>${escapeHtml(error.message || error)}</p></section>`;
}

const pages = { holdings: holdingsPage, matches: matchesPage, briefs: briefsPage, opportunity: opportunityPage };
Promise.resolve(pages[document.body.dataset.page]?.()).catch(showError);
