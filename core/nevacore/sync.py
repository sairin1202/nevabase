"""Bring one market's stored data up to date. Every step is an idempotent upsert, safe to rerun at any time."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from . import sources
from .spec import Market
from .store import Store, now

log = logging.getLogger("nevacore.sync")


def _sync_cn_future(m: Market, st: Store, inst) -> str:
    src = inst.source
    start_year = int(m.start[:4]) - 1
    codes = sources.contract_codes(src["symbol"], src["months"], start_year)
    done = set(json.loads(st.get_state(f"done:{inst.id}", "[]")))
    today = date.today()
    fetched = 0
    for code in codes:
        exp = sources.contract_expiry(code)
        if code in done or exp > today + timedelta(days=470):  # finished, or not listed yet
            continue
        rows = sources.fetch_contract(code)
        if rows:
            st.upsert_contracts([(inst.id, code.lower(), *r) for r in rows])
            fetched += 1
        if exp < today - timedelta(days=20):  # expired: never changes again (empty ones are just unavailable)
            done.add(code)
    st.set_state(f"done:{inst.id}", json.dumps(sorted(done)))
    by_code: dict[str, list] = {}
    for r in st.query("SELECT contract,date,open,high,low,close,settle,volume,oi FROM contracts WHERE inst=? AND date>=? ORDER BY date",
                      (inst.id, m.start)):
        by_code.setdefault(r["contract"], []).append(tuple(r)[1:])
    chain = sources.main_chain(by_code)
    st.replace_bars(inst.id, chain)
    st.upsert_points(f"{inst.id}.carry", sources.carry(chain, by_code))
    return f"{fetched} contracts refreshed, {len(chain)} days"


def _sync_foreign(m: Market, st: Store, inst) -> str:
    rows = [r for r in sources.fetch_foreign(inst.source["symbol"], inst.source.get("yahoo")) if r[0] >= m.start]
    st.replace_bars(inst.id, rows)
    return f"{len(rows)} days"


def _sync_basis(m: Market, st: Store, variables: list[str]) -> str:
    """Spot/basis is fetched one trading day per request upstream, so history is backfilled in chunks."""
    key = "basis:" + ",".join(variables)
    last = st.get_state(key)
    start = date.fromisoformat(last) - timedelta(days=3) if last else date.fromisoformat(m.start)
    end = date.today()
    n = 0
    while start <= end:
        chunk_end = min(start + timedelta(days=45), end)
        try:
            data = sources.fetch_basis(variables, start, chunk_end)
        except Exception as e:
            log.warning("%s basis %s..%s: %s", m.key, start, chunk_end, e)
            break
        for sid, rows in data.items():
            n += st.upsert_points(sid, rows)
        st.set_state(key, chunk_end.isoformat())
        start = chunk_end + timedelta(days=1)
    return f"{n} points"


def _sync_series(m: Market, st: Store, s) -> str:
    src = s.source
    last = st.one("SELECT MAX(date) AS d FROM points WHERE series=?", (s.id,))["d"]
    first = date.fromisoformat(src["since"]) if src.get("since") else date.fromisoformat(m.start) - timedelta(days=400)
    start = date.fromisoformat(last) - timedelta(days=10) if last else first
    if src["kind"] == "fx":
        rows = sources.fetch_fx(src["base"], src["quote"], start)
    elif src["kind"] == "weather":
        rows = []
        if start < date.today() - timedelta(days=7):
            # the archive takes at most a few years per request comfortably; walk it in 3-year steps
            s0 = start
            while s0 < date.today() - timedelta(days=6):
                s1 = min(s0 + timedelta(days=3 * 365), date.today() - timedelta(days=6))
                rows += sources.fetch_weather(src["lat"], src["lon"], src["var"], s0, s1)
                s0 = s1 + timedelta(days=1)
        recent, forecast = sources.fetch_weather_recent(src["lat"], src["lon"], src["var"])
        rows += recent
        st.set_state(f"forecast:{s.id}", json.dumps(forecast))
    else:
        return "unknown source"
    return f"{st.upsert_points(s.id, rows)} points"


def sync_market(m: Market, st: Store) -> dict:
    """Fetch everything the market spec lists. Returns {step: result} and records it in sync_state."""
    report: dict[str, str] = {}
    for inst in m.instruments:
        kind = inst.source["kind"]
        try:
            report[inst.id] = (_sync_cn_future if kind == "cn_future" else _sync_foreign)(m, st, inst)
        except Exception as e:
            log.exception("%s %s", m.key, inst.id)
            report[inst.id] = f"error: {e}"
    basis_vars = sorted({s.source["var"] for s in m.series if s.source and s.source["kind"] == "cn_basis"})
    if basis_vars:
        report["basis"] = _sync_basis(m, st, basis_vars)
    for s in m.series:
        if s.source and s.source["kind"] in ("fx", "weather"):
            try:
                report[s.id] = _sync_series(m, st, s)
            except Exception as e:
                log.warning("%s %s: %s", m.key, s.id, e)
                report[s.id] = f"error: {e}"
    st.set_state("last_sync", json.dumps({"at": now(), "report": report}, ensure_ascii=False))
    log.info("%s synced: %s", m.key, report)
    return report
