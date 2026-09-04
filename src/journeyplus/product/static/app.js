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

const agentCommandLabels = {
  CONFIRM: "确认",
  REJECT: "不接受",
  CANCEL_WAIT: "取消持续跟进",
  FINISH_WAIT: "结束持续跟进",
};

function agentRouteCard(route, label) {
  if (!route) return "";
  const evidence = uniqueValues((route.steps || []).flatMap((step) => step.evidence_links || []));
  const costs = uniqueValues((route.steps || []).flatMap((step) => step.costs || []));
  const challenges = uniqueValues((route.steps || []).map((step) => step.challenge_requirements));
  const actions = uniqueValues((route.steps || []).flatMap((step) => step.action_links || []));
  return `<article class="agent-route card">
    <div class="badges">${badge(label)}${route.target_alliance ? badge(route.target_alliance, "neutral") : ""}</div>
    <h3>${escapeHtml(route.target_program)} · ${escapeHtml(route.target_tier)}</h3>
    <p class="agent-route__path">${escapeHtml((route.node_path || []).map(membershipNodeText).join(" → "))}</p>
    <dl class="agent-facts">
      <div><dt>步骤</dt><dd>${escapeHtml(String((route.steps || []).length))}</dd></div>
      <div><dt>费用资料</dt><dd>${escapeHtml(costs.join("；") || "未明确")}</dd></div>
      <div><dt>挑战资料</dt><dd>${escapeHtml(challenges.join("；") || "未明确")}</dd></div>
    </dl>
    ${(route.limitations || []).length ? `<ul class="agent-notes">${route.limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    <div class="agent-links">
      ${actions.map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">申请入口 ↗</a>`).join("")}
      ${evidence.map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">事实原文 ↗</a>`).join("")}
    </div>
  </article>`;
}

function agentExperience(observation) {
  const counts = observation.outcome_counts || {};
  return `<article class="agent-experience card">
    <div class="badges">${badge(`经验信号：${observation.signal}`, observation.signal === "较弱" ? "warn" : "neutral")}</div>
    <p>可比自报 ${escapeHtml(observation.comparable_report_count)} 条：直接匹配 ${escapeHtml(counts.MATCH || 0)}、转为挑战 ${escapeHtml(counts.CHALLENGE || 0)}、拒绝 ${escapeHtml(counts.DENY || 0)}。</p>
    ${(observation.practical_notes || []).length ? `<ul>${observation.practical_notes.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    <p class="muted">${escapeHtml(observation.limitation)}</p>
    <div class="agent-links">${(observation.source_urls || []).map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">StatusMatcher 页面 ↗</a>`).join("")}</div>
  </article>`;
}

function agentTargetText(interpreted) {
  const target = interpreted?.target;
  if (!target) return "";
  return [target.program, target.tier, target.alliance, target.relative_level === "HIGH" ? "偏好高等级" : ""].filter(Boolean).join(" · ");
}

function renderAgentResponse(response, title = "本次结果") {
  if (!response) return '<div class="empty"><h2>还没有策略结果</h2><p>写下你持有什么会籍、想去哪里，以及费用或挑战上的取舍。</p></div>';
  const alternatives = response.alternative_routes || [];
  const result = response.candidate_result;
  return `<section class="agent-response">
    <div class="agent-response__heading"><div><p class="eyebrow">${escapeHtml(title)}</p><h2>${escapeHtml(response.message)}</h2></div>${response.action ? badge(response.action, "neutral") : ""}</div>
    ${response.interpreted_request ? `<p class="muted">目标：${escapeHtml(agentTargetText(response.interpreted_request))}</p>` : ""}
    ${(response.risks || []).length ? `<section class="agent-risk"><h3>风险与注意点</h3><ul>${response.risks.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
    ${response.proposed_adjustment ? `<section class="agent-adjustment"><strong>建议只改一个条件：</strong> ${escapeHtml(response.proposed_adjustment.explanation)}</section>` : ""}
    ${response.primary_route ? `<div class="grid agent-routes">${agentRouteCard(response.primary_route, "首选")}${alternatives.map((route, index) => agentRouteCard(route, `备选 ${index + 1}`)).join("")}</div>` : ""}
    ${(response.experience || []).length ? `<section><h3>实际申请经验</h3><div class="grid agent-routes">${response.experience.map(agentExperience).join("")}</div></section>` : ""}
    ${result && !response.primary_route ? `<p class="muted">符合条件 ${result.matching_routes.length} 条 · 只差一个条件 ${result.nearby_routes.length} 条 · 关键信息未知 ${result.unknown_routes.length} 条</p>` : ""}
    <div class="agent-actions">${(response.allowed_commands || []).filter((command) => command !== "MESSAGE").map((command) => `<button type="button" data-agent-command="${escapeHtml(command)}">${escapeHtml(agentCommandLabels[command] || command)}</button>`).join("")}</div>
  </section>`;
}

function renderWaitGoal(goal) {
  if (!goal || goal.status !== "ACTIVE") return '<p class="muted">当前没有持续跟进目标。</p>';
  const target = goal.query?.target || {};
  const targetText = [target.program_key, target.tier_key, target.alliance, target.relative_tier === "HIGH" ? "偏好高等级" : ""].filter(Boolean).join(" · ");
  return `<div class="agent-wait card"><div><strong>${escapeHtml(targetText)}</strong><p class="muted">没有新候选时不会调用 Agent 或通知；首次命中才重新评估。</p></div><div class="agent-wait__actions"><button type="button" class="secondary" data-agent-command="FINISH_WAIT">结束跟进</button><button type="button" class="danger" data-agent-command="CANCEL_WAIT">取消跟进</button></div></div>`;
}

async function agentPage() {
  app.innerHTML = hero(
    "MEMBERSHIP STRATEGY AGENT",
    "把目标和取舍直接告诉我",
    "例如：我有汉莎金卡，想要天合联盟高卡，尽量免费；如果有必要可以先问我一个关键问题。",
  ) + `<section class="agent-layout">
    <div class="card agent-composer">
      <form id="agent-form" class="grid">
        <label for="agent-message">你的会籍、目标和取舍</label>
        <textarea id="agent-message" rows="6" maxlength="3000" placeholder="我有……，希望……，费用/挑战方面……" required></textarea>
        <button type="submit">交给 Agent</button>
        <p id="agent-form-message" class="muted" role="status"></p>
      </form>
      <section><h3>持续跟进</h3><div id="agent-wait"></div></section>
    </div>
    <div id="agent-result"></div>
  </section>`;
  const form = document.querySelector("#agent-form");
  const input = document.querySelector("#agent-message");
  const message = document.querySelector("#agent-form-message");
  const resultNode = document.querySelector("#agent-result");
  const waitNode = document.querySelector("#agent-wait");
  let current = null;

  const bindCommands = () => document.querySelectorAll("[data-agent-command]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    message.textContent = "正在执行已确认的操作…";
    try {
      current = await api("/v1/agent/turn", {
        method: "POST",
        body: JSON.stringify({
          interaction_id: current?.interaction_id || null,
          command: button.dataset.agentCommand,
        }),
      });
      resultNode.innerHTML = renderAgentResponse(current);
      const state = await api("/v1/agent/state");
      waitNode.innerHTML = renderWaitGoal(state.wait_goal);
      message.textContent = "";
      bindCommands();
    } catch (error) { message.textContent = error.message; button.disabled = false; }
  }));

  const state = await api("/v1/agent/state");
  current = state.interaction;
  form.querySelector("button").disabled = !state.available;
  if (!state.available) message.textContent = "服务端尚未配置模型，其他确定性功能仍可正常使用。";
  resultNode.innerHTML = state.pending_result
    ? renderAgentResponse(state.pending_result, "持续跟进首次命中") + renderAgentResponse(current, "最近一次交互")
    : renderAgentResponse(current);
  waitNode.innerHTML = renderWaitGoal(state.wait_goal);
  bindCommands();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.textContent = "Agent 正在理解目标并查询当前数据…";
    form.querySelector("button").disabled = true;
    try {
      const resumable = current?.allowed_commands?.includes("MESSAGE");
      current = await api("/v1/agent/turn", {
        method: "POST",
        body: JSON.stringify({
          interaction_id: resumable ? current.interaction_id : null,
          command: "MESSAGE",
          message: input.value,
        }),
      });
      resultNode.innerHTML = renderAgentResponse(current);
      input.value = "";
      message.textContent = "";
      bindCommands();
    } catch (error) { message.textContent = error.message; }
    finally { form.querySelector("button").disabled = !state.available; }
  });
}

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
      <strong class="membership-tier">${escapeHtml(node.node.tier)}</strong>
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
  const original = String(item.title || "").trim();
  const isManagedStatusMatch = item.opportunity_kind === "STATUS_MATCH" && item.source !== "ORDINARY_ARTICLE";
  if (!isManagedStatusMatch) return original;
  const marker = "会籍匹配";
  const markerIndex = original.indexOf(marker);
  return markerIndex >= 0 ? original.slice(0, markerIndex + marker.length) : `${item.program}${marker}`;
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
  return `<a class="brief-row" href="/opportunities/${item.opportunity_id}" aria-label="查看${escapeHtml(title)}">
    <article>
      <h2>${escapeHtml(title)}</h2>
      <p class="brief-row__summary">${escapeHtml(item.summary)}</p>
      <p class="brief-row__path"><span class="brief-row__path-label">可尝试</span><span class="brief-row__path-value">${escapeHtml(briefPathText(item.path))}</span></p>
      <time datetime="${escapeHtml(item.updated_at)}">更新于 ${dateText(item.updated_at)}</time>
    </article>
  </a>`;
}

