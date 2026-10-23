/* One market page: logic graph, daily review (复盘), backtest (回测), paper trading (虚拟交易), data. */
(function () {
  const { t, esc, num, pct } = Neva;
  const M = window.MARKET;
  const API = `/${M.key}/api`;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const C = { s1: "var(--series-1)", s2: "var(--series-2)", s3: "var(--series-3)", muted: "var(--viz-muted)" };
  const VERDICT = {
    holds: [t("成立", "Holds"), "ok"], weak: [t("偏弱", "Weak"), "warn"], fails: [t("不成立", "Fails"), "no"],
    insufficient: [t("样本不足", "Too few"), "na"], na: [t("不适用", "n/a"), "na"],
  };
  const selfPill = r => r.kind === "self" ? `<span class="pill">${t("价格自身", "own prices")}</span>` : "";
  const TRANSFORM = {
    pct: t("{w} 日涨跌幅", "{w}-day % change"), diff: t("{w} 日变化", "{w}-day change"), level: t("相对过去 {w} 天的水平", "level vs the last {w} days"),
    sum: t("{w} 日累计", "{w}-day total"), anomaly: t("{w} 日累计相对往年同期", "{w}-day total vs the same days in past years"),
    count_below: t("{w} 日内低于 {x} 的天数", "days below {x} in {w} days"), count_above: t("{w} 日内高于 {x} 的天数", "days above {x} in {w} days"),
  };
  const TABS = [
    ["graph", t("逻辑图谱", "Logic graph")], ["review", t("复盘", "Review")], ["backtest", t("回测", "Backtest")],
    ["paper", t("虚拟交易", "Paper trading")], ["data", t("数据", "Data")],
  ];
  let meta = null, summary = null;
  const name = o => t(o.name, o.nameEn ?? o.name_en);
  const seriesOf = id => meta.series.find(s => s.id === id) || { id, name: id, nameEn: id, unit: "" };
  const instOf = id => meta.instruments.find(i => i.id === id);
  const badge = v => { const [label, cls] = VERDICT[v] || VERDICT.insufficient; return `<span class="vbadge ${cls}">${label}</span>`; };
  const signed = (v, d = 2) => v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(d);
  const move = (v, d = 2) => `<span class="${Neva.dir(v)}">${pct(v, d)}</span>`;
  const viewText = v => v === null || v === undefined || Math.abs(v) < 0.15 ? `<span class="view flat">${t("中性", "Neutral")}</span>`
    : `<span class="view ${v > 0 ? "up" : "down"}">${v > 0 ? t("看多", "Bullish") : t("看空", "Bearish")} ${Math.abs(v).toFixed(2)}</span>`;
  const describe = r => {
    const s = seriesOf(r.driver), tr = (TRANSFORM[r.transform] || r.transform).replace("{w}", r.window).replace("{x}", r.threshold);
    const months = r.months?.length ? t(`，只在 ${r.months.join("、")} 月`, `, only in months ${r.months.join(", ")}`) : "";
    return t(`${name(s)}的${tr}，滞后 ${r.lag} 天，对应${name(instOf(r.target))}之后 ${r.horizon} 个交易日的涨跌；${r.sign > 0 ? "同向" : "反向"}${months}`,
      `${tr} of ${name(s)}, lagged ${r.lag} day(s), against ${name(instOf(r.target))} over the next ${r.horizon} trading days; ${r.sign > 0 ? "same direction" : "opposite direction"}${months}`);
  };
  const fail = (host, e) => { host.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`; };

  // ---- shell ------------------------------------------------------------------------------------------
  $("#mkKicker").textContent = t("期货 · 市场", "Futures · market");
  $("#mkName").textContent = t(M.name, M.nameEn);
  $("#mkTagline").textContent = t(M.tagline, M.taglineEn);
  document.title = `${t(M.name, M.nameEn)} · nevabase`;
  $("#mkTabs").innerHTML = TABS.map(([k, label]) => `<a href="#${k}" role="tab" data-k="${k}">${label}</a>`).join("");

  const loaded = {};
  function route() {
    const k = (location.hash.slice(1).split("?")[0]) || "graph";
    const tab = TABS.some(([x]) => x === k) ? k : "graph";
    $$("#mkTabs a").forEach(a => a.classList.toggle("active", a.dataset.k === tab));
    $$("section[data-tab]").forEach(s => s.hidden = s.dataset.tab !== tab);
    if (!loaded[tab] && meta) { loaded[tab] = true; ({ graph, review, backtest, paper, data })[tab]($(`section[data-tab="${tab}"]`)); }
  }
  addEventListener("hashchange", route);

  function header() {
    const p = meta.pack;
    $("#mkMeta").innerHTML = `
      <div><span class="k">${t("数据截至", "Data through")}</span><strong>${esc(meta.lastDate || "—")}</strong></div>
      <div><span class="k">${t("历史", "History")}</span><strong>${esc(meta.firstDate?.slice(0, 4) || "—")} –</strong></div>
      <div><span class="k">${t("逻辑包", "Logic pack")}</span><strong title="${esc(p?.version || "")}">${p ? esc(p.version.slice(0, 8)) : "—"}</strong></div>`;
    $("#mkStrip").innerHTML = (summary?.instruments || []).map(i => `
      <a class="mk-inst" href="#data?s=${esc(i.id)}">
        <div class="top"><span class="nm">${esc(name(i))}</span><span class="code mono">${esc(instOf(i.id)?.contract || i.id)}</span></div>
        <div class="px"><strong>${num(i.close, i.close >= 1000 ? 0 : 2)}</strong><span class="unit">${esc(i.unit)}</span></div>
        <div class="chg">${move(i.d1)}<span class="dim">${t("20 日", "20d")} ${move(i.d20, 1)}</span></div>
        ${Charts.spark(i.spark, "var(--series-1)", 120, 28)}
      </a>`).join("");
  }

  async function boot() {
    try {
      [meta, summary] = await Promise.all([Neva.get(`${API}/market`), Neva.get(`${API}/summary`)]);
    } catch (e) { fail($("main"), e); return; }
    if (!meta.lastDate) { $("main").innerHTML = `<div class="empty">${t("第一次同步还在进行，几分钟后再刷新。", "The first data sync is still running; refresh in a few minutes.")}</div>`; return; }
    header();
    route();
  }

  // ---- logic graph ------------------------------------------------------------------------------------
  function edgeKind(r) { return r.used ? "predict" : r.comove?.verdict === "holds" ? "explain" : "none"; }

  function graph(host) {
    const p = meta.pack;
    const used = meta.relations.filter(r => r.used).length;
    const explain = meta.relations.filter(r => r.comove?.verdict === "holds").length;
    host.innerHTML = `
      <div class="sec-head">
        <div><h2>${t("数据之间的逻辑", "How the data connect")}</h2>
        <p class="muted">${t(`每条箭头是一条可检验的假设。代码分两种方式检验：<b>同步</b>看两者是否同时变动（能解释行情），<b>领先</b>看驱动是否提前反映在价格上（能用来交易）。样本内（${esc(p?.split || "")} 之前）选关系，样本外检验它。`,
          `Every arrow is a testable claim, checked two ways: <b>same-period</b> (do they move together — explains moves) and <b>leading</b> (does the driver show up in later prices — tradable). Relations are chosen on data before ${esc(p?.split || "")} and judged after it.`)}</p></div>
        <div class="tiles">
          <div class="tile"><span class="k">${t("关系", "Relations")}</span><strong>${meta.relations.length}</strong></div>
          <div class="tile"><span class="k">${t("能解释行情", "Explain moves")}</span><strong>${explain}</strong></div>
          <div class="tile"><span class="k">${t("进逻辑包（能预测）", "In the pack (predictive)")}</span><strong>${used}</strong></div>
        </div>
      </div>
      <div class="card graph-card"><div class="graph-legend">
        <span><i class="e predict"></i>${t("进逻辑包：样本内能预测", "In the pack: predicts in-sample")}</span>
        <span><i class="e explain"></i>${t("只能解释：同步联动成立", "Explains only: moves together")}</span>
        <span><i class="e none"></i>${t("没被数据支持", "Not supported by data")}</span></div>
        <div id="graphSvg" class="graph-svg"></div></div>
      <div class="card"><table class="tbl rel-tbl"><thead><tr>
        <th>${t("关系", "Relation")}</th><th>${t("同步联动", "Same-period")}</th><th>${t("领先 · 样本内", "Leading · in-sample")}</th><th>${t("领先 · 样本外", "Leading · out-of-sample")}</th><th>${t("今天的读数", "Today's reading")}</th></tr></thead>
        <tbody>${meta.relations.map(r => `<tr data-r="${esc(r.id)}" tabindex="0">
          <td><div class="rn">${r.used ? `<span class="pill accent">${t("逻辑包", "pack")}${r.weight < 1 ? " ×" + r.weight : ""}</span>` : ""}${r.origin === "gen" ? `<span class="pill">${t("AI 提出", "AI proposed")}</span>` : ""}${selfPill(r)}${esc(t(r.name, r.name_en))}</div><div class="dim small">${esc(t(r.why, r.why_en))}</div></td>
          <td>${badge(r.comove?.verdict)}${r.kind === "self" ? "" : `<div class="dim small mono">r ${signed(r.comove?.corr)} · t ${signed(r.comove?.t, 1)}</div>`}</td>
          <td>${badge(r.inSample?.verdict)}<div class="dim small mono">IC ${signed(r.inSample?.ic, 3)} · t ${signed(r.inSample?.t, 1)}</div></td>
          <td>${badge(r.outSample?.verdict)}<div class="dim small mono">IC ${signed(r.outSample?.ic, 3)}</div></td>
          <td>${r.state?.inSeason === false ? `<span class="dim">${t("不在季节内", "Out of season")}</span>` : viewText(r.state?.signal)}<div class="dim small mono">z ${signed(r.state?.z)}</div></td></tr>`).join("")}</tbody></table></div>
      <div id="relDetail"></div>
      ${packCard(p)}`;
    drawGraph($("#graphSvg"));
    $$(".rel-tbl tbody tr", host).forEach(tr => {
      const open = () => relDetail(tr.dataset.r);
      tr.addEventListener("click", open); tr.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
    });
  }

  function packCard(p) {
    if (!p) return "";
    const reg = Object.entries(p.regression || {}).filter(([, v]) => v.relations?.length);
    const rej = (p.rejected || []).filter(x => x.relation);
    return `<div class="card pack-card"><h3>${t("逻辑包的回归测试", "The pack's regression test")}</h3>
      <p class="muted small">${t(`版本 ${esc(p.version)} · ${p.origin === "gen" ? "大模型提出候选，代码检验" : "只用种子关系"} · 数据截至 ${esc(p.dataThrough)}。新版本只有在每个品种的样本外 Sharpe 不比上一版差超过 0.1 时才会发布。`,
        `Version ${esc(p.version)} · ${p.origin === "gen" ? "LLM proposals, tested by code" : "seed relations only"} · data through ${esc(p.dataThrough)}. A new version ships only if no instrument loses more than 0.1 out-of-sample Sharpe.`)}</p>
      ${reg.length ? `<table class="tbl compact"><thead><tr><th>${t("品种", "Instrument")}</th><th>${t("用到的关系", "Relations")}</th><th>${t("样本内 Sharpe", "In-sample Sharpe")}</th><th>${t("样本外 Sharpe", "Out-of-sample Sharpe")}</th><th>${t("样本外收益", "OOS return")}</th></tr></thead><tbody>
        ${reg.map(([k, v]) => `<tr><td>${esc(name(instOf(k)))}</td><td>${v.relations.length}</td><td class="mono">${signed(v.inSample?.sharpe)}</td><td class="mono">${signed(v.outSample?.sharpe)}</td><td>${move(v.outSample?.total, 1)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="empty-inline">${t("目前没有关系在样本内通过领先检验，逻辑包不持仓。复盘里的联动解释照常可用。", "No relation passes the in-sample leading test yet, so the pack holds no position. Same-period explanations still work in the review.")}</p>`}
      <p class="small">${(p.gate?.reasons || []).map(esc).join(" · ")}</p>
      ${rej.length ? `<details><summary>${t(`大模型提过、但没通过检验的假设（${rej.length}）`, `Hypotheses the LLM proposed that failed the test (${rej.length})`)}</summary>
        <ul class="rej">${rej.map(x => `<li><strong>${esc(t(x.relation.name, x.relation.name_en))}</strong> <span class="dim">— ${esc(x.reason)}</span><div class="dim small">${esc(t(x.relation.why, x.relation.why_en))}</div></li>`).join("")}</ul></details>` : ""}
    </div>`;
  }

  function drawGraph(host) {
    // phones keep the desktop layout at a fixed width and scroll it sideways inside the card
    const W = Math.max(host.clientWidth, 760), H = 400, NW = 150, NH = 54;
    const pos = {};
    for (const n of meta.nodes) pos[n.id] = { x: NW / 2 + 6 + n.x * (W - NW - 12), y: NH / 2 + 6 + n.y * (H - NH - 12), node: n };
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.innerHTML = `<defs>${["predict", "explain", "none"].map(k => `<marker id="ar-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" class="ah ${k}"/></marker>`).join("")}</defs>`;
    const pairCount = {};
    const clip = (a, b) => { // point where segment a→b leaves b's box
      const dx = a.x - b.x, dy = a.y - b.y, sx = (NW / 2 + 4) / Math.abs(dx || 1e-6), sy = (NH / 2 + 4) / Math.abs(dy || 1e-6), s = Math.min(sx, sy, 1);
      return { x: b.x + dx * s, y: b.y + dy * s };
    };
    const tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true; host.appendChild(tip);
    const order = { none: 0, explain: 1, predict: 2 };
    [...meta.relations].sort((a, b) => order[edgeKind(a)] - order[edgeKind(b)]).forEach(r => {
      const a = pos[r.driver], b = pos[r.target];
      if (!a || !b || a === b) return;
      const key = [r.driver, r.target].sort().join("|");
      const k = pairCount[key] = (pairCount[key] || 0) + 1;
      const off = (k - 1) * 26 * (k % 2 ? 1 : -1) + (k > 1 ? 0 : 0);
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const cx = mx - (b.y - a.y) / len * (16 + off), cy = my + (b.x - a.x) / len * (16 + off);
      const start = clip({ x: cx, y: cy }, a), end = clip({ x: cx, y: cy }, b);
      const kind = edgeKind(r);
      const g = document.createElementNS(NS, "g"); g.setAttribute("class", "edge " + kind); g.setAttribute("tabindex", 0);
      g.innerHTML = `<path class="hit" d="M${start.x},${start.y}Q${cx},${cy} ${end.x},${end.y}"/><path class="ln" d="M${start.x},${start.y}Q${cx},${cy} ${end.x},${end.y}" marker-end="url(#ar-${kind})"/>`;
      const on = e => {
        tip.replaceChildren();
        const s = document.createElement("strong"); s.textContent = t(r.name, r.name_en);
        const d = document.createElement("div"); d.className = "dim"; d.textContent = `${t("同步", "same-period")} ${VERDICT[r.comove?.verdict]?.[0] || "—"} · ${t("领先", "leading")} ${VERDICT[r.inSample?.verdict]?.[0] || "—"}`;
        tip.append(s, d); tip.hidden = false;
        tip.style.left = Math.min(cx, W - 220) + "px"; tip.style.top = Math.max(cy - 50, 0) + "px";
        g.classList.add("hover");
      };
      const off2 = () => { tip.hidden = true; g.classList.remove("hover"); };
      g.addEventListener("pointerenter", on); g.addEventListener("pointerleave", off2); g.addEventListener("focus", on); g.addEventListener("blur", off2);
      g.addEventListener("click", () => relDetail(r.id));
      svg.appendChild(g);
    });
    for (const [id, p] of Object.entries(pos)) {
      const s = seriesOf(id), inst = instOf(id), si = summary?.instruments?.find(i => i.id === id);
      const g = document.createElementNS(NS, "g"); g.setAttribute("class", "node" + (inst ? " inst" : ""));
      g.setAttribute("transform", `translate(${p.x - NW / 2},${p.y - NH / 2})`);
      const val = s.latest === null || s.latest === undefined ? "—" : num(s.latest, Math.abs(s.latest) >= 1000 ? 0 : 2);
      g.innerHTML = `<rect width="${NW}" height="${NH}" rx="4"/><text x="10" y="21" class="nm"></text><text x="10" y="41" class="val"></text>${si ? `<text x="${NW - 10}" y="41" text-anchor="end" class="chg ${Neva.dir(si.d1)}"></text>` : ""}`;
      g.querySelector(".nm").textContent = name(s);
      g.querySelector(".val").textContent = `${val} ${s.unit}`;
      if (si) g.querySelector(".chg").textContent = pct(si.d1, 1);
      svg.appendChild(g);
    }
    host.appendChild(svg);
  }

  async function relDetail(id) {
    const host = $("#relDetail");
    $$(".rel-tbl tr").forEach(tr => tr.classList.toggle("sel", tr.dataset.r === id));
    host.innerHTML = `<div class="card"><div class="dim">${t("加载中…", "Loading…")}</div></div>`;
    let d;
    try { d = await Neva.get(`${API}/relation/${encodeURIComponent(id)}`); } catch (e) { fail(host, e); return; }
    const r = d.relation, drv = seriesOf(r.driver), tgt = instOf(r.target);
    const e = d.evidence, co = d.comove;
    host.innerHTML = `<div class="card rel-card">
      <div class="rel-top"><div><span class="label">${t("关系详情", "Relation")}</span><h3>${esc(t(r.name, r.name_en))}</h3>
        <p>${esc(t(r.why, r.why_en))}</p><p class="dim small">${esc(describe(r))}</p></div>
        <div class="rel-actions"><a class="btn" href="#backtest?target=${esc(r.target)}&rel=${esc(r.id)}">${t("单独回测这条", "Backtest this alone")}</a><button class="btn ghost" id="relClose">${t("关闭", "Close")}</button></div></div>
      <div class="ev-grid">
        <div><span class="k">${t("同步联动", "Same-period")}</span>${badge(co.verdict)}<p class="small">${r.kind === "self" ? t("价格和它自己同步变动是必然的，这一项不检验。", "A price always moves with itself, so this test does not apply.") : t(`${co.horizon} 日窗口不重叠取样 ${co.n} 次，相关系数 ${signed(co.corr)}（按假设方向），t = ${signed(co.t, 1)}`, `${co.n} non-overlapping ${co.horizon}-day windows, correlation ${signed(co.corr)} in the claimed direction, t = ${signed(co.t, 1)}`)}</p></div>
        <div><span class="k">${t("领先 · 全样本", "Leading · full history")}</span>${badge(e.verdict)}<p class="small">${t(`IC ${signed(e.ic, 3)}，t = ${signed(e.t, 1)}；信号触发 ${e.active} 天，方向命中率 ${e.hit === null ? "—" : pct(e.hit, 0, false)}，触发后平均收益 ${pct(e.avgActive)}`, `IC ${signed(e.ic, 3)}, t = ${signed(e.t, 1)}; triggered on ${e.active} days, direction right ${e.hit === null ? "—" : pct(e.hit, 0, false)}, average return after a trigger ${pct(e.avgActive)}`)}</p></div>
        <div><span class="k">${t("样本内 → 样本外", "In → out of sample")}</span>${badge(d.inSample?.verdict)} → ${badge(d.outSample?.verdict)}<p class="small">${t(`以 ${esc(d.split)} 为界。IC ${signed(d.inSample?.ic, 3)} → ${signed(d.outSample?.ic, 3)}`, `Split at ${esc(d.split)}. IC ${signed(d.inSample?.ic, 3)} → ${signed(d.outSample?.ic, 3)}`)}</p></div>
      </div>
      <div class="grid2">
        <div><h4>${esc(name(drv))} <span class="dim">${esc(drv.unit)}</span></h4><div id="chDrv"></div></div>
        <div><h4>${esc(name(tgt))} <span class="dim">${esc(tgt.unit)}</span></h4><div id="chTgt"></div></div>
      </div>
      <div class="grid2">
        <div><h4>${t("信号强度（标准化读数）", "Signal (standardized reading)")}</h4><div id="chZ"></div></div>
        <div><h4>${t(`按读数分五档：之后 ${r.horizon} 日 ${name(tgt)} 平均涨跌`, `Five buckets by reading: average ${name(tgt)} move over the next ${r.horizon} days`)}</h4><div id="chBk"></div></div>
      </div>
      ${e.byYear?.length ? `<h4>${t("每年的 IC（按假设方向，正数说明当年成立）", "IC by year (in the claimed direction; positive = held that year)")}</h4><div id="chYr"></div>` : ""}
    </div>`;
    $("#relClose").onclick = () => { host.innerHTML = ""; $$(".rel-tbl tr").forEach(tr => tr.classList.remove("sel")); };
    const c = d.chart;
    Charts.line($("#chDrv"), { dates: c.dates, series: [{ name: name(drv), values: c.driver, color: C.s1 }], height: 170 });
    Charts.line($("#chTgt"), { dates: c.dates, series: [{ name: name(tgt), values: c.target, color: C.s2 }], height: 170 });
    Charts.line($("#chZ"), { dates: c.dates, series: [{ name: "z", values: c.feature, color: C.s3, area: true }], height: 170, zero: true });
    if (d.buckets.length) Charts.columns($("#chBk"), { labels: d.buckets.map(b => "Q" + b.bucket), sub: d.buckets.map(b => `${b.zMin}~${b.zMax}`), values: d.buckets.map(b => b.avgFwd),
      tips: d.buckets.map(b => t(`读数 ${b.zMin} ~ ${b.zMax}，${b.n} 天，上涨占 ${Math.round(b.up * 100)}%`, `reading ${b.zMin} to ${b.zMax}, ${b.n} days, up ${Math.round(b.up * 100)}%`)),
      format: v => pct(v, 2), height: 190, color: C.s1 });
    else $("#chBk").innerHTML = `<div class="viz-empty">${t("样本太少，不分档", "Too few observations to bucket")}</div>`;
    if (e.byYear?.length) Charts.columns($("#chYr"), { labels: e.byYear.map(y => String(y.year).slice(2)), values: e.byYear.map(y => y.ic), format: v => v.toFixed(2), height: 170, color: C.s1,
      tips: e.byYear.map(y => `${y.year} · ${y.n} ${t("天", "days")}`) });
    host.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---- review -----------------------------------------------------------------------------------------
  async function review(host, day) {
    host.innerHTML = `<div class="dim">${t("加载中…", "Loading…")}</div>`;
    let rv, dates;
    try { [rv, { dates }] = await Promise.all([Neva.get(`${API}/review${day ? "?date=" + day : ""}`), Neva.get(`${API}/review/dates`)]); }
    catch (e) { fail(host, e); return; }
    if (rv.error) { fail(host, rv.error); return; }
    const i = dates.indexOf(rv.date);
    const comp = rv.composite || [];
    const rels = rv.relations || [];
    const checks = { right: [t("应验", "Right"), "ok"], wrong: [t("背离", "Wrong"), "no"], none: [t("当时没有看法", "No view then"), "na"] };
    host.innerHTML = `
      <div class="sec-head"><div><h2>${t("复盘", "Daily review")} · ${esc(rv.date)}</h2>
        <p class="muted">${t("当天的行情，放到逻辑链里逐条对照：哪些关系应验了，哪些背离了，逻辑包对下一个交易日怎么看。所有数字都由代码从数据算出。", "The day's moves read against the logic chain: which relations played out, which broke, and what the pack expects next. Every number is computed from the data.")}</p></div>
        <div class="date-nav"><button class="btn" id="rvPrev" ${i < dates.length - 1 ? "" : "disabled"}>‹</button>
          <select class="input" id="rvDate">${dates.map(d => `<option ${d === rv.date ? "selected" : ""}>${d}</option>`).join("")}</select>
          <button class="btn" id="rvNext" ${i > 0 ? "" : "disabled"}>›</button></div></div>
      ${rv.narrative ? `<div class="card narrative"><span class="label">${t("AI 摘要 · 只复述下面的数字", "AI summary · restates the numbers below")}</span><p>${esc(t(rv.narrative, rv.narrativeEn || rv.narrative))}</p></div>` : ""}
      <div class="rv-insts">${rv.instruments.map(x => `<div class="card rv-inst"><div class="top"><strong>${esc(name(x))}</strong><span class="mono dim">${esc(x.contract || "")}</span></div>
        <div class="px">${num(x.close, x.close >= 1000 ? 0 : 2)} <span class="dim small">${esc(x.unit)}</span></div>
        <div class="row"><span>${t("当日", "Day")}</span>${move(x.d1)}</div><div class="row"><span>${t("5 日", "5d")}</span>${move(x.d5)}</div><div class="row"><span>${t("20 日", "20d")}</span>${move(x.d20)}</div></div>`).join("")}</div>
      <div class="card"><h3>${t("逻辑包的判断", "What the pack said")}</h3>
        ${comp.length ? `<table class="tbl"><thead><tr><th>${t("品种", "Instrument")}</th><th>${t("前一日收盘时的看法", "View at the prior close")}</th><th>${t("当日实际", "What happened")}</th><th>${t("结果", "Result")}</th><th>${t("近 20 日命中", "Hit rate, 20 days")}</th><th>${t("对下一交易日", "For the next session")}</th></tr></thead><tbody>
          ${comp.map(c => `<tr><td>${esc(name(instOf(c.target)))}</td><td>${viewText(c.yesterday)}</td><td>${move(c.realized)}</td>
            <td>${c.right === null ? `<span class="dim">${t("没有看法", "No view")}</span>` : c.right ? `<span class="vbadge ok">${t("对", "Right")}</span>` : `<span class="vbadge no">${t("错", "Wrong")}</span>`}</td>
            <td class="mono">${c.hit20 === null ? "—" : pct(c.hit20, 0, false)} <span class="dim">/ ${c.n20}</span></td><td>${viewText(c.today)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="empty-inline">${t("逻辑包里还没有能预测的关系，所以不给方向。下面的联动照样能解释当天的行情。", "The pack has no predictive relation yet, so it takes no view. The links below still explain the day.")}</p>`}
      </div>
      <div class="card"><h3>${t("逻辑链逐条对照", "Relation by relation")}</h3><table class="tbl rv-rel"><thead><tr><th>${t("关系", "Relation")}</th><th>${t("驱动今天的读数", "Driver today")}</th><th>${t("它指向", "Points to")}</th><th>${t("目标当日", "Target today")}</th><th>${t("它 N 日前的看法 → 这 N 日实际", "Its view N days ago → those N days")}</th></tr></thead><tbody>
        ${rels.map(r => `<tr class="${r.used ? "" : "dimrow"}"><td>${r.used ? `<span class="pill accent">${t("逻辑包", "pack")}</span>` : ""}${selfPill(r)}${esc(t(r.name, r.nameEn))}</td>
          <td class="mono">${r.state?.driver === null || r.state?.driver === undefined ? "—" : num(r.state.driver, Math.abs(r.state.driver) >= 1000 ? 0 : 2)} <span class="dim">z ${signed(r.state?.z)}</span></td>
          <td>${r.state?.inSeason === false ? `<span class="dim">${t("不在季节内", "Out of season")}</span>` : viewText(r.state?.signal)}</td>
          <td>${move(r.targetD1)}</td>
          <td>${r.check === "none" ? `<span class="dim">${checks.none[0]}</span>` : `<span class="vbadge ${checks[r.check][1]}">${checks[r.check][0]}</span> <span class="dim small">${r.horizon}${t(" 日 ", "d ")}</span>${move(r.targetH, 1)}`}</td></tr>`).join("")}</tbody></table></div>
      <div class="grid2">
        <div class="card"><h3>${t("异动", "Unusual moves")}</h3>${rv.movers.length ? `<ul class="movers">${rv.movers.map(x => `<li><span>${esc(name(x))}</span><span class="mono">${signed(x.change)} ${esc(x.unit)}</span><span class="dim mono">${signed(x.z, 1)}σ</span></li>`).join("")}</ul>`
          : `<p class="empty-inline">${t("没有序列的单日变化超过过去一年的 2 倍标准差。", "No series moved more than 2 standard deviations of its past year.")}</p>`}</div>
        ${rv.forecasts.length ? `<div class="card"><h3>${t("产区天气预报（未来 16 天）", "Growing-belt forecast (next 16 days)")}</h3><p class="dim small">${t("预报只用于提示，不进历史数据和回测。", "Forecasts are shown for context only; they never enter history or backtests.")}</p>
          ${rv.forecasts.map(f => `<div class="fc"><div class="row"><strong>${esc(name(f))}</strong><span class="dim mono">${f.unit === "mm" ? t("合计 ", "total ") + f.sum + " mm" : t("最低 ", "min ") + f.min + " " + esc(f.unit)}</span></div><div class="fc-chart" data-f="${esc(f.id)}"></div></div>`).join("")}</div>` : ""}
      </div>`;
    $("#rvPrev").onclick = () => review(host, dates[i + 1]);
    $("#rvNext").onclick = () => review(host, dates[i - 1]);
    $("#rvDate").onchange = e => review(host, e.target.value);
    for (const f of rv.forecasts) Charts.line($(`.fc-chart[data-f="${f.id}"]`, host), { dates: f.points.map(p => p[0]), series: [{ name: name(f), values: f.points.map(p => p[1]), color: C.s1, area: f.unit === "mm" }], height: 120, zero: f.unit === "mm" });
  }

  // ---- backtest ---------------------------------------------------------------------------------------
  function backtest(host) {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    const targets = meta.instruments.filter(i => meta.relations.some(r => r.target === i.id));
    let target = q.get("target") || (targets.find(i => meta.relations.some(r => r.target === i.id && r.used)) || targets[0])?.id;
    const only = q.get("rel");
    host.innerHTML = `
      <div class="sec-head"><div><h2>${t("回测", "Backtest")}</h2><p class="muted">${t("选品种和关系，按它们合成的看法持仓：收盘时决定，下一交易日兑现，扣手续费和滑点。国内品种的收益只在同一合约内计算，换月不算收益。", "Pick an instrument and relations; the position follows their combined view, decided at the close and earned on the next session, net of costs. Domestic returns are measured inside one contract, so rolls are not returns.")}</p></div></div>
      <div class="card bt-form">
        <div class="bt-row">
          <label>${t("品种", "Instrument")}<select class="input" id="btTarget">${targets.map(i => `<option value="${i.id}" ${i.id === target ? "selected" : ""}>${esc(name(i))}</option>`).join("")}</select></label>
          <label>${t("开始", "From")}<input class="input" type="date" id="btStart" value="${meta.firstDate}"></label>
          <label>${t("结束", "To")}<input class="input" type="date" id="btEnd" value="${meta.lastDate}"></label>
          <label>${t("成本（基点/换手）", "Cost (bps per turnover)")}<input class="input" type="number" id="btCost" value="3" min="0" max="100" step="0.5"></label>
          <label>${t("信号门槛", "Signal threshold")}<input class="input" type="number" id="btThr" value="0" min="0" max="1" step="0.05"></label>
          <label class="chk"><input type="checkbox" id="btDisc"> ${t("满仓/空仓（不按强弱）", "All-in / flat (ignore strength)")}</label>
          <label class="chk"><input type="checkbox" id="btLong"> ${t("只做多", "Long only")}</label>
        </div>
        <div id="btRels"></div>
        <div class="bt-run"><button class="btn primary" id="btRun">${t("运行回测", "Run backtest")}</button><span class="dim small" id="btNote"></span></div>
      </div>
      <div id="btOut"></div>`;
    const renderRels = () => {
      const rs = meta.relations.filter(r => r.target === target);
      const anyUsed = rs.some(r => r.used);
      $("#btRels").innerHTML = `<div class="bt-rels-head"><strong>${t("关系", "Relations")}</strong><span class="dim small">${t("默认勾选逻辑包里的关系；可以改参数后重跑（改过的版本只在这里试，不进逻辑包）。", "The pack's relations are ticked by default; edit parameters to experiment (edits stay here and never enter the pack).")}</span></div>
        <table class="tbl compact bt-rels"><thead><tr><th></th><th>${t("关系", "Relation")}</th><th>${t("领先 · 样本内", "Leading · in-sample")}</th><th>${t("窗口", "Window")}</th><th>${t("滞后", "Lag")}</th><th>${t("持有", "Horizon")}</th><th>${t("方向", "Sign")}</th></tr></thead><tbody>
        ${rs.map(r => `<tr data-r="${esc(r.id)}"><td><input type="checkbox" ${only ? (r.id === only ? "checked" : "") : (anyUsed ? (r.used ? "checked" : "") : "checked")}></td>
          <td>${selfPill(r)}${esc(t(r.name, r.name_en))}</td><td>${badge(r.inSample?.verdict)}</td>
          <td><input class="input sm" data-f="window" type="number" min="1" max="250" value="${r.window}"></td>
          <td><input class="input sm" data-f="lag" type="number" min="0" max="20" value="${r.lag}"></td>
          <td><input class="input sm" data-f="horizon" type="number" min="1" max="60" value="${r.horizon}"></td>
          <td><select class="input sm" data-f="sign"><option value="1" ${r.sign > 0 ? "selected" : ""}>${t("同向", "+")}</option><option value="-1" ${r.sign < 0 ? "selected" : ""}>${t("反向", "−")}</option></select></td></tr>`).join("")}</tbody></table>`;
    };
    renderRels();
    $("#btTarget").onchange = e => { target = e.target.value; renderRels(); };
    const run = async () => {
      const rows = $$("#btRels tbody tr").filter(tr => tr.querySelector("input[type=checkbox]").checked);
      if (!rows.length) { Neva.toast(t("至少选一条关系", "Pick at least one relation")); return; }
      const custom = rows.map(tr => {
        const r = meta.relations.find(x => x.id === tr.dataset.r);
        const out = {}; for (const k of ["id", "driver", "target", "transform", "window", "lag", "horizon", "sign", "name", "name_en", "why", "why_en", "threshold", "months", "origin"]) out[k] = r[k];
        $$("[data-f]", tr).forEach(inp => out[inp.dataset.f] = Number(inp.value));
        return out;
      });
      const edited = custom.some(c => { const r = meta.relations.find(x => x.id === c.id); return ["window", "lag", "horizon", "sign"].some(k => r[k] !== c[k]); });
      const usedSet = meta.relations.filter(r => r.target === target && r.used).map(r => r.id).sort().join();
      const isPack = !edited && custom.map(c => c.id).sort().join() === usedSet;
      $("#btRun").disabled = true; $("#btNote").textContent = t("计算中…", "Running…");
      try {
        const body = { target, start: $("#btStart").value, end: $("#btEnd").value, costBps: +$("#btCost").value, threshold: +$("#btThr").value,
          discrete: $("#btDisc").checked, longOnly: $("#btLong").checked };
        if (isPack) body.relations = null; else body.custom = custom;
        if (!isPack && !edited) { delete body.custom; body.relations = custom.map(c => c.id); }
        const res = await Neva.post(`${API}/backtest`, body);
        $("#btNote").textContent = isPack ? t("这是逻辑包本身的配置（带权重）", "This is the pack's own configuration (weighted)") : edited ? t("用了改过的参数", "Using edited parameters") : "";
        renderBt($("#btOut"), res);
      } catch (e) { fail($("#btOut"), e); $("#btNote").textContent = ""; }
      finally { $("#btRun").disabled = false; }
    };
    $("#btRun").onclick = run;
    run();
  }

  function renderBt(host, b) {
    const m = b.metrics, bm = b.benchmarkMetrics, tgt = instOf(b.target);
    const tile = (k, v, bv, fmt = x => pct(x, 1, false)) => `<div class="tile"><span class="k">${k}</span><strong>${v === null || v === undefined ? "—" : fmt(v)}</strong>${bv !== undefined ? `<span class="dim small">${t("买入持有", "Buy & hold")} ${bv === null ? "—" : fmt(bv)}</span>` : ""}</div>`;
    host.innerHTML = `
      <div class="tiles bt-tiles">
        ${tile(t("总收益", "Total return"), m.total, bm.total, x => pct(x, 1))}${tile(t("年化", "Annualized"), m.annual, bm.annual, x => pct(x, 1))}
        ${tile("Sharpe", m.sharpe, bm.sharpe, x => x.toFixed(2))}${tile(t("最大回撤", "Max drawdown"), m.maxDrawdown, bm.maxDrawdown, x => pct(x, 1))}
        ${tile(t("持仓天数占比", "Time in market"), m.exposure)}${tile(t("持仓日胜率", "Win rate (days held)"), m.winRate)}
      </div>
      ${b.split ? `<div class="card oos"><strong>${t("样本内 vs 样本外", "In-sample vs out-of-sample")}</strong> <span class="dim small">${t(`以 ${esc(b.split)} 为界：逻辑包只用界线之前的数据挑关系`, `split at ${esc(b.split)}: the pack picks relations from data before it`)}</span>
        <table class="tbl compact"><thead><tr><th></th><th>${t("年化", "Annualized")}</th><th>Sharpe</th><th>${t("最大回撤", "Max DD")}</th><th>${t("天数", "Days")}</th></tr></thead><tbody>
        ${[["inSample", t("样本内", "In-sample")], ["outSample", t("样本外", "Out-of-sample")]].map(([k, l]) => { const x = b[k] || {}; return `<tr><td>${l}</td><td>${move(x.annual, 1)}</td><td class="mono">${signed(x.sharpe)}</td><td>${pct(x.maxDrawdown, 1)}</td><td class="mono">${x.days ?? "—"}</td></tr>`; }).join("")}</tbody></table></div>` : ""}
      <div class="card"><h3>${t("净值", "Equity")}</h3><div id="btEq"></div></div>
      <div class="grid2"><div class="card"><h3>${t("回撤", "Drawdown")}</h3><div id="btDd"></div></div><div class="card"><h3>${t("仓位（1 = 满仓做多，−1 = 满仓做空）", "Position (1 = fully long, −1 = fully short)")}</h3><div id="btPos"></div></div></div>
      <div class="card"><h3>${t("逐年", "By year")}</h3><table class="tbl compact"><thead><tr><th>${t("年份", "Year")}</th><th>${t("策略", "Strategy")}</th><th>${t("买入持有", "Buy & hold")}</th></tr></thead><tbody>
        ${b.byYear.map(y => `<tr><td>${y.year}</td><td>${move(y.ret, 1)}</td><td>${move(y.bench, 1)}</td></tr>`).join("")}</tbody></table>
        ${tgt?.note ? `<p class="dim small">${esc(t(tgt.note, tgt.noteEn))}</p>` : ""}</div>`;
    const marker = b.split ? { date: b.split, label: t("样本外 →", "out-of-sample →") } : null;
    Charts.line($("#btEq"), { dates: b.dates, series: [{ name: t("策略", "Strategy"), values: b.equity, color: C.s2 }, { name: t(`买入持有 ${name(tgt)}`, `Buy & hold ${name(tgt)}`), values: b.benchmark, color: C.muted }], height: 300, marker, format: v => v.toFixed(2) });
    Charts.line($("#btDd"), { dates: b.dates, series: [{ name: t("回撤", "Drawdown"), values: b.drawdown, color: C.s2, area: true }], height: 180, zero: true, format: v => pct(v, 0, false), marker });
    Charts.line($("#btPos"), { dates: b.dates, series: [{ name: t("仓位", "Position"), values: b.position, color: C.s1, area: true }], height: 180, zero: true, format: v => v.toFixed(2), marker });
  }

  // ---- paper trading ----------------------------------------------------------------------------------
  let current = null;
  async function paper(host) {
    host.innerHTML = `<div class="dim">${t("加载中…", "Loading…")}</div>`;
    const user = await new Promise(r => { const go = () => window.NevaAuth ? window.NevaAuth.ready.then(r, () => r(null)) : setTimeout(go, 80); go(); });
    if (!user) {
      host.innerHTML = `<div class="card cta"><h2>${t("虚拟交易", "Paper trading")}</h2><p class="muted">${t(`每个账户 ${num(meta.capital, 0)} ${meta.currency} 虚拟资金。可以自己下单（按实时行情成交），也可以交给逻辑包每天收盘后自动调仓。每笔成交都记着是谁下的。`, `Each account starts with ${num(meta.capital, 0)} ${meta.currency} of virtual money. Trade it yourself at live prices, or let the logic pack rebalance it after every close. Every fill records who placed it.`)}</p>
        <a class="btn primary" href="/login?next=${encodeURIComponent(location.pathname + "#paper")}">${t("登录后开始", "Sign in to start")}</a></div>`;
      return;
    }
    let list;
    try { ({ accounts: list } = await Neva.authed("GET", `${API}/paper`)); } catch (e) { fail(host, e); return; }
    host.innerHTML = `<div class="sec-head"><div><h2>${t("虚拟交易", "Paper trading")}</h2><p class="muted">${t("市价单按新浪实时行情成交（拿不到时用最近收盘价），加一跳滑点和手续费；名义价值最多 3 倍权益。", "Market orders fill at Sina's live price (or the last close when unavailable) plus one tick and commission; notional is capped at 3× equity.")}</p></div>
      <button class="btn primary" id="newAcct">${t("新建账户", "New account")}</button></div>
      <div class="acct-list" id="acctList"></div><div id="acctView"></div>`;
    $("#newAcct").onclick = newAccount;
    renderAccounts(list);
    if (list.length) openAccount((list.find(a => a.id === current) || list[0]).id);
    else $("#acctView").innerHTML = `<div class="card empty">${t("还没有账户。新建一个：自己下单，或交给逻辑包。", "No accounts yet. Create one to trade yourself or hand it to the logic pack.")}</div>`;
  }

  function renderAccounts(list) {
    $("#acctList").innerHTML = list.map(a => `<button class="card acct ${a.id === current ? "sel" : ""}" data-a="${a.id}">
      <div class="top"><strong>${esc(a.name)}</strong><span class="pill ${a.mode === "agent" ? "accent" : ""}">${a.mode === "agent" ? t("逻辑包代管", "Pack-managed") : t("手动", "Manual")}</span></div>
      <div class="px">${num(a.equity, 0)} <span class="dim small">${esc(a.currency)}</span></div><div>${move(a.return)}</div></button>`).join("");
    $$("#acctList .acct").forEach(b => b.onclick = () => openAccount(b.dataset.a));
  }

  async function newAccount() {
    const nm = await Neva.prompt(t("账户名称", "Account name"), t("模拟账户", "Paper account"));
    if (nm === null) return;
    const agent = await Neva.dialog({ title: t("谁来下单？", "Who trades it?"), body: t("选“交给逻辑包”后，每个交易日收盘后按逻辑包的看法自动调仓（主力品种）。之后随时可以切换。", "\"Logic pack\" rebalances the main instrument after each close by the pack's view. You can switch any time."), ok: t("交给逻辑包", "Logic pack"), cancel: t("自己下单", "Myself") });
    try {
      const a = await Neva.authed("POST", `${API}/paper`, { name: nm || t("模拟账户", "Paper account"), mode: agent ? "agent" : "manual", agentInst: meta.main });
      if (agent) await Neva.authed("PATCH", `${API}/paper/${a.id}`, { mode: "agent" });
      current = a.id; loaded.paper = true; paper($(`section[data-tab="paper"]`));
    } catch (e) { Neva.toast(e.message); }
  }

  async function openAccount(id) {
    current = id;
    $$("#acctList .acct").forEach(b => b.classList.toggle("sel", b.dataset.a === id));
    const host = $("#acctView");
    let a, quotes;
    try { [a, quotes] = await Promise.all([Neva.authed("GET", `${API}/paper/${id}`), Neva.get(`${API}/quotes`)]); } catch (e) { fail(host, e); return; }
    const insts = meta.instruments;
    host.innerHTML = `
      <div class="tiles">
        <div class="tile"><span class="k">${t("权益", "Equity")}</span><strong>${num(a.equity, 0)}</strong><span class="dim small">${move(a.return)}</span></div>
        <div class="tile"><span class="k">${t("可用", "Available")}</span><strong>${num(a.available, 0)}</strong></div>
        <div class="tile"><span class="k">${t("占用保证金", "Margin")}</span><strong>${num(a.margin, 0)}</strong></div>
        <div class="tile"><span class="k">${t("浮动盈亏", "Unrealized")}</span><strong class="${Neva.dir(a.unrealized)}">${num(a.unrealized, 0)}</strong></div>
      </div>
      <div class="grid2 paper-grid">
        <div class="card">
          <div class="row-between"><h3>${t("持仓", "Positions")}</h3>
            <div class="mode-switch"><span class="dim small">${t("下单方", "Traded by")}</span>
              <select class="input sm" id="acMode"><option value="manual" ${a.mode === "manual" ? "selected" : ""}>${t("我自己", "Me")}</option><option value="agent" ${a.mode === "agent" ? "selected" : ""}>${t("逻辑包", "Logic pack")}</option></select>
              <select class="input sm" id="acInst" ${a.mode === "agent" ? "" : "hidden"}>${insts.map(i => `<option value="${i.id}" ${i.id === a.agentInst ? "selected" : ""}>${esc(name(i))}</option>`).join("")}</select>
              <button class="btn ghost sm" id="acDel">${t("删除", "Delete")}</button></div></div>
          ${a.positions.length ? `<table class="tbl compact"><thead><tr><th>${t("合约", "Contract")}</th><th>${t("手数", "Lots")}</th><th>${t("均价", "Avg")}</th><th>${t("现价", "Last")}</th><th>${t("浮盈", "P&L")}</th><th></th></tr></thead><tbody>
            ${a.positions.map(p => `<tr><td>${esc(name(p))} <span class="mono dim">${esc(p.contract)}</span>${p.isMain ? "" : ` <span class="pill">${t("非主力", "not main")}</span>`}</td><td class="mono ${p.lots > 0 ? "up" : "down"}">${p.lots > 0 ? "+" : ""}${p.lots}</td>
              <td class="mono">${num(p.avgPrice, 2)}</td><td class="mono" title="${esc(p.priceTime || "")}">${num(p.price, 2)}${p.priceSource === "realtime" ? "" : "*"}</td><td class="mono ${Neva.dir(p.unrealized)}">${num(p.unrealized, 0)}</td>
              <td>${a.mode === "manual" ? `<button class="btn sm" data-close="${esc(p.inst)}|${esc(p.contract)}|${p.lots}">${t("平仓", "Close")}</button>` : ""}</td></tr>`).join("")}</tbody></table>`
            : `<p class="empty-inline">${t("空仓", "No positions")}</p>`}
          <h3>${t("权益曲线", "Equity curve")}</h3><div id="acCurve"></div>
        </div>
        <div class="card ticket">
          <h3>${t("下单", "Order")}</h3>
          ${a.mode === "agent" ? `<p class="muted">${t(`这个账户由逻辑包代管：每个交易日收盘后，按逻辑包对${name(instOf(a.agentInst))}的看法调到目标仓位（看法 1.0 = 名义价值等于权益）。切回“我自己”就能手动下单。`, `The logic pack manages this account: after each close it moves ${name(instOf(a.agentInst))} to the pack's target (view 1.0 = notional equal to equity). Switch to "Me" to trade by hand.`)}</p>` : `
          <label>${t("品种", "Instrument")}<select class="input" id="tkInst">${insts.map(i => `<option value="${i.id}">${esc(name(i))}</option>`).join("")}</select></label>
          <div class="quote" id="tkQuote"></div>
          <label>${t("手数", "Lots")}<input class="input" id="tkLots" type="number" min="1" max="1000" value="1"></label>
          <div class="tk-btns"><button class="btn buy" id="tkBuy">${t("买入", "Buy")}</button><button class="btn sell" id="tkSell">${t("卖出", "Sell")}</button></div>
          <p class="dim small" id="tkInfo"></p>`}
        </div>
      </div>
      <div class="card"><h3>${t("成交记录", "Fills")}</h3>${a.trades.length ? `<table class="tbl compact"><thead><tr><th>${t("时间", "Time")}</th><th>${t("合约", "Contract")}</th><th>${t("方向", "Side")}</th><th>${t("手数", "Lots")}</th><th>${t("价格", "Price")}</th><th>${t("手续费", "Fee")}</th><th>${t("平仓盈亏", "Realized")}</th><th>${t("下单方", "By")}</th></tr></thead><tbody>
        ${a.trades.map(x => `<tr title="${esc(x.note || "")}"><td class="mono small">${esc(x.ts.replace("T", " ").slice(0, 16))}</td><td class="mono">${esc(x.contract)}</td><td class="${x.side === "buy" ? "up" : "down"}">${x.side === "buy" ? t("买", "Buy") : t("卖", "Sell")}</td><td class="mono">${x.lots}</td><td class="mono">${num(x.price, 2)}</td><td class="mono">${num(x.fee, 2)}</td><td class="mono ${Neva.dir(x.realized)}">${x.realized ? num(x.realized, 0) : "—"}</td><td><span class="pill ${x.by === "agent" ? "accent" : ""}">${x.by === "agent" ? t("逻辑包", "Pack") : t("本人", "Me")}</span></td></tr>`).join("")}</tbody></table>`
        : `<p class="empty-inline">${t("还没有成交", "No fills yet")}</p>`}</div>`;
    if (a.curve.length > 1) Charts.line($("#acCurve"), { dates: a.curve.map(c => c.date), series: [{ name: t("权益", "Equity"), values: a.curve.map(c => c.equity), color: C.s2 }], height: 160 });
    else $("#acCurve").innerHTML = `<p class="empty-inline">${t("每个交易日收盘后记一次权益，攒够两天就有曲线。", "Equity is recorded after each close; the curve appears after two days.")}</p>`;
    const patch = async body => { try { await Neva.authed("PATCH", `${API}/paper/${id}`, body); refresh(); } catch (e) { Neva.toast(e.message); } };
    $("#acMode").onchange = e => patch({ mode: e.target.value });
    $("#acInst").onchange = e => patch({ agentInst: e.target.value });
    $("#acDel").onclick = async () => { if (await Neva.confirm(t("删除这个账户和全部记录？", "Delete this account and its history?"), { danger: true, ok: t("删除", "Delete") })) { await Neva.authed("DELETE", `${API}/paper/${id}`); current = null; paper($(`section[data-tab="paper"]`)); } };
    const send = async (inst, side, lots, contract) => {
      try { const r = await Neva.authed("POST", `${API}/paper/${id}/orders`, { inst, side, lots, contract }); Neva.toast(t(`成交 ${r.fill.lots > 0 ? "+" : ""}${r.fill.lots} 手 @ ${r.fill.price}`, `Filled ${r.fill.lots > 0 ? "+" : ""}${r.fill.lots} @ ${r.fill.price}`)); refresh(); }
      catch (e) { Neva.toast(e.message); }
    };
    $$("[data-close]", host).forEach(b => b.onclick = () => { const [inst, contract, lots] = b.dataset.close.split("|"); send(inst, +lots > 0 ? "sell" : "buy", Math.abs(+lots), contract); });
    if (a.mode === "manual") {
      const showQuote = () => {
        const i = instOf($("#tkInst").value), q = quotes[i.id];
        $("#tkQuote").innerHTML = q ? `<span class="mono">${esc(q.contract)}</span> <strong>${num(q.price, 2)}</strong> <span class="dim small">${q.source === "realtime" ? t("实时", "live") : t("最近收盘", "last close")} · ${esc(q.time || "")}</span>` : `<span class="dim">${t("暂无报价", "No quote")}</span>`;
        const lots = +$("#tkLots").value || 1;
        $("#tkInfo").textContent = q ? t(`每手 ${i.multiplier} ${i.unit.split("/")[1] || ""}，名义价值约 ${num(q.price * i.multiplier * lots, 0)} ${i.currency}，保证金约 ${num(q.price * i.multiplier * lots * i.margin, 0)}`, `Contract size ${i.multiplier}; notional ≈ ${num(q.price * i.multiplier * lots, 0)} ${i.currency}, margin ≈ ${num(q.price * i.multiplier * lots * i.margin, 0)}`) : "";
      };
      $("#tkInst").onchange = showQuote; $("#tkLots").oninput = showQuote; showQuote();
      $("#tkBuy").onclick = () => send($("#tkInst").value, "buy", +$("#tkLots").value, null);
      $("#tkSell").onclick = () => send($("#tkInst").value, "sell", +$("#tkLots").value, null);
    }
    async function refresh() {
      try { const { accounts } = await Neva.authed("GET", `${API}/paper`); renderAccounts(accounts); openAccount(id); } catch (e) { Neva.toast(e.message); }
    }
  }

  // ---- data -------------------------------------------------------------------------------------------
  function data(host) {
    const groups = {};
    for (const s of meta.series) (groups[t(s.group, s.groupEn)] ||= []).push(s);
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    host.innerHTML = `<div class="sec-head"><div><h2>${t("数据", "Data")}</h2><p class="muted">${t("这个市场用到的全部序列，每小时同步一次。点一行看走势。", "Every series this market uses, re-synced hourly. Click a row to chart it.")}</p></div></div>
      <div class="grid-data"><div class="card"><table class="tbl compact data-tbl"><thead><tr><th>${t("序列", "Series")}</th><th>${t("最新", "Latest")}</th><th>${t("日期", "Date")}</th><th>${t("起始", "Since")}</th></tr></thead>
        ${Object.entries(groups).map(([g, ss]) => `<tbody><tr class="grp"><td colspan="4">${esc(g)}</td></tr>${ss.map(s => `<tr data-s="${esc(s.id)}" tabindex="0"><td>${esc(name(s))}${s.formula ? `<div class="dim small">${esc(s.formula)}</div>` : ""}</td><td class="mono">${s.latest === null ? "—" : num(s.latest, Math.abs(s.latest) >= 1000 ? 0 : 2)} <span class="dim">${esc(s.unit)}</span></td><td class="mono small">${esc(s.latestDate || "—")}</td><td class="mono small">${esc(s.since || "—")}</td></tr>`).join("")}</tbody>`).join("")}</table>
        <p class="dim small">${t("来源：新浪财经 / 雅虎财经（行情），100ppi via AkShare（现货与基差），欧洲央行 via Frankfurter（汇率），Open-Meteo（天气）。", "Sources: Sina Finance / Yahoo Finance (prices), 100ppi via AkShare (spot & basis), ECB via Frankfurter (FX), Open-Meteo (weather).")}</p></div>
        <div class="card sticky"><div class="row-between"><h3 id="dsName"></h3><div class="seg" id="dsRange"><button data-y="1">1Y</button><button data-y="3" class="on">3Y</button><button data-y="0">${t("全部", "All")}</button></div></div><div id="dsChart"></div></div></div>`;
    let sel = q.get("s") || meta.main, years = 3;
    const draw = async () => {
      const s = seriesOf(sel);
      $("#dsName").textContent = `${name(s)} · ${s.unit}`;
      $$(".data-tbl tr[data-s]").forEach(tr => tr.classList.toggle("sel", tr.dataset.s === sel));
      const start = years ? new Date(new Date(meta.lastDate) - years * 365 * 864e5).toISOString().slice(0, 10) : "";
      const d = await Neva.get(`${API}/series?ids=${encodeURIComponent(sel)}${start ? "&start=" + start : ""}`);
      Charts.line($("#dsChart"), { dates: d.dates, series: [{ name: name(s), values: d.series[sel], color: C.s1 }], height: 320 });
    };
    $$(".data-tbl tr[data-s]").forEach(tr => { const go = () => { sel = tr.dataset.s; draw(); }; tr.onclick = go; tr.onkeydown = e => { if (e.key === "Enter") go(); }; });
    $$("#dsRange button").forEach(b => b.onclick = () => { years = +b.dataset.y; $$("#dsRange button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
    draw();
  }

  // re-run a tab whose hash carries parameters (e.g. "#backtest?target=J&rel=…" from a relation card)
  addEventListener("hashchange", () => {
    const [k, qs] = location.hash.slice(1).split("?");
    if (qs && meta && (k === "backtest" || k === "data")) ({ backtest, data })[k]($(`section[data-tab="${k}"]`));
  });
  let rz; addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (meta && !$('section[data-tab="graph"]').hidden) { const g = $("#graphSvg"); g.innerHTML = ""; drawGraph(g); } }, 200); });
  boot();
})();
