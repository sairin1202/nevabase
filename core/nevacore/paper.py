"""虚拟交易: paper futures accounts per user per market.

Market orders fill at the Sina realtime price of the contract (falling back to the last stored close),
plus one tick of slippage and the instrument's commission. Positions are per contract, so a held contract
keeps its own price after the main contract rolls. An account in `agent` mode is traded by the logic pack:
after each new close it moves to the composite view's target exposure (1.0 = equity's worth of notional).
Every trade records who placed it: `human` or `agent`.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone

import pandas as pd

from . import analytics as A
from . import pack as P
from . import sources
from .spec import Instrument, Market
from .store import Store, now

MAX_LEVERAGE = 3.0      # notional / equity cap for manual orders
_quote_cache: dict[str, tuple[float, dict]] = {}


class PaperError(Exception):
    pass


def _quote_code(inst: Instrument, contract: str) -> str:
    return f"nf_{contract.upper()}" if inst.quote == "nf_" else inst.quote


def price_of(m: Market, st: Store, inst: Instrument, contract: str) -> dict:
    """{"price", "source": "realtime"|"close", "time"} for one contract."""
    code = _quote_code(inst, contract)
    t = datetime.now().timestamp()
    hit = _quote_cache.get(code)
    if not hit or t - hit[0] > 20:
        q = sources.quotes([code]).get(code)
        _quote_cache[code] = (t, q or {})
        hit = _quote_cache[code]
    q = hit[1]
    if q.get("price"):
        return {"price": q["price"], "source": "realtime", "time": f"{q.get('date', '')} {q.get('time', '')}".strip()}
    if inst.source["kind"] == "cn_future":
        r = st.one("SELECT date, close FROM contracts WHERE contract=? ORDER BY date DESC LIMIT 1", (contract,))
    else:
        r = st.one("SELECT date, close FROM bars WHERE inst=? ORDER BY date DESC LIMIT 1", (inst.id,))
    if not r:
        raise PaperError("这个合约还没有价格")
    return {"price": r["close"], "source": "close", "time": r["date"]}


def main_contract(st: Store, inst: Instrument) -> str:
    r = st.one("SELECT contract FROM bars WHERE inst=? ORDER BY date DESC LIMIT 1", (inst.id,))
    if not r:
        raise PaperError("这个品种还没有数据")
    return r["contract"]


# ---- accounts -------------------------------------------------------------------------------------------
def create_account(m: Market, st: Store, uid: str, name: str, mode: str = "manual", agent_inst: str | None = None) -> dict:
    if mode not in ("manual", "agent"):
        raise PaperError("mode 只能是 manual 或 agent")
    n = st.one("SELECT COUNT(*) AS n FROM accounts WHERE uid=?", (uid,))["n"]
    if n >= 10:
        raise PaperError("每个市场最多 10 个模拟账户")
    aid = uuid.uuid4().hex[:12]
    with st.tx() as c:
        c.execute("INSERT INTO accounts (id,uid,name,mode,agent_inst,capital,cash,created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (aid, uid, (name or "模拟账户")[:40], mode, agent_inst or m.main, m.capital, m.capital, now()))
    return account(m, st, uid, aid)


def _own(st: Store, uid: str, aid: str):
    a = st.one("SELECT * FROM accounts WHERE id=? AND uid=?", (aid, uid))
    if not a:
        raise PaperError("没有这个账户")
    return a


def update_account(m: Market, st: Store, uid: str, aid: str, name: str | None, mode: str | None, agent_inst: str | None) -> dict:
    a = _own(st, uid, aid)
    if mode and mode not in ("manual", "agent"):
        raise PaperError("mode 只能是 manual 或 agent")
    if agent_inst and not m.instrument(agent_inst):
        raise PaperError("没有这个品种")
    with st.tx() as c:
        c.execute("UPDATE accounts SET name=?, mode=?, agent_inst=? WHERE id=?",
                  ((name or a["name"])[:40], mode or a["mode"], agent_inst or a["agent_inst"], aid))
    return account(m, st, uid, aid)


def delete_account(st: Store, uid: str, aid: str) -> None:
    _own(st, uid, aid)
    with st.tx() as c:
        for t in ("positions", "trades", "equity"):
            c.execute(f"DELETE FROM {t} WHERE account=?", (aid,))
        c.execute("DELETE FROM accounts WHERE id=?", (aid,))


def _positions(m: Market, st: Store, aid: str, live: bool = True) -> list[dict]:
    out = []
    for p in st.query("SELECT * FROM positions WHERE account=? AND lots<>0 ORDER BY inst, contract", (aid,)):
        inst = m.instrument(p["inst"])
        q = price_of(m, st, inst, p["contract"]) if live else {"price": p["avg_price"], "source": "cost"}
        upnl = (q["price"] - p["avg_price"]) * p["lots"] * inst.multiplier
        main = main_contract(st, inst)
        out.append({"inst": p["inst"], "name": inst.name, "nameEn": inst.name_en, "contract": p["contract"], "lots": p["lots"],
                    "avgPrice": round(p["avg_price"], 4), "price": q["price"], "priceSource": q["source"], "priceTime": q.get("time"),
                    "unrealized": round(upnl, 2), "notional": round(abs(p["lots"]) * q["price"] * inst.multiplier, 2),
                    "margin": round(abs(p["lots"]) * q["price"] * inst.multiplier * inst.margin, 2),
                    "isMain": p["contract"] == main, "main": main})
    return out


def account(m: Market, st: Store, uid: str, aid: str, trades: int = 50) -> dict:
    a = _own(st, uid, aid)
    pos = _positions(m, st, aid)
    upnl = sum(p["unrealized"] for p in pos)
    equity = a["cash"] + upnl
    margin = sum(p["margin"] for p in pos)
    tr = [dict(r) for r in st.query("SELECT * FROM trades WHERE account=? ORDER BY id DESC LIMIT ?", (aid, trades))]
    curve = [dict(r) for r in st.query("SELECT date, equity FROM equity WHERE account=? ORDER BY date", (aid,))]
    return {"id": a["id"], "name": a["name"], "mode": a["mode"], "agentInst": a["agent_inst"], "currency": m.currency,
            "capital": a["capital"], "cash": round(a["cash"], 2), "equity": round(equity, 2), "unrealized": round(upnl, 2),
            "margin": round(margin, 2), "available": round(equity - margin, 2),
            "return": round(equity / a["capital"] - 1, 5) if a["capital"] else 0, "createdAt": a["created_at"],
            "positions": pos, "trades": tr, "curve": curve}


def accounts(m: Market, st: Store, uid: str) -> list[dict]:
    out = []
    for a in st.query("SELECT id FROM accounts WHERE uid=? ORDER BY created_at", (uid,)):
        acc = account(m, st, uid, a["id"], trades=0)
        acc.pop("trades")
        acc.pop("curve")
        out.append(acc)
    return out


# ---- orders ---------------------------------------------------------------------------------------------
def _fill(m: Market, st: Store, aid: str, inst: Instrument, contract: str, lots: int, price: float, by: str, note: str,
          day: str | None = None) -> dict:
    """Apply a signed fill (lots > 0 buys) at `price`; realize P&L on the part that reduces a position."""
    fee = abs(lots) * price * inst.multiplier * inst.fee_rate
    with st.tx() as c:
        p = c.execute("SELECT lots, avg_price FROM positions WHERE account=? AND contract=?", (aid, contract)).fetchone()
        cur, avg = (p["lots"], p["avg_price"]) if p else (0, 0.0)
        realized = 0.0
        new = cur + lots
        if cur and (cur > 0) != (lots > 0):           # reducing or flipping
            closed = min(abs(lots), abs(cur)) * (1 if cur > 0 else -1)
            realized = (price - avg) * closed * inst.multiplier
            avg = avg if abs(lots) < abs(cur) else price
            if abs(lots) == abs(cur):
                avg = 0.0
        else:                                         # opening or adding
            avg = (avg * abs(cur) + price * abs(lots)) / abs(new) if new else 0.0
        c.execute("INSERT INTO positions (account,contract,inst,lots,avg_price) VALUES (?,?,?,?,?) ON CONFLICT(account,contract) "
                  "DO UPDATE SET lots=excluded.lots, avg_price=excluded.avg_price", (aid, contract, inst.id, new, avg))
        c.execute("UPDATE accounts SET cash = cash + ? - ? WHERE id=?", (realized, fee, aid))
        c.execute("INSERT INTO trades (account,ts,date,inst,contract,side,lots,price,fee,realized,by,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (aid, now(), day or datetime.now().date().isoformat(), inst.id, contract, "buy" if lots > 0 else "sell",
                   abs(lots), price, round(fee, 2), round(realized, 2), by, note[:300]))
    return {"contract": contract, "lots": lots, "price": price, "fee": round(fee, 2), "realized": round(realized, 2)}


def order(m: Market, st: Store, uid: str, aid: str, inst_id: str, side: str, lots: int, contract: str | None = None) -> dict:
    a = _own(st, uid, aid)
    if a["mode"] == "agent":
        raise PaperError("这个账户由逻辑包代下单；先切回手动")
    inst = m.instrument(inst_id)
    if not inst:
        raise PaperError("没有这个品种")
    if side not in ("buy", "sell") or not isinstance(lots, int) or not 1 <= lots <= 1000:
        raise PaperError("方向是 buy/sell，手数 1–1000")
    contract = contract or main_contract(st, inst)
    if inst.source["kind"] == "cn_future":
        contract = contract.lower()
    if inst.source["kind"] == "cn_future" and not st.one("SELECT 1 FROM contracts WHERE contract=? LIMIT 1", (contract,)):
        raise PaperError(f"没有合约 {contract}")
    q = price_of(m, st, inst, contract)
    signed = lots if side == "buy" else -lots
    price = q["price"] + (inst.tick if signed > 0 else -inst.tick)
    acc = account(m, st, uid, aid, trades=0)
    cur = next((p["lots"] for p in acc["positions"] if p["contract"] == contract), 0)
    adds = abs(cur + signed) > abs(cur)
    if adds:
        gross = sum(p["notional"] for p in acc["positions"] if p["contract"] != contract) + abs(cur + signed) * price * inst.multiplier
        if acc["equity"] <= 0 or gross > acc["equity"] * MAX_LEVERAGE:
            raise PaperError(f"超过 {MAX_LEVERAGE:g} 倍杠杆上限（名义价值 / 权益）")
        need = sum(p["margin"] for p in acc["positions"] if p["contract"] != contract) + abs(cur + signed) * price * inst.multiplier * inst.margin
        if need > acc["equity"]:
            raise PaperError("保证金不够")
    fill = _fill(m, st, aid, inst, contract, signed, price, "human", f"手动 · 成交价来自{'实时行情' if q['source'] == 'realtime' else '最近收盘'}")
    return {"fill": {**fill, "priceSource": q["source"]}, "account": account(m, st, uid, aid)}


# ---- marking and the agent ------------------------------------------------------------------------------
def mark_all(m: Market, st: Store, day: str) -> int:
    """Record end-of-day equity for every account, valued at stored closes of `day`."""
    n = 0
    for a in st.query("SELECT * FROM accounts"):
        upnl = 0.0
        for p in st.query("SELECT * FROM positions WHERE account=? AND lots<>0", (a["id"],)):
            inst = m.instrument(p["inst"])
            if inst.source["kind"] == "cn_future":
                r = st.one("SELECT close FROM contracts WHERE contract=? AND date<=? ORDER BY date DESC LIMIT 1", (p["contract"], day))
            else:
                r = st.one("SELECT close FROM bars WHERE inst=? AND date<=? ORDER BY date DESC LIMIT 1", (p["inst"], day))
            if r:
                upnl += (r["close"] - p["avg_price"]) * p["lots"] * inst.multiplier
        with st.tx() as c:
            c.execute("INSERT INTO equity (account,date,equity) VALUES (?,?,?) ON CONFLICT(account,date) DO UPDATE SET equity=excluded.equity",
                      (a["id"], day, round(a["cash"] + upnl, 2)))
        n += 1
    return n


def run_agents(m: Market, st: Store) -> dict:
    """After a new close: each agent account moves to the pack's target exposure on its instrument, at that close."""
    fr = A.frame(m, st)
    if not len(fr.cal):
        return {"skipped": "no data"}
    day = fr.last_date
    pk = P.current(m)
    rels = P.relations_of(pk, m, used_only=True)
    weights = P.weights_of(pk)
    done = []
    for a in st.query("SELECT * FROM accounts WHERE mode='agent'"):
        if st.one("SELECT 1 FROM trades WHERE account=? AND by='agent' AND date=? LIMIT 1", (a["id"], day)) or \
                st.get_state(f"agent:{a['id']}") == day:
            continue
        inst = m.instrument(a["agent_inst"] or m.main)
        view = float(A.composite(fr, rels, inst.id, weights).iloc[-1]) if rels else 0.0
        contract = main_contract(st, inst)
        close = float(fr.bars[inst.id]["close"].iloc[-1])
        acc = account(m, st, a["uid"], a["id"], trades=0)
        target = int(math.floor(abs(view) * acc["equity"] / (close * inst.multiplier))) * (1 if view >= 0 else -1)
        why = ", ".join(r.name for r in rels if r.target == inst.id and abs(float(fr.signal(r).iloc[-1])) >= 0.15) or "没有关系给出看法"
        # roll: anything held in other contracts of this instrument is closed first
        for p in acc["positions"]:
            if p["inst"] == inst.id and p["contract"] != contract and p["lots"]:
                px = st.one("SELECT close FROM contracts WHERE contract=? ORDER BY date DESC LIMIT 1", (p["contract"],))
                _fill(m, st, a["id"], inst, p["contract"], -p["lots"], px["close"] if px else p["price"], "agent", "换月：平掉旧合约", day)
        cur = st.one("SELECT lots FROM positions WHERE account=? AND contract=?", (a["id"], contract))
        cur = cur["lots"] if cur else 0
        if target != cur:
            _fill(m, st, a["id"], inst, contract, target - cur, close, "agent",
                  f"逻辑包看法 {view:+.2f} → 目标 {target} 手（{why}）", day)
        st.set_state(f"agent:{a['id']}", day)
        done.append({"account": a["id"], "view": round(view, 3), "target": target, "from": cur})
    mark_all(m, st, day)
    return {"date": day, "rebalanced": done}