async function briefsPage() {
  app.innerHTML = hero(
    "ALL BRIEFS",
    "机会简报",
  ) + `<section id="brief-list" class="brief-list"></section>`;
  const payload = await api("/v1/briefs");
  document.querySelector("#brief-list").innerHTML = payload.items.map(briefRow).join("") || '<div class="empty"><h2>暂无简报</h2><p>当前没有可展示的简报。</p></div>';
}

const uniqueValues = (values) => [...new Set(values.filter(Boolean))];

function titleCaseWords(value) {
  return String(value || "").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function membershipPath(path) {
  if (!path?.length) return '<p class="muted">当前持有会籍暂未找到通往此机会的匹配路径。</p>';
  return `<div class="detail-path">${path.map((nodeId, index) => {
    const [program, tier] = nodeId.split("::");
    const arrow = index ? '<span class="detail-path__arrow" aria-hidden="true">→</span>' : "";
    return `${arrow}<span class="detail-path__step"><strong>${escapeHtml(titleCaseWords(program))}</strong>${tier ? `<span>${escapeHtml(titleCaseWords(tier))}</span>` : ""}</span>`;
  }).join("")}</div>`;
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
  const usable = items.filter((item) => item.availability !== "UNAVAILABLE");
  if (!usable.length) return '<span class="table-empty">—</span>';
  const tiers = uniqueValues(usable.flatMap((item) => item.source_tiers || []));
  const notes = [];
  if (usable.some((item) => item.availability === "CONDITIONAL")) notes.push("可选／有条件");
  if (usable.some((item) => item.conflict)) notes.push("信息有冲突");
  return `${tiers.length ? tiers.map((tier) => escapeHtml(tier)).join("<br>") : "符合条件"}${notes.length ? `<small>${escapeHtml(notes.join(" · "))}</small>` : ""}`;
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
  const scope = route.scope || "默认申请方式";
  if (/travel rewards|credit card|信用卡/i.test(scope)) return "旅行奖励信用卡";
  if (/alaska airlines/i.test(scope)) return "Alaska Airlines 会籍";
  if (/hotel/i.test(scope)) return "酒店会籍";
  if (/airline/i.test(scope)) return "航空会籍";
  return scope;
}

function priceText(price) {
  if (!price) return '<span class="table-empty">—</span>';
  if (price.amount != null) {
    const amount = String(price.amount).replace(/\.0+$/, "");
    return `<strong>${escapeHtml(`${price.currency || ""} ${amount}`.trim())}</strong>`;
  }
  return escapeHtml({ UNAVAILABLE: "不可用", CONDITIONAL: "有条件", UNKNOWN: "未公布" }[price.availability] || price.raw_text || "未公布");
}

function priceTable(detail) {
  const routes = detail.routes || [];
  const targetTiers = uniqueValues(routes.flatMap((route) => route.prices || []).map((price) => price.target_tier || "通用"));
  if (!routes.length || !targetTiers.length) return '<p class="muted">原文没有可展示的匹配费用表。</p>';
  return `<div class="detail-table-wrap"><table class="detail-table price-table">
    <thead><tr><th scope="col">申请方式</th>${targetTiers.map((tier) => `<th scope="col">${escapeHtml(tier)}</th>`).join("")}</tr></thead>
    <tbody>${routes.map((route) => `<tr><th scope="row">${escapeHtml(routeLabel(route))}${route.conflict ? "<small>信息有冲突</small>" : ""}</th>${targetTiers.map((tier) => `<td>${priceText((route.prices || []).find((price) => (price.target_tier || "通用") === tier))}</td>`).join("")}</tr>`).join("")}</tbody>
  </table></div>`;
}

function officialActionLink(detail) {
  return detail.facts?.action_link?.value || detail.routes?.map((route) => route.action_link).find(Boolean) || null;
}

function detailNotices(detail) {
  const briefNotices = (detail.brief?.caveats || []).map((item) => item.text);
  const fallbackNotices = briefNotices.length
    ? []
    : String(detail.facts?.caveats?.value || "").split("；").map((item) => item.trim());
  const lifecycleNotice = detail.lifecycle_status === "UNKNOWN" && !detail.facts?.deadline?.value
    ? ["官网未提供明确截止时间，提交申请前请确认活动仍在开放。"]
    : [];
  return uniqueValues([...briefNotices, ...fallbackNotices, ...lifecycleNotice]);
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

function sameLink(left, right) {
  return String(left || "").replace(/\/$/, "") === String(right || "").replace(/\/$/, "");
}

async function opportunityPage() {
  const id = document.body.dataset.opportunityId;
  const detail = await api(`/v1/match-opportunities/${id}`);
  const title = briefDisplayTitle({ ...detail, title: detail.brief?.title || `${detail.program}${detail.target_status ? ` · ${detail.target_status}` : ""}` });
  const summary = detail.brief?.summary || detail.summary;
  const notices = detailNotices(detail);
  const actionLink = officialActionLink(detail);
  const sourceLinks = (detail.source_links || []).filter((link) => !sameLink(link, actionLink));
  app.innerHTML = `<article class="brief-detail">
    <a class="detail-back" href="/briefs">← 返回机会简报</a>
    <header class="brief-detail__header"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(summary)}</p></header>
    <section class="detail-section"><h2>跟我的会籍联系</h2>${membershipPath(detail.path)}</section>
    <section class="detail-section"><h2>注意事项和提醒</h2>${notices.length ? `<ul class="detail-notices">${notices.map((notice) => `<li>${escapeHtml(notice)}</li>`).join("")}</ul>` : '<p class="muted">暂无额外提醒。</p>'}</section>
    <section class="detail-section official-entry"><h2>官方匹配入口</h2>${actionLink ? `<a class="official-entry__link" href="${escapeHtml(actionLink)}" target="_blank" rel="noopener">前往官方申请页面 <span aria-hidden="true">↗</span></a>` : '<p class="muted">当前没有可验证的官方申请入口。</p>'}</section>
    <section class="detail-section"><h2>会籍映射表格</h2>${mappingTable(detail)}</section>
    <section class="detail-section"><h2>匹配费用表格</h2>${priceTable(detail)}</section>
    <section class="detail-section"><h2>原文链接</h2>${sourceLinks.length ? `<div class="detail-sources">${sourceLinks.map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener"><span>${escapeHtml(sourceLinkLabel(link))}</span><small>${escapeHtml(link)}</small></a>`).join("")}</div>` : '<p class="muted">暂无独立原文链接。</p>'}</section>
  </article>`;
}

function showError(error) {
  app.innerHTML = `<section class="empty error"><h2>暂时无法读取</h2><p>${escapeHtml(error.message || error)}</p></section>`;
}

const pages = { agent: agentPage, holdings: holdingsPage, matches: matchesPage, briefs: briefsPage, opportunity: opportunityPage };
Promise.resolve(pages[document.body.dataset.page]?.()).catch(showError);
