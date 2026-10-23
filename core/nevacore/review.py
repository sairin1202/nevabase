"""复盘: what happened on one trading day, read against the logic pack. Every number is computed here."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import analytics as A
from . import pack as P
from .spec import Market
from .store import Store

NEUTRAL = 0.15   # |signal| below this is "no view"


def _pct(a, b):
    return None if a is None or b is None or not b else round(a / b - 1, 5)


def _cum(ret: pd.Series, end: int, n: int) -> float | None:
    if end - n + 1 < 0:
        return None
    return round(float(np.prod(1 + ret.iloc[end - n + 1:end + 1].values) - 1), 5)


def review(m: Market, st: Store, day: str | None = None) -> dict:
    fr = A.frame(m, st)
    if not len(fr.cal):
        return {"error": "还没有数据，第一次同步完成后再来"}
    pk = P.current(m)
    rels = P.relations_of(pk, m)
    used = {r["id"] for r in (pk or {}).get("relations", []) if r.get("used")}
    weights = P.weights_of(pk)
    at = fr.cal[-1] if not day else fr.cal[fr.cal <= pd.Timestamp(day)][-1] if (fr.cal <= pd.Timestamp(day)).any() else fr.cal[0]
    i = fr.cal.get_loc(at)
    prev = fr.cal[i - 1] if i > 0 else None

    # instruments: price, contract, moves
    insts = []
    for inst in m.instruments:
        b = fr.bars[inst.id]
        row = b.loc[at] if len(b) and at in b.index else None
        ret = fr.ret[inst.id]
        insts.append({"id": inst.id, "name": inst.name, "nameEn": inst.name_en, "unit": inst.unit,
                      "close": None if row is None else row["close"], "contract": None if row is None else row["contract"],
                      "volume": None if row is None else row["volume"], "oi": None if row is None else row["oi"],
                      "d1": _cum(ret, i, 1), "d5": _cum(ret, i, 5), "d20": _cum(ret, i, 20)})

    # relations: today's reading, the view it implies and whether the target agreed
    rows = []
    for r in rels:
        s = A.latest_state(fr, r, at)
        sig = s.get("signal") or 0.0
        realized = _cum(fr.ret[r.target], i, 1)
        h_ret = _cum(fr.ret[r.target], i, min(r.horizon, i + 1))
        sig_then = float(fr.signal(r).iloc[i - r.horizon]) if i - r.horizon >= 0 else 0.0
        if abs(sig) < NEUTRAL:
            view = "neutral"
        else:
            view = "up" if sig > 0 else "down"
        # did the view it held `horizon` days ago come true over those days?
        if abs(sig_then) < NEUTRAL or h_ret is None:
            check = "none"
        else:
            check = "right" if np.sign(sig_then) == np.sign(h_ret) else "wrong"
        rows.append({"id": r.id, "name": r.name, "nameEn": r.name_en, "driver": r.driver, "target": r.target, "kind": r.kind,
                     "used": r.id in used, "state": s, "view": view, "targetD1": realized,
                     "horizon": r.horizon, "viewThen": round(sig_then, 3), "targetH": h_ret, "check": check})

    # composite: yesterday's view (the position held into today) vs today's move; today's view for tomorrow
    comp = []
    pack_rels = P.relations_of(pk, m, used_only=True)
    for inst in m.instruments:
        if not any(r.target == inst.id for r in pack_rels):
            continue
        c = A.composite(fr, pack_rels, inst.id, weights)
        ret = fr.ret[inst.id]
        held = c.shift(1)
        last20 = [(float(held.iloc[k]), float(ret.iloc[k])) for k in range(max(1, i - 19), i + 1) if abs(held.iloc[k]) >= NEUTRAL]
        comp.append({"target": inst.id, "yesterday": None if prev is None else round(float(c.loc[prev]), 3),
                     "today": round(float(c.loc[at]), 3), "realized": _cum(ret, i, 1),
                     "right": None if prev is None or abs(c.loc[prev]) < NEUTRAL else bool(np.sign(c.loc[prev]) == np.sign(ret.iloc[i])),
                     "hit20": None if not last20 else round(sum(1 for p, x in last20 if np.sign(p) == np.sign(x)) / len(last20), 3),
                     "n20": len(last20)})

    # unusual moves across every series: today's change against its own past year
    movers = []
    for sid, meta in fr.series_meta.items():
        x = fr.aligned.get(sid)
        if x is None:
            continue
        d = x.diff()
        sd = d.rolling(A.ZWIN, min_periods=A.ZMIN).std()
        if pd.isna(d.loc[at]) or pd.isna(sd.loc[at]) or not sd.loc[at]:
            continue
        z = float(d.loc[at] / sd.loc[at])
        if abs(z) >= 2:
            movers.append({"id": sid, "name": meta.name, "nameEn": meta.name_en, "value": round(float(x.loc[at]), 4),
                           "change": round(float(d.loc[at]), 4), "z": round(z, 2), "unit": meta.unit})
    movers.sort(key=lambda r: -abs(r["z"]))

    forecasts = []
    for s in m.series:
        raw = st.get_state(f"forecast:{s.id}")
        if raw and at == fr.cal[-1]:
            pts = json.loads(raw)
            if pts:
                vals = [v for _, v in pts]
                forecasts.append({"id": s.id, "name": s.name, "nameEn": s.name_en, "unit": s.unit, "points": pts,
                                  "min": min(vals), "max": max(vals), "sum": round(sum(vals), 1)})

    saved = st.one("SELECT narrative, narrative_en, pack FROM reviews WHERE date=?", (at.date().isoformat(),))
    return {"date": at.date().isoformat(), "prev": None if prev is None else prev.date().isoformat(),
            "isLatest": bool(at == fr.cal[-1]), "pack": (pk or {}).get("version"), "instruments": insts,
            "relations": rows, "composite": comp, "movers": movers[:8], "forecasts": forecasts,
            "narrative": saved["narrative"] if saved else None, "narrativeEn": saved["narrative_en"] if saved else None}


def dates(m: Market, st: Store, n: int = 120) -> list[str]:
    fr = A.frame(m, st)
    return [d.date().isoformat() for d in fr.cal[-n:][::-1]]
