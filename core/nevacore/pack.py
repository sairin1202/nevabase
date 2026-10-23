"""The logic pack: the relations a market currently trusts, with the evidence and regression test behind them.

Packs live in DATA_DIR/<market>/packs/<version>.json; `current` names the published one. Like nevatown's
content packs, a pack is written offline (gen.py) and the running service picks a new one up on its own.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import analytics as A
from .registry import data_dir
from .spec import Market, Relation

OOS_YEARS = 2          # the last two years are held out: relations are chosen before, judged after
TOLERANCE = 0.10       # a new pack may not lose more than this much out-of-sample Sharpe on any target
WEIGHT = {"holds": 1.0, "weak": 0.5}


def pack_dir(key: str) -> Path:
    d = data_dir(key) / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def current(m: Market) -> dict | None:
    d = pack_dir(m.key)
    ptr = d / "current"
    if not ptr.exists():
        return None
    p = d / f"{ptr.read_text().strip()}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def relations_of(pack: dict | None, m: Market, used_only: bool = False) -> list[Relation]:
    """Relations of a pack (falls back to the spec's seeds when nothing is published yet)."""
    if not pack:
        return [] if used_only else list(m.relations)
    fields = Relation.__dataclass_fields__
    out = []
    for r in pack["relations"]:
        if used_only and not r.get("used"):
            continue
        out.append(Relation(**{k: v for k, v in r.items() if k in fields}))
    return out


def weights_of(pack: dict | None) -> dict[str, float]:
    return {r["id"]: r.get("weight", 0) for r in (pack or {}).get("relations", []) if r.get("used")}


def cutoff(fr: A.Frame) -> str:
    last = fr.cal[-1] if len(fr.cal) else pd.Timestamp.today()
    return (last - pd.DateOffset(years=OOS_YEARS)).date().isoformat()


def assess(fr: A.Frame, rels: list[Relation], split: str) -> list[dict]:
    """Evidence on the full history, before the split (selection) and after it (honest check)."""
    out = []
    for r in rels:
        full = A.evidence(fr, r)
        ins = A.evidence(fr, r, end=split)
        oos = A.evidence(fr, r, start=split)
        w = WEIGHT.get(ins["verdict"], 0.0)
        out.append({**r.to_dict(), "evidence": full, "inSample": _brief(ins), "outSample": _brief(oos),
                    "comove": A.comove(fr, r), "used": w > 0, "weight": w})
    return out


def _brief(e: dict) -> dict:
    return {k: e.get(k) for k in ("n", "ic", "t", "hit", "active", "avgActive", "verdict")}


def regression(m: Market, fr: A.Frame, assessed: list[dict], split: str) -> dict:
    """Backtest the pack's composite on every target, reporting in-sample and out-of-sample."""
    rels = [Relation(**{k: v for k, v in r.items() if k in Relation.__dataclass_fields__}) for r in assessed if r["used"]]
    weights = {r["id"]: r["weight"] for r in assessed if r["used"]}
    out = {}
    for inst in m.instruments:
        if not any(r.target == inst.id for r in rels):
            out[inst.id] = {"relations": [], "inSample": None, "outSample": None}
            continue
        bt = A.backtest(fr, rels, inst.id, weights=weights, split=split)
        out[inst.id] = {"relations": bt["relations"], "inSample": bt.get("inSample"), "outSample": bt.get("outSample"),
                        "full": bt["metrics"], "benchmark": bt["benchmarkMetrics"]}
    return out


def gate(new_reg: dict, old_reg: dict | None) -> tuple[bool, list[str]]:
    """Publish only if no target loses more than TOLERANCE out-of-sample Sharpe against the current pack."""
    if not old_reg:
        return True, ["第一版逻辑包"]
    reasons, ok = [], True
    for inst, new in new_reg.items():
        old = old_reg.get(inst) or {}
        ns = ((new.get("outSample") or {}).get("sharpe")) or 0.0
        os_ = ((old.get("outSample") or {}).get("sharpe")) or 0.0
        if ns < os_ - TOLERANCE:
            ok = False
            reasons.append(f"{inst} 样本外 Sharpe {os_:.2f} → {ns:.2f}，变差超过 {TOLERANCE}")
        else:
            reasons.append(f"{inst} 样本外 Sharpe {os_:.2f} → {ns:.2f}")
    return ok, reasons


def build(m: Market, fr: A.Frame, rels: list[Relation], origin: str, extra: dict | None = None) -> dict:
    split = cutoff(fr)
    assessed = assess(fr, rels, split)
    version = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return {"version": version, "market": m.key, "origin": origin, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataThrough": fr.last_date, "split": split, "relations": assessed,
            "regression": regression(m, fr, assessed, split), **(extra or {})}


def publish(m: Market, pack: dict) -> str:
    d = pack_dir(m.key)
    (d / f"{pack['version']}.json").write_text(json.dumps(pack, ensure_ascii=False, indent=1), "utf-8")
    tmp = d / "current.tmp"
    tmp.write_text(pack["version"])
    tmp.replace(d / "current")
    return pack["version"]


def history(m: Market) -> list[dict]:
    d = pack_dir(m.key)
    out = []
    for p in sorted(d.glob("*.json"), reverse=True)[:30]:
        try:
            j = json.loads(p.read_text("utf-8"))
        except ValueError:
            continue
        out.append({"version": j["version"], "origin": j.get("origin"), "createdAt": j.get("createdAt"),
                    "used": sum(1 for r in j["relations"] if r.get("used")), "total": len(j["relations"]),
                    "gate": j.get("gate"), "published": j.get("published", True)})
    return out
