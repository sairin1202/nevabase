/* Hand-written SVG charts: line (crosshair + one tooltip for every series), columns, sparkline.
   One y-axis per chart, always; two measures of different scale go in two charts. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const t = (zh, en) => window.Neva?.t(zh, en) ?? zh;
  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };
  const ticks = (lo, hi, n = 4) => {
    if (lo === hi) { lo -= 1; hi += 1; }
    const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= raw);
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  };
  const fmtDefault = v => Math.abs(v) >= 1e4 ? (v / 1e3).toFixed(0) + "K" : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(2).replace(/\.?0+$/, "") : v.toFixed(3).replace(/\.?0+$/, "");

  function tooltip(host) {
    let tip = host.querySelector(".viz-tip");
    if (!tip) { tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true; host.appendChild(tip); }
    return tip;
  }

  /** line(host, {dates, series: [{name, values, color, area, dash}], format, height, marker: {date, label}, zero}) */
  function line(host, o) {
    host.innerHTML = "";
    host.classList.add("viz");
    const W = Math.max(host.clientWidth || 640, 280), H = o.height || 260;
    const m = { l: 8, r: 56, t: 12, b: 26 };
    const fmt = o.format || fmtDefault;
    const series = o.series.filter(s => s.values?.some(v => v !== null && v !== undefined));
    const all = series.flatMap(s => s.values).filter(v => v !== null && v !== undefined && isFinite(v));
    if (!all.length) { host.innerHTML = `<div class="viz-empty">${t("没有数据", "No data")}</div>`; return; }
    let lo = Math.min(...all), hi = Math.max(...all);
    if (o.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const n = o.dates.length;
    const x = i => m.l + (W - m.l - m.r) * (n <= 1 ? 0.5 : i / (n - 1));
    const y = v => m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": o.label || "" }, host);
    for (const v of ticks(lo, hi)) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: v === 0 && o.zero ? "viz-base" : "viz-grid" }, svg);
      el("text", { x: W - m.r + 6, y: y(v) + 4, class: "viz-tick" }, svg).textContent = fmt(v);
    }
    // x ticks: first day of a few evenly spaced months/years
    const span = (new Date(o.dates[n - 1]) - new Date(o.dates[0])) / 864e5;
    const every = span > 2000 ? "year" : span > 400 ? "half" : span > 120 ? "quarter" : "month";
    let last = "";
    o.dates.forEach((d, i) => {
      const key = every === "year" ? d.slice(0, 4) : every === "half" ? d.slice(0, 4) + (d.slice(5, 7) < "07" ? "a" : "b") :
        every === "quarter" ? d.slice(0, 4) + Math.floor((+d.slice(5, 7) - 1) / 3) : d.slice(0, 7);
      if (key !== last && i > 0) {
        el("text", { x: x(i), y: H - 8, class: "viz-tick", "text-anchor": "middle" }, svg).textContent = every === "year" || every === "half" && key.endsWith("a") ? d.slice(0, 4) : d.slice(2, 7);
      }
      last = key;
    });
    if (o.marker) {
      const i = o.dates.findIndex(d => d >= o.marker.date);
      if (i > 0) {
        el("line", { x1: x(i), x2: x(i), y1: m.t, y2: H - m.b, class: "viz-marker" }, svg);
        el("text", { x: x(i) + 4, y: m.t + 10, class: "viz-tick" }, svg).textContent = o.marker.label;
      }
    }
    for (const s of series) {
      let dpath = "", started = false;
      s.values.forEach((v, i) => {
        if (v === null || v === undefined || !isFinite(v)) { started = false; return; }
        dpath += (started ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); started = true;
      });
      if (s.area) {
        const base = y(o.zero ? 0 : lo);
        const first = s.values.findIndex(v => v !== null), lastI = s.values.length - 1 - [...s.values].reverse().findIndex(v => v !== null);
        el("path", { d: dpath + `L${x(lastI)},${base}L${x(first)},${base}Z`, fill: s.color, "fill-opacity": 0.1, stroke: "none" }, svg);
      }
      el("path", { d: dpath, fill: "none", stroke: s.color, "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": s.dash || "" }, svg);
    }
    // legend (two or more series)
    if (series.length > 1) {
      const lg = document.createElement("div"); lg.className = "viz-legend";
      for (const s of series) { const it = document.createElement("span"); it.innerHTML = `<i style="background:${s.color}"></i>`; it.appendChild(document.createTextNode(s.name)); lg.appendChild(it); }
      host.insertBefore(lg, svg);
    }
    // crosshair + tooltip
    const cross = el("line", { y1: m.t, y2: H - m.b, class: "viz-cross", visibility: "hidden" }, svg);
    const dots = series.map(s => el("circle", { r: 4, fill: s.color, stroke: "var(--viz-surface)", "stroke-width": 2, visibility: "hidden" }, svg));
    const tip = tooltip(host);
    const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent", tabindex: 0 }, svg);
    const show = i => {
      i = Math.max(0, Math.min(n - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      tip.replaceChildren();
      const head = document.createElement("div"); head.className = "viz-tip-date"; head.textContent = o.dates[i]; tip.appendChild(head);
      series.forEach((s, k) => {
        const v = s.values[i];
        if (v === null || v === undefined) { dots[k].setAttribute("visibility", "hidden"); return; }
        dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); dots[k].setAttribute("visibility", "visible");
        const row = document.createElement("div"); row.className = "viz-tip-row";
        const key = document.createElement("i"); key.style.background = s.color;
        const val = document.createElement("strong"); val.textContent = (s.format || fmt)(v);
        const name = document.createElement("span"); name.textContent = s.name;
        row.append(key, val, name); tip.appendChild(row);
      });
      tip.hidden = false;
      const left = x(i) / W * host.clientWidth;
      tip.style.left = Math.min(Math.max(left + 12, 0), host.clientWidth - tip.offsetWidth - 4) + "px";
      tip.style.top = "28px";
      if (left + 12 + tip.offsetWidth > host.clientWidth) tip.style.left = Math.max(left - tip.offsetWidth - 12, 0) + "px";
    };
    const hide = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); };
    hit.addEventListener("pointermove", e => { const r = svg.getBoundingClientRect(); const px = (e.clientX - r.left) * W / r.width; show(Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))); });
    hit.addEventListener("pointerleave", hide);
    let cursor = n - 1;
    hit.addEventListener("focus", () => show(cursor));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", e => { if (e.key === "ArrowLeft") { cursor = Math.max(0, cursor - 1); show(cursor); } if (e.key === "ArrowRight") { cursor = Math.min(n - 1, cursor + 1); show(cursor); } });
  }

  /** columns(host, {labels, values, format, color, height, sub}) — bars from a zero baseline. */
  function columns(host, o) {
    host.innerHTML = ""; host.classList.add("viz");
    const W = Math.max(host.clientWidth || 400, 240), H = o.height || 200, m = { l: 8, r: 8, t: 18, b: 34 };
    const vals = o.values, fmt = o.format || fmtDefault;
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    if (lo === hi) hi = 1;
    const pad = (hi - lo) * 0.12; lo = lo < 0 ? lo - pad : lo; hi = hi > 0 ? hi + pad : hi;
    const y = v => m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H }, host);
    const band = (W - m.l - m.r) / vals.length, bw = Math.min(24, band * 0.6);
    const tip = tooltip(host);
    vals.forEach((v, i) => {
      const cx = m.l + band * (i + 0.5), top = y(Math.max(v, 0)), bot = y(Math.min(v, 0)), h = Math.max(bot - top, 1);
      const r = Math.min(4, h);
      // rounded data end, square at the baseline
      const d = v >= 0
        ? `M${cx - bw / 2},${bot}V${top + r}Q${cx - bw / 2},${top} ${cx - bw / 2 + r},${top}H${cx + bw / 2 - r}Q${cx + bw / 2},${top} ${cx + bw / 2},${top + r}V${bot}Z`
        : `M${cx - bw / 2},${top}V${bot - r}Q${cx - bw / 2},${bot} ${cx - bw / 2 + r},${bot}H${cx + bw / 2 - r}Q${cx + bw / 2},${bot} ${cx + bw / 2},${bot - r}V${top}Z`;
      const bar = el("path", { d, fill: (o.colorOf ? o.colorOf(v, i) : o.color) || "var(--series-1)", class: "viz-bar" }, svg);
      el("text", { x: cx, y: v >= 0 ? top - 5 : bot + 13, class: "viz-val", "text-anchor": "middle" }, svg).textContent = fmt(v);
      el("text", { x: cx, y: H - 16, class: "viz-tick", "text-anchor": "middle" }, svg).textContent = o.labels[i];
      if (o.sub) el("text", { x: cx, y: H - 3, class: "viz-tick", "text-anchor": "middle" }, svg).textContent = o.sub[i];
      const hitR = el("rect", { x: cx - band / 2, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent", tabindex: 0 }, svg);
      const on = () => { bar.classList.add("hover"); tip.replaceChildren(); const s = document.createElement("strong"); s.textContent = fmt(v); const l = document.createElement("span"); l.textContent = " " + (o.tips ? o.tips[i] : o.labels[i]); tip.append(s, l); tip.hidden = false; tip.style.left = Math.min(cx / W * host.clientWidth, host.clientWidth - tip.offsetWidth - 4) + "px"; tip.style.top = "4px"; };
      const off = () => { bar.classList.remove("hover"); tip.hidden = true; };
      hitR.addEventListener("pointerenter", on); hitR.addEventListener("pointerleave", off); hitR.addEventListener("focus", on); hitR.addEventListener("blur", off);
    });
    el("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "viz-base" }, svg);
  }

  /** spark(values, color) → inline SVG string (no axes; context only). */
  function spark(values, color = "var(--series-1)", w = 120, h = 32) {
    const v = values.filter(x => x !== null && isFinite(x));
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), n = values.length;
    let d = "", st = false;
    values.forEach((x, i) => { if (x === null || !isFinite(x)) { st = false; return; } d += (st ? "L" : "M") + (i / (n - 1) * (w - 4) + 2).toFixed(1) + "," + (h - 3 - (x - lo) / (hi - lo || 1) * (h - 6)).toFixed(1); st = true; });
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  window.Charts = { line, columns, spark };
})();
