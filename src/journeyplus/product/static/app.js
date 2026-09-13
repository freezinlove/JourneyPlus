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

const hero = (eyebrow, title, copy = "", action = "") => `
  <section class="hero">
    <div><p class="eyebrow">${escapeHtml(eyebrow)}</p><h1>${escapeHtml(title)}</h1>${copy ? `<p>${escapeHtml(copy)}</p>` : ""}</div>
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
const GRAPH_CARD_HEIGHT = 96;
const GRAPH_HORIZONTAL_STEP = 248;
const GRAPH_LEVEL_GAP = 58;
const GRAPH_PADDING = 32;

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
  const origins = rootNodeIds.map((nodeId) => records.get(nodeId)).filter(Boolean);
  if (origins.length) {
    const combined = {...origins[0], nodeId: 'my-memberships',
      node: {...origins[0].node, program: '我的会籍',
        tier: origins.map(root => `${root.node.program} ${root.node.tier}`).join(' ＋ '),
        alliance: null, categories: []},
      children: origins.flatMap(root => root.children)};
    return {roots: [combined], records};
  }
  return {roots: [], records};
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
  const isRoot = rootIds.has(node.nodeId);
  const kind = node.node.alliance
    ? { icon: "✈", label: node.node.alliance }
    : node.node.categories.includes("HOTEL")
      ? { icon: "◆", label: "酒店会籍" }
      : null;
  const kindLine = kind
    ? `<div class="membership-node__topline"><span class="membership-kind"><span aria-hidden="true">${kind.icon}</span>${escapeHtml(kind.label)}</span></div>`
    : "";
  return `<article
      id="${node.id}"
      class="membership-node${isRoot ? " is-root" : ""}"
      style="left:${node.x}px;top:${node.y}px"
      role="treeitem"
      aria-label="${escapeHtml(`${node.node.program} ${node.node.tier}${node.node.alliance ? `，${node.node.alliance}` : ""}`)}"
    >
      ${kindLine}
      <h3>${escapeHtml(node.node.program)}</h3>
      <strong class="membership-tier" title="${escapeHtml(node.node.tier)}">${escapeHtml(node.node.tier)}</strong>
    </article>`;
}

function graphFeeLabel(item, feeByEdge) {
  const labels = feeByEdge.get(`${item.edge.source_node_id}\u0000${item.edge.target_node_id}`) || [];
  if (!labels.length) return "";
  const label = labels.join(" / ");
  const left = item.target.centerX;
  const top = item.source.y + GRAPH_CARD_HEIGHT + (GRAPH_LEVEL_GAP - 26) / 2;
  return `<span class="graph-fee-label" style="left:${left}px;top:${top}px" title="${escapeHtml(labels.length > 1 ? `匹配是否付费：${label}` : `匹配是否付费：${label}`)}">${escapeHtml(label)}</span>`;
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
    return `<path class="graph-link" d="M ${sourceX} ${sourceY} C ${sourceX} ${bendY}, ${targetX} ${bendY}, ${targetX} ${targetY}"/>`;
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
      <div class="graph-legend" aria-label="图例"><span><i class="legend-dot root"></i>当前持有会籍</span><span><i class="legend-line"></i>最近路径</span><span><i class="legend-fee">USD</i>明确费用</span></div>
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

function briefDisplayTitle(item) {
  return String(item.title || `${item.program} 会籍匹配活动`).trim();
}

function lifecycleBadge(item) {
  const label = {EXPIRED: '已结束', STALE: '资料已过期', ARCHIVED: '已归档', UPCOMING: '尚未开始'}[item.lifecycle_status];
  return label ? `<strong class="lifecycle-notice" role="status">${label}</strong>` : '';
}

function briefFee(item) {
  return `<span class="fee-chip">${escapeHtml(item.fee?.label || "费用待确认")}</span>`;
}

function briefUpdatedAt(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "尚未生成";
}

function publicLinks(links, label) {
  return (links || []).map((link, index) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(label ? `${label}${links.length > 1 ? ` ${index + 1}` : ""}` : sourceLinkLabel(link))}</a>`).join(" · ");
}

function membershipNodeText(nodeId) {
  const [program, tier] = String(nodeId || "").split("::");
  return [titleCaseWords(program), titleCaseWords(tier)].filter(Boolean).join(" · ");
}

function briefPathText(path) {
  return path?.length
    ? path.map(membershipNodeText).join(" → ")
    : "与我的会籍暂无直接匹配路径";
}

