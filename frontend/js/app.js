/* Shared shell for the hub and every market page: language, nav, footer, fetch helpers, toast, dialog. */
(function () {
  const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
  const lang = store.get("neva-lang") === "en" ? "en" : "zh";
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.documentElement.dataset.lang = lang;
  const t = (zh, en) => (lang === "en" ? en ?? zh : zh);

  const path = location.pathname.replace(/\/$/, "") || "/";
  const MARKETS = [
    { key: "coal", zh: "煤炭", en: "Coal", group: t("期货", "Futures") },
    { key: "coffee", zh: "咖啡", en: "Coffee", group: t("期货", "Futures") },
  ];
  const SOON = [{ zh: "A 股", en: "China A-shares" }, { zh: "美股", en: "US stocks" }];
  const here = MARKETS.find(m => path === "/" + m.key);
  const chev = `<svg viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2 3.5l3 3 3-3"/></svg>`;
  const a = (h, label) => `<a href="${h}" class="${path === h ? "active" : ""}">${label}</a>`;
  const links = `
    <div class="dd"><button type="button">${t("市场", "Markets")} ${chev}</button><div class="menu">
      <span class="k">${t("期货", "Futures")}</span>${MARKETS.map(m => `<a href="/${m.key}">${t(m.zh, m.en)}</a>`).join("")}
      <span class="k">${t("即将上线", "Coming next")}</span>${SOON.map(s => `<span class="soon">${t(s.zh, s.en)}</span>`).join("")}</div></div>
    ${MARKETS.map(m => a("/" + m.key, t(m.zh, m.en))).join("")}${a("/#how", t("怎么做的", "How it works"))}`;
  const nav = document.getElementById("nav");
  if (nav) nav.innerHTML = `
    <div class="wrap">
      <a href="/" class="brand"><img class="logo" src="/static/logo.svg" alt="" width="20" height="20">nevabase</a>${here ? `<a href="/${here.key}" class="brand-sub">${t(here.zh, here.en)}</a>` : ""}
      <div class="nav-links" id="navlinks">${links}</div>
      <div class="spacer"></div>
      <div class="right">
        <button class="btn ghost lang-switch" id="langSwitch" type="button" title="${t("Switch to English", "切换到中文")}">${lang === "zh" ? "EN" : "中"}</button>
        <span class="nav-auth" id="navAuth"><a href="/login" class="btn">${t("登录", "Sign in")}</a></span>
        <button class="btn ghost icon-btn nav-toggle" id="navToggle" aria-label="menu">☰</button>
      </div>
    </div>`;
  document.getElementById("langSwitch")?.addEventListener("click", () => { store.set("neva-lang", lang === "zh" ? "en" : "zh"); location.reload(); });
  document.getElementById("navToggle")?.addEventListener("click", () => document.getElementById("navlinks").classList.toggle("open"));
  const dds = [...document.querySelectorAll(".nav-links .dd")];
  const closeAll = except => dds.forEach(d => { if (d !== except) d.classList.remove("open"); });
  dds.forEach(d => d.querySelector("button").addEventListener("click", e => { e.stopPropagation(); closeAll(d); d.classList.toggle("open"); }));
  document.addEventListener("click", () => closeAll());
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeAll(); });
  if (!document.querySelector('script[src^="/static/js/auth.js"]')) {
    const v = (document.currentScript?.src.match(/[?&]v=(\w+)/) || [])[1]; const s = document.createElement("script"); s.type = "module"; s.src = "/static/js/auth.js" + (v ? `?v=${v}` : ""); document.head.appendChild(s);
  }

  const footer = document.getElementById("footer");
  if (footer) footer.innerHTML = `<div class="wrap">
    <div class="co">nevabase</div>
    <p class="big">${t("把数据之间的逻辑，变成复盘、回测和模拟盘。", "The logic between market data, turned into reviews, backtests and paper trading.")}</p>
    <div class="cols">
      <div><h4>${t("市场", "Markets")}</h4>${MARKETS.map(m => `<a href="/${m.key}">${t(m.zh, m.en)}</a>`).join("")}${SOON.map(s => `<span class="dim">${t(s.zh, s.en)} · ${t("即将上线", "soon")}</span>`).join("")}</div>
      <div><h4>${t("功能", "Product")}</h4><a href="/coal#graph">${t("逻辑图谱", "Logic graph")}</a><a href="/coal#review">${t("复盘", "Daily review")}</a><a href="/coal#backtest">${t("回测", "Backtest")}</a><a href="/coal#paper">${t("虚拟交易", "Paper trading")}</a></div>
      <div><h4>${t("关于", "Company")}</h4><a href="/#how">${t("怎么做的", "How it works")}</a><a href="/privacy">${t("隐私政策", "Privacy policy")}</a><a href="/terms">${t("服务条款", "Terms of service")}</a><a href="mailto:hello@nevabase.com">${t("联系我们", "Contact")}</a></div>
    </div>
    <p class="disclaimer">${t("nevabase 展示的是历史数据和统计检验结果，不构成投资建议。虚拟交易不涉及真实资金。", "nevabase shows historical data and statistical tests, not investment advice. Paper trading involves no real money.")}</p>
    <div class="bottom"><div><a href="/privacy">${t("隐私", "Privacy")}</a><a href="/terms">${t("条款", "Terms")}</a></div><div>© ${new Date().getFullYear()} nevabase</div></div></div>`;

  const req = async (method, url, body, headers = {}) => {
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json", ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || data.detail?.error || `HTTP ${r.status}`); e.status = r.status; e.code = data.code; throw e; }
    return data;
  };

  window.Neva = {
    lang, t, store,
    markets: MARKETS,
    get: url => req("GET", url),
    post: (url, body) => req("POST", url, body),
    /** Same as get/post but with the Firebase login token. */
    async authed(method, url, body) {
      const headers = window.NevaAuth ? await window.NevaAuth.headers() : {};
      return req(method, url, body, headers);
    },
    esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); },
    /** Number formatting: fixed decimals, thousands separators, compact above 10k when asked. */
    num(v, d = 2, compact = false) {
      if (v === null || v === undefined || Number.isNaN(v)) return "—";
      if (compact && Math.abs(v) >= 1e4) return new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en", { notation: "compact", maximumFractionDigits: 1 }).format(v);
      return Number(v).toLocaleString(lang === "zh" ? "zh-CN" : "en", { minimumFractionDigits: d, maximumFractionDigits: d });
    },
    pct(v, d = 2, signed = true) {
      if (v === null || v === undefined || Number.isNaN(v)) return "—";
      const s = (v * 100).toFixed(d) + "%";
      return signed && v > 0 ? "+" + s : s;
    },
    /** CSS class for a move: Chinese convention (red up) in zh, green up in en. */
    dir(v) { return v === null || v === undefined || Math.abs(v) < 1e-12 ? "flat" : v > 0 ? "up" : "down"; },
    toast(msg) {
      let el = document.querySelector(".toast");
      if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
      el.textContent = msg; el.classList.add("show"); clearTimeout(el._h); el._h = setTimeout(() => el.classList.remove("show"), 2600);
    },
    // Styled replacement for alert / confirm / prompt. Resolves to true/false (confirm), the string or null (prompt).
    dialog({ title = "", body = "", ok = t("确定", "OK"), cancel = t("取消", "Cancel"), danger = false, input = null, placeholder = "" } = {}) {
      return new Promise(resolve => {
        document.querySelector(".dlg-back")?.remove();
        const back = document.createElement("div"); back.className = "dlg-back";
        back.innerHTML = `<div class="dlg" role="dialog" aria-modal="true">
          ${title ? `<div class="dlg-title">${this.esc(title)}</div>` : ""}
          ${body ? `<div class="dlg-body">${this.esc(body)}</div>` : ""}
          ${input !== null ? `<input class="input dlg-input" value="${this.esc(input)}" placeholder="${this.esc(placeholder)}">` : ""}
          <div class="dlg-actions">
            ${cancel ? `<button class="btn dlg-cancel" type="button">${this.esc(cancel)}</button>` : ""}
            <button class="btn ${danger ? "danger" : "primary"} dlg-ok" type="button">${this.esc(ok)}</button>
          </div></div>`;
        const inp = back.querySelector(".dlg-input");
        const close = v => { back.classList.remove("show"); document.removeEventListener("keydown", onKey); setTimeout(() => back.remove(), 160); resolve(v); };
        const done = () => close(inp ? inp.value : true);
        const onKey = e => { if (e.key === "Escape") { e.preventDefault(); close(inp ? null : false); } else if (e.key === "Enter" && (inp || document.activeElement === back.querySelector(".dlg-ok"))) { e.preventDefault(); done(); } };
        back.querySelector(".dlg-ok").onclick = done;
        back.querySelector(".dlg-cancel")?.addEventListener("click", () => close(inp ? null : false));
        back.addEventListener("mousedown", e => { if (e.target === back) close(inp ? null : false); });
        document.addEventListener("keydown", onKey);
        document.body.appendChild(back);
        requestAnimationFrame(() => { back.classList.add("show"); (inp || back.querySelector(".dlg-ok")).focus(); inp?.select(); });
      });
    },
    confirm(body, opts = {}) { return this.dialog({ body, ...opts }); },
    prompt(title, value = "", opts = {}) { return this.dialog({ title, input: value, ...opts }); },
  };
})();
