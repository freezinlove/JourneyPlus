const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const uniqueValues = (values) => [...new Set(values.filter(Boolean))];

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
  const urls = uniqueValues((links || []).map(link => {
    try { const url = new URL(link); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
    catch { return null; }
  }));
  return urls.map((link, index) => `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(label ? `${label}${urls.length > 1 ? ` ${index + 1}` : ""}` : sourceLinkLabel(link))}</a>`).join(" · ");
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
  return escapeHtml({ UNAVAILABLE: "不可用", CONDITIONAL: "有条件", UNKNOWN: "费用待核实" }[price.availability] || price.raw_text || "费用待核实");
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


function renderBrief(detail) {
  if (!detail.brief) return '<p class="empty">此版本尚无已生成简报。</p>';
  const title = briefDisplayTitle({ ...detail, title: detail.brief.title });
  const sourceLinks = detail.source_links || [];
  return `<article class="brief-detail">
    <div class="brief-detail__header"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(detail.brief.summary)}</p>${lifecycleBadge(detail)} ${briefFee(detail)}<time>简报更新于 ${escapeHtml(briefUpdatedAt(detail.brief_updated_at))}（北京时间）</time></div>
    <section class="detail-section"><h2>和我的关系</h2><p>${escapeHtml(detail.relationship?.text || "暂未计算")}</p></section>
    <section class="detail-section official-entry"><h2>申请入口</h2>${publicLinks(detail.action_links, "前往申请页面") || '<p class="muted">暂无申请入口。</p>'}</section>
    <section class="detail-section"><h2>会籍匹配表</h2>${mappingTable(detail)}</section>
    <section class="detail-section"><h2>价格表</h2>${priceTable(detail)}</section>
    <section class="detail-section"><h2>原文链接</h2>${sourceLinks.length ? `<div class="detail-sources">${sourceLinks.map((link) => publicLinks([link])).join("")}</div>` : '<p class="muted">暂无来源链接。</p>'}</section>
  </article>`;
}

export {mappingTable, renderBrief, briefDisplayTitle, lifecycleBadge, briefFee, briefUpdatedAt, publicLinks};
