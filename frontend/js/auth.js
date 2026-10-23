/* Firebase login. Loaded as an ES module on every page; exposes window.NevaAuth and fires
   a "neva-auth" event on document whenever the signed-in user changes. */
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth, onAuthStateChanged, signInWithRedirect, getRedirectResult, GoogleAuthProvider,
  GithubAuthProvider, signInWithEmailAndPassword, createUserWithEmailAndPassword, sendPasswordResetEmail,
  signOut, updateProfile, setPersistence, browserLocalPersistence,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";

const state = { user: null, ready: false, enabled: false, error: null };
let auth = null;
let resolveReady;
const ready = new Promise(r => (resolveReady = r));

const emit = () => document.dispatchEvent(new CustomEvent("neva-auth", { detail: { user: state.user } }));

function pretty(e) {
  const code = e?.code || "";
  const map = {
    "auth/redirect-cancelled-by-user": "Sign-in was cancelled.",
    "auth/redirect-operation-pending": "A sign-in is already in progress.",
    "auth/unauthorized-domain": `This domain (${location.hostname}) is not authorised in Firebase → Authentication → Settings → Authorized domains.`,
    "auth/operation-not-allowed": "This sign-in method is not enabled in the Firebase console (Authentication → Sign-in method).",
    "auth/invalid-credential": "Wrong email or password.",
    "auth/invalid-login-credentials": "Wrong email or password.",
    "auth/wrong-password": "Wrong email or password.",
    "auth/user-not-found": "No account with that email.",
    "auth/email-already-in-use": "An account with that email already exists. Sign in instead.",
    "auth/weak-password": "Password must be at least 6 characters.",
    "auth/invalid-email": "That email address doesn't look right.",
    "auth/too-many-requests": "Too many attempts. Try again in a few minutes.",
    "auth/network-request-failed": "Network error while contacting Firebase.",
    "auth/account-exists-with-different-credential": "This email is already linked to a different sign-in method.",
  };
  return map[code] || e?.message || String(e);
}

async function init() {
  try {
    const r = await fetch("/api/auth/config");
    const cfg = await r.json();
    state.enabled = !!cfg.enabled;
    if (!cfg.firebase?.apiKey) throw new Error("Firebase web config missing");
    const app = initializeApp(cfg.firebase);
    auth = getAuth(app);
    await setPersistence(auth, browserLocalPersistence).catch(() => {});
    // resolve "ready" only after a pending provider redirect (if any) has been processed, so callers
    // never see a false "signed out" while the result is still being exchanged
    const redirectDone = getRedirectResult(auth).then(r => {
      let pending = false; try { pending = sessionStorage.getItem("neva-redirect") === "1"; sessionStorage.removeItem("neva-redirect"); } catch {}
      if (pending && !r?.user && !auth.currentUser) state.error = "Sign-in did not complete. Your browser may block third-party storage; try again, or sign in with email.";
    }).catch(e => { state.error = pretty(e); try { sessionStorage.removeItem("neva-redirect"); } catch {} });
    onAuthStateChanged(auth, u => {
      state.user = u ? { uid: u.uid, email: u.email, name: u.displayName, picture: u.photoURL } : null;
      redirectDone.then(() => { if (!state.ready) { state.ready = true; resolveReady(state.user); } emit(); });
    });
  } catch (e) {
    state.error = pretty(e); state.ready = true; resolveReady(null); emit();
  }
}

/** Full-page redirect to the provider (no popup). The page navigates away; on return, onAuthStateChanged
    fires with the user and getRedirectResult surfaces any error via state.error. */
async function oauth(provider) {
  try { try { sessionStorage.setItem("neva-redirect", "1"); } catch {} await signInWithRedirect(auth, provider); return { redirecting: true }; }
  catch (e) { throw new Error(pretty(e)); }
}

window.NevaAuth = {
  state, ready,
  get user() { return state.user; },
  get enabled() { return state.enabled; },
  onChange(fn) { document.addEventListener("neva-auth", e => fn(e.detail.user)); if (state.ready) fn(state.user); },
  async idToken(force = false) { return auth?.currentUser ? auth.currentUser.getIdToken(force) : null; },
  /** Headers for calls to logged-in endpoints (dashboard, /api/auth/me). */
  async headers(extra = {}) {
    const t = await this.idToken();
    return t ? { ...extra, Authorization: "Bearer " + t } : extra;
  },
  signInWithGoogle() { const p = new GoogleAuthProvider(); p.setCustomParameters({ prompt: "select_account" }); return oauth(p); },
  signInWithGithub() { return oauth(new GithubAuthProvider()); },
  async signInWithEmail(email, password) {
    try { return (await signInWithEmailAndPassword(auth, email, password)).user; } catch (e) { throw new Error(pretty(e)); }
  },
  async createAccount(email, password, name) {
    try {
      const cred = await createUserWithEmailAndPassword(auth, email, password);
      if (name) await updateProfile(cred.user, { displayName: name }).catch(() => {});
      return cred.user;
    } catch (e) { throw new Error(pretty(e)); }
  },
  async resetPassword(email) { try { await sendPasswordResetEmail(auth, email); } catch (e) { throw new Error(pretty(e)); } },
  async signOut() { await signOut(auth); },
  /** Redirect to /login unless signed in. Resolves with the user when signed in. */
  async require() {
    const u = await ready;
    if (!u) location.replace("/login?next=" + encodeURIComponent(location.pathname + location.hash));
    return u;
  },
  /** Confirms the login with the backend (creates the local user on first sign-in). */
  async me() {
    const r = await fetch("/api/auth/me", { headers: await this.headers() });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  },
};

// Nav slot rendered by app.js: "Sign in" or the account menu.
function renderNav(user) {
  const slot = document.getElementById("navAuth");
  if (!slot) return;
  const t = window.Neva?.t || ((zh, en) => en);
  const next = encodeURIComponent(location.pathname + location.hash);
  if (!user) {
    slot.innerHTML = `<a href="/login?next=${next}" class="btn">${t("登录", "Sign in")}</a>`;
    return;
  }
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const label = esc(user.name || user.email || "Account");
  const avatar = user.picture ? `<img src="${esc(user.picture)}" alt="" referrerpolicy="no-referrer">` : `<span>${label.slice(0, 1).toUpperCase()}</span>`;
  const markets = (window.Neva?.markets || []).map(m => `<a href="/${m.key}#paper">${t(m.zh, m.en)} · ${t("模拟盘", "paper")}</a>`).join("");
  slot.innerHTML = `<div class="account"><button class="avatar" id="acctBtn" title="${label}">${avatar}</button>
    <div class="menu" id="acctMenu"><div class="who"><strong>${label}</strong><span class="dim">${esc(user.email || "")}</span></div>
    ${markets}<button id="signOutBtn">${t("退出登录", "Sign out")}</button></div></div>`;
  const menu = slot.querySelector("#acctMenu");
  slot.querySelector("#acctBtn").onclick = e => { e.stopPropagation(); menu.classList.toggle("open"); };
  document.addEventListener("click", () => menu.classList.remove("open"));
  slot.querySelector("#signOutBtn").onclick = async () => { await window.NevaAuth.signOut(); location.reload(); };
}
document.addEventListener("neva-auth", e => renderNav(e.detail.user));

init();
