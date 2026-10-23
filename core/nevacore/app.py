"""`create_market(key)`: the online service of one market — page, read APIs, backtests, paper trading, sync loop.

Every route lives under /<key> (nevabase.com/coal, nevabase.com/coffee), so Caddy can send each path to its own
process the way nevatown gives every world its own service.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics as A
from . import auth
from . import pack as P
from . import paper, registry, review as R, sources
from .config import ADMIN_TOKEN, FRONTEND_DIR, SYNC_ENABLED, SYNC_INTERVAL
from .spec import TRANSFORMS, Relation
from .store import now
from .sync import sync_market

log = logging.getLogger("nevacore.app")


class BacktestIn(BaseModel):
    target: str
    relations: list[str] | None = None          # ids from the pack; None = the pack's used relations
    custom: list[dict] | None = None            # edited relation definitions (same fields as Relation)
    start: str | None = None
    end: str | None = None
    costBps: float = Field(3.0, ge=0, le=100)
    threshold: float = Field(0.0, ge=0, le=1)
    discrete: bool = False
    longOnly: bool = False


class AccountIn(BaseModel):
    name: str = "模拟账户"
    mode: str = "manual"
    agentInst: str | None = None


class AccountPatch(BaseModel):
    name: str | None = None
    mode: str | None = None
    agentInst: str | None = None


class OrderIn(BaseModel):
    inst: str
    side: str
    lots: int
    contract: str | None = None


def _clean(v):
    """JSON-safe: NaN / inf → None, numpy scalars → Python."""
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if f != f or f in (float("inf"), float("-inf")) else f
    if isinstance(v, np.integer):
        return int(v)
    return v


def create_market(key: str) -> FastAPI:
    m = registry.load(key)
    st = registry.store(key)
    base = f"/{key}"

    def after_sync(report: dict | None = None) -> None:
        if P.current(m) is None:
            from .gen import seed_pack
            seed_pack(m, st)
        paper.run_agents(m, st)

    async def loop():
        while True:
            try:
                await asyncio.to_thread(sync_market, m, st)
                await asyncio.to_thread(after_sync)
            except Exception:
                log.exception("%s sync loop", key)
            await asyncio.sleep(SYNC_INTERVAL)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.get_running_loop().create_task(loop()) if SYNC_ENABLED else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title=f"nevabase {m.name_en}", lifespan=lifespan, docs_url=f"{base}/api/openapi",
                  redoc_url=None, openapi_url=f"{base}/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(paper.PaperError)
    async def paper_exc(_: Request, exc: paper.PaperError):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    api = APIRouter(prefix=f"{base}/api")

    def user(request: Request) -> auth.User:
        u = auth.current_user(request)
        with st.tx() as c:
            c.execute("INSERT INTO users (uid,email,name,created_at,last_seen) VALUES (?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET "
                      "email=excluded.email, name=excluded.name, last_seen=excluded.last_seen", (u.uid, u.email, u.name, now(), now()))
        return u

    def rel_payload(fr: A.Frame, pk: dict | None) -> list[dict]:
        rows = (pk or {}).get("relations") or [
            {**r.to_dict(), "evidence": A.evidence(fr, r), "comove": A.comove(fr, r), "used": False, "weight": 0} for r in m.relations]
        out = []
        for r in rows:
            rel = Relation(**{k: v for k, v in r.items() if k in Relation.__dataclass_fields__})
            out.append({**{k: v for k, v in r.items() if k != "evidence"},
                        "evidence": {k: v for k, v in r["evidence"].items() if k != "byYear"},
                        "state": A.latest_state(fr, rel)})
        return out

    @api.get("/market")
    def market_meta():
        fr = A.frame(m, st)
        pk = P.current(m)
        series = []
        for s in m.all_series():
            x = fr.aligned.get(s.id)
            xs = x.dropna() if x is not None else pd.Series(dtype=float)
            series.append({"id": s.id, "name": s.name, "nameEn": s.name_en, "unit": s.unit, "group": s.group,
                           "groupEn": s.group_en, "formula": s.formula, "calendar": s.calendar,
                           "latest": None if not len(xs) else float(xs.iloc[-1]),
                           "latestDate": None if not len(xs) else xs.index[-1].date().isoformat(),
                           "since": None if not len(xs) else xs.index[0].date().isoformat()})
        insts = [{"id": i.id, "name": i.name, "nameEn": i.name_en, "exchange": i.exchange, "currency": i.currency,
                  "unit": i.unit, "multiplier": i.multiplier, "margin": i.margin, "tick": i.tick, "feeRate": i.fee_rate,
                  "note": i.note, "noteEn": i.note_en,
                  "contract": (fr.bars[i.id]["contract"].iloc[-1] if len(fr.bars[i.id]) else None)} for i in m.instruments]
        return _clean({
            "key": m.key, "name": m.name, "nameEn": m.name_en, "tagline": m.tagline, "taglineEn": m.tagline_en,
            "currency": m.currency, "capital": m.capital, "main": m.main, "lastDate": fr.last_date,
            "firstDate": fr.cal[0].date().isoformat() if len(fr.cal) else None,
            "instruments": insts, "series": series,
            "nodes": [n.__dict__ for n in m.nodes], "relations": rel_payload(fr, pk),
            "pack": None if not pk else {k: pk.get(k) for k in ("version", "origin", "createdAt", "dataThrough", "split", "gate",
                                                                   "regression", "proposed", "rejected")},
            "sync": A.sync_stamp(st),
        })

    @api.get("/series")
    def series(ids: str, start: str | None = None, end: str | None = None):
        fr = A.frame(m, st)
        want = [i for i in ids.split(",") if i in fr.aligned.columns][:12]
        idx = fr.cal
        if start:
            idx = idx[idx >= pd.Timestamp(start)]
        if end:
            idx = idx[idx <= pd.Timestamp(end)]
        return _clean({"dates": [d.date().isoformat() for d in idx],
                       "series": {i: [None if pd.isna(v) else round(float(v), 4) for v in fr.aligned[i].reindex(idx).values] for i in want}})

    @api.get("/relation/{rid}")
    def relation(rid: str, years: int = 3):
        fr = A.frame(m, st)
        pk = P.current(m)
        rels = {r.id: r for r in P.relations_of(pk, m)}
        r = rels.get(rid)
        if not r:
            raise HTTPException(404, {"error": "没有这条关系"})
        z, fwd = fr.feature(r), fr.forward(r.target, r.horizon)
        ok = z.notna() & fwd.notna() & fr.in_season(r)
        buckets = []
        if ok.sum() >= 50:
            q = pd.qcut(z[ok].rank(method="first"), 5, labels=False)
            for b in range(5):
                sel = q == b
                buckets.append({"bucket": b + 1, "zMin": round(float(z[ok][sel].min()), 2), "zMax": round(float(z[ok][sel].max()), 2),
                                "avgFwd": round(float(fwd[ok][sel].mean()), 5), "n": int(sel.sum()),
                                "up": round(float((fwd[ok][sel] > 0).mean()), 3)})
        idx = fr.cal[fr.cal >= fr.cal[-1] - pd.DateOffset(years=years)] if len(fr.cal) else fr.cal
        meta = next((x for x in (pk or {}).get("relations", []) if x["id"] == rid), None)
        return _clean({
            "relation": r.to_dict(), "evidence": A.evidence(fr, r), "comove": A.comove(fr, r),
            "inSample": (meta or {}).get("inSample"), "outSample": (meta or {}).get("outSample"), "split": (pk or {}).get("split"),
            "used": bool((meta or {}).get("used")), "weight": (meta or {}).get("weight", 0),
            "state": A.latest_state(fr, r), "buckets": buckets,
            "chart": {"dates": [d.date().isoformat() for d in idx],
                      "driver": [None if pd.isna(v) else round(float(v), 4) for v in fr.aligned[r.driver].reindex(idx).values],
                      "target": [None if pd.isna(v) else round(float(v), 4) for v in fr.close[r.target].reindex(idx).values],
                      "feature": [None if pd.isna(v) else round(float(v), 3) for v in z.reindex(idx).values]},
        })

    @api.get("/review")
    def get_review(date: str | None = None):
        return _clean(R.review(m, st, date))

    @api.get("/review/dates")
    def review_dates():
        return {"dates": R.dates(m, st)}

    @api.post("/backtest")
    def run_backtest(body: BacktestIn):
        fr = A.frame(m, st)
        if not m.instrument(body.target):
            raise HTTPException(400, {"error": "没有这个品种"})
        pk = P.current(m)
        pool = {r.id: r for r in P.relations_of(pk, m)}
        if body.custom:
            rels = []
            for c in body.custom[:20]:
                try:
                    r = Relation(**{k: v for k, v in c.items() if k in Relation.__dataclass_fields__})
                except TypeError as e:
                    raise HTTPException(400, {"error": f"关系定义不对：{e}"})
                if r.driver not in fr.aligned.columns or r.transform not in TRANSFORMS:
                    raise HTTPException(400, {"error": f"关系 {r.id} 的 driver 或 transform 不对"})
                r.window, r.lag, r.horizon = max(1, min(int(r.window), 250)), max(0, min(int(r.lag), 20)), max(1, min(int(r.horizon), 60))
                rels.append(r)
            weights = None
        elif body.relations is not None:
            rels = [pool[i] for i in body.relations if i in pool]
            weights = None
        else:
            rels = P.relations_of(pk, m, used_only=True)
            weights = P.weights_of(pk)
        rels = [r for r in rels if r.target == body.target]
        if not rels:
            raise HTTPException(400, {"error": "这个品种没有选中的关系"})
        out = A.backtest(fr, rels, body.target, start=body.start, end=body.end, cost_bps=body.costBps, threshold=body.threshold,
                         discrete=body.discrete, long_only=body.longOnly, weights=weights, split=(pk or {}).get("split"))
        return _clean(out)

    @api.get("/packs")
    def packs():
        return {"packs": P.history(m)}

    @api.get("/quotes")
    def quotes():
        out = {}
        for inst in m.instruments:
            try:
                c = paper.main_contract(st, inst)
                out[inst.id] = {"contract": c, **paper.price_of(m, st, inst, c)}
            except paper.PaperError:
                pass
        return out

    @api.get("/summary")
    def summary():
        """Compact card for the hub homepage."""
        fr = A.frame(m, st)
        if not len(fr.cal):
            return {"key": m.key, "name": m.name, "nameEn": m.name_en, "ready": False}
        pk = P.current(m)
        rels = P.relations_of(pk, m, used_only=True)
        rows = (pk or {}).get("relations", [])
        insts = []
        for inst in m.instruments:
            b = fr.bars[inst.id]
            if not len(b):
                continue
            ret = fr.ret[inst.id]
            insts.append({"id": inst.id, "name": inst.name, "nameEn": inst.name_en, "close": float(b["close"].iloc[-1]),
                          "unit": inst.unit, "d1": float(ret.iloc[-1]), "d20": float(np.prod(1 + ret.iloc[-20:].values) - 1),
                          "view": round(float(A.composite(fr, rels, inst.id, P.weights_of(pk)).iloc[-1]), 3) if any(r.target == inst.id for r in rels) else None,
                          "spark": [round(float(v), 4) for v in fr.close[inst.id].iloc[-60:].values]})
        return _clean({"key": m.key, "name": m.name, "nameEn": m.name_en, "tagline": m.tagline, "taglineEn": m.tagline_en,
                       "ready": True, "lastDate": fr.last_date, "instruments": insts,
                       "relations": {"total": len(rows), "used": sum(1 for r in rows if r.get("used")),
                                     "comove": sum(1 for r in rows if (r.get("comove") or {}).get("verdict") == "holds")},
                       "pack": (pk or {}).get("version")})

    # ---- paper trading ----------------------------------------------------------------------------------
    @api.get("/paper")
    def paper_list(u: auth.User = Depends(user)):
        return _clean({"accounts": paper.accounts(m, st, u.uid)})

    @api.post("/paper")
    def paper_create(body: AccountIn, u: auth.User = Depends(user)):
        return _clean(paper.create_account(m, st, u.uid, body.name, body.mode, body.agentInst))

    @api.get("/paper/{aid}")
    def paper_get(aid: str, u: auth.User = Depends(user)):
        return _clean(paper.account(m, st, u.uid, aid))

    @api.patch("/paper/{aid}")
    def paper_patch(aid: str, body: AccountPatch, u: auth.User = Depends(user)):
        acc = paper.update_account(m, st, u.uid, aid, body.name, body.mode, body.agentInst)
        if body.mode == "agent":
            paper.run_agents(m, st)
            acc = paper.account(m, st, u.uid, aid)
        return _clean(acc)

    @api.delete("/paper/{aid}")
    def paper_delete(aid: str, u: auth.User = Depends(user)):
        paper.delete_account(st, u.uid, aid)
        return {"ok": True}

    @api.post("/paper/{aid}/orders")
    def paper_order(aid: str, body: OrderIn, u: auth.User = Depends(user)):
        return _clean(paper.order(m, st, u.uid, aid, body.inst, body.side, body.lots, body.contract))

    # ---- admin --------------------------------------------------------------------------------------------
    @api.post("/admin/sync")
    async def admin_sync(request: Request):
        tok = request.headers.get("x-admin-token", "")
        if ADMIN_TOKEN and tok != ADMIN_TOKEN:
            raise HTTPException(403, {"error": "admin token required"})
        rep = await asyncio.to_thread(sync_market, m, st)
        await asyncio.to_thread(after_sync)
        return rep

    app.include_router(api)

    # ---- page ---------------------------------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")   # only used when run without the hub
    asset_re = re.compile(r"(/static/(?:css|js)/[\w./-]+)")

    @app.api_route(base, methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route(base + "/", methods=["GET", "HEAD"], include_in_schema=False)
    def page():
        version = int(max(p.stat().st_mtime for p in FRONTEND_DIR.rglob("*") if p.is_file()))
        html = (FRONTEND_DIR / "market.html").read_text("utf-8")
        boot = json.dumps({"key": m.key, "name": m.name, "nameEn": m.name_en, "tagline": m.tagline, "taglineEn": m.tagline_en},
                          ensure_ascii=False)
        html = html.replace("{{BOOT}}", boot).replace("{{NAME}}", m.name).replace("{{NAME_EN}}", m.name_en) \
                   .replace("{{TAGLINE}}", m.tagline)
        html = asset_re.sub(rf"\1?v={version}", html)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    return app