function briefRow(item) {
  const title = briefDisplayTitle(item);
  return `<article class="brief-row">
    <h2><a href="/opportunities/${item.opportunity_id}">${escapeHtml(title)}</a></h2>
    <p class="brief-row__summary">${escapeHtml(item.summary)}</p>
    ${lifecycleBadge(item)} ${briefFee(item)}
    <p class="brief-row__path"><span class="brief-row__path-label">和我的关系</span><span class="brief-row__path-value">${escapeHtml(item.relationship?.text || briefPathText(item.path))}</span></p>
    <p class="brief-links">${publicLinks(item.action_links, "申请入口")}</p>
    <p class="brief-links">来源：${publicLinks(item.source_links) || "暂无来源链接"}</p>
    <time datetime="${escapeHtml(item.updated_at)}">简报更新于 ${escapeHtml(briefUpdatedAt(item.updated_at))}（北京时间）</time>
  </article>`;
}

async function briefsPage() {
  app.innerHTML = hero(
    "ALL BRIEFS",
    "机会简报",
  ) + `<label class="archive-toggle"><input type="checkbox" id="include-archived"> 显示已结束和已归档的简报</label><section id="brief-list" class="brief-list"></section>`;
  document.querySelector('#include-archived').checked = new URLSearchParams(location.search).get('include_archived') === 'true';
  document.querySelector('#include-archived').onchange = event => { location.href = event.target.checked ? '/briefs?include_archived=true' : '/briefs'; };
  const payload = await api('/v1/briefs' + (document.querySelector('#include-archived').checked ? '?include_archived=true' : ''));
  document.querySelector("#brief-list").innerHTML = payload.items.map(briefRow).join("") || '<div class="empty"><h2>暂无简报</h2><p>当前没有可展示的简报。</p></div>';
}

const uniqueValues = (values) => [...new Set(values.filter(Boolean))];

function titleCaseWords(value) {
  return String(value || "").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}


function compactTargetTier(value, targetStatus) {
  const raw = String(value || "通用").trim();
  const options = String(targetStatus || "")
    .split(/[,/]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return options.find((item) => raw.toLocaleLowerCase().endsWith(item.toLocaleLowerCase())) || raw;
}

function mappingCell(items) {
  if (!items.length) return '<span class="table-empty">—</span>';
  return items.map((item) => {
    const tiers = (item.source_tiers || []).map(escapeHtml).join("<br>");
    const label = item.availability === "UNAVAILABLE" ? `${tiers ? `${tiers}<br>` : ""}不可用` : tiers || "未说明原等级";
    const availability = { CONDITIONAL: "有条件／可选", UNKNOWN: "可用性待确认" }[item.availability];
    const notes = uniqueValues([item.conditions, item.conflict_note]);
    return `<div>${label}${availability ? `<small>${availability}</small>` : ""}${item.conflict ? "<small>信息有冲突</small>" : ""}${notes.length ? `<details class="table-notes"><summary>条件说明</summary>${notes.map(note => `<p>${escapeHtml(note)}</p>`).join("")}</details>` : ""}</div>`;
  }).join("<hr>");
}

function mappingTable(detail) {
  const mappings = detail.facts?.status_mappings || [];
  if (!mappings.length) return '<p class="muted">原文没有可展示的会籍映射表。</p>';
  const targetTiers = uniqueValues(mappings.map((item) => compactTargetTier(item.target_tier, detail.target_status)));
  const rows = new Map();
  mappings.forEach((item) => {
    const program = item.source_program || "其他会籍";
    const targetTier = compactTargetTier(item.target_tier, detail.target_status);
    if (!rows.has(program)) rows.set(program, new Map());
    if (!rows.get(program).has(targetTier)) rows.get(program).set(targetTier, []);
    rows.get(program).get(targetTier).push(item);
  });
  return `<div class="detail-table-wrap"><table class="detail-table mapping-table">
    <thead><tr><th scope="col">现有会籍项目</th>${targetTiers.map((tier) => `<th scope="col">匹配至 ${escapeHtml(tier)}</th>`).join("")}</tr></thead>
    <tbody>${[...rows.entries()].map(([program, cells]) => `<tr><th scope="row">${escapeHtml(program)}</th>${targetTiers.map((tier) => `<td>${mappingCell(cells.get(tier) || [])}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

function routeLabel(route) {
  return route.scope || "默认申请方式";
}

function priceText(price) {
  if (!price) return '<span class="table-empty">—</span>';
  if (price.amount != null) {
    const amount = String(price.amount).replace(/\.0+$/, "");
    return `<strong>${escapeHtml(`${price.currency || ""} ${amount}`.trim())}</strong>${price.availability === "CONDITIONAL" ? `<small>有条件／可选费用${price.raw_text ? `：${escapeHtml(price.raw_text)}` : ""}</small>` : price.availability === "UNKNOWN" ? "<small>可用性待确认</small>" : ""}`;
  }
  return escapeHtml({ UNAVAILABLE: "不可用", CONDITIONAL: "有条件", UNKNOWN: "未公布" }[price.availability] || price.raw_text || "未公布");
}

function priceTable(detail) {
  const routes = detail.routes || [];
  const targetTiers = uniqueValues(routes.flatMap((route) => route.prices || []).map((price) => price.target_tier || "通用"));
  if (!routes.length || !targetTiers.length) return '<p class="muted">原文没有可展示的匹配费用表。</p>';
  return `<div class="detail-table-wrap"><table class="detail-table price-table">
    <thead><tr><th scope="col">申请方式</th>${targetTiers.map((tier) => `<th scope="col">${escapeHtml(tier)}</th>`).join("")}</tr></thead>
    <tbody>${routes.map((route) => `<tr><th scope="row">${escapeHtml(routeLabel(route))}${uniqueValues([route.region, route.eligibility, route.cost, route.conflict_note]).filter(note => note !== routeLabel(route)).map(note => `<small>${escapeHtml(note)}</small>`).join("")}${route.conflict ? "<small>信息有冲突</small>" : ""}</th>${targetTiers.map((tier) => `<td>${(route.prices || []).filter((price) => (price.target_tier || "通用") === tier).map(priceText).join("<br>") || "—"}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}



function sourceLinkLabel(link) {
  try {
    const url = new URL(link);
    if (/\/faq\/?$/i.test(url.pathname)) return "官方 FAQ";
    if (/\/terms\/?$/i.test(url.pathname)) return "官方条款";
    if (url.pathname === "/" || !url.pathname) return "官方活动页";
    return url.hostname + url.pathname;
  } catch (_error) {
    return link;
  }
}


async function opportunityPage() {
  const id = document.body.dataset.opportunityId;
  const detail = await api(`/v1/match-opportunities/${id}`);
  const title = briefDisplayTitle({ ...detail, title: detail.brief?.title || `${detail.program}${detail.target_status ? ` · ${detail.target_status}` : ""}` });
  const summary = detail.brief?.summary || detail.summary;
  const sourceLinks = detail.source_links || [];
  const conditions = uniqueValues([detail.facts?.eligibility?.value, detail.facts?.status_validity?.value, detail.facts?.caveats?.value, detail.facts?.challenge_requirements?.value]);
  app.innerHTML = `<article class="brief-detail">
    <a class="detail-back" href="/briefs">← 返回机会简报</a>
    <header class="brief-detail__header"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(summary)}</p>${lifecycleBadge(detail)} ${briefFee(detail)}<time>简报更新于 ${escapeHtml(briefUpdatedAt(detail.brief_updated_at))}（北京时间）</time></header>
    <section class="detail-section"><h2>和我的关系</h2><p>${escapeHtml(detail.relationship?.text || "暂未计算")}</p>${detail.relationship?.path_labels?.length ? `<p class="detail-path">${escapeHtml(detail.relationship.path_labels.join(" → "))}</p>` : ""}</section>
    <section class="detail-section official-entry"><h2>申请入口</h2>${publicLinks(detail.action_links, "前往申请页面") || '<p class="muted">暂无申请入口。</p>'}</section>
    <section class="detail-section"><h2>完整映射表</h2>${mappingTable(detail)}${conditions.length ? `<details class="table-notes"><summary>活动适用条件</summary>${conditions.map(text => `<p>${escapeHtml(text)}</p>`).join("")}</details>` : ""}</section>
    <section class="detail-section"><h2>价格表</h2>${priceTable(detail)}${(detail.fee?.notes || []).map(note => `<p class="muted">${escapeHtml(note)}</p>`).join("")}</section>
    <section class="detail-section"><h2>来源链接</h2>${sourceLinks.length ? `<div class="detail-sources">${sourceLinks.map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener"><span>${escapeHtml(sourceLinkLabel(link))}</span><small>${escapeHtml(link)}</small></a>`).join("")}</div>` : '<p class="muted">暂无来源链接。</p>'}</section>
  </article>`;
}

function showError(error) {
  app.innerHTML = `<section class="empty error"><h2>暂时无法读取</h2><p>${escapeHtml(error.message || error)}</p></section>`;
}

const pages = { holdings: holdingsPage, matches: matchesPage, briefs: briefsPage, opportunity: opportunityPage };
Promise.resolve(pages[document.body.dataset.page]?.()).catch(showError);
