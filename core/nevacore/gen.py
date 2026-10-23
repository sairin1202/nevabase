"""Offline generation (the 生成期): the LLM proposes, the data disposes.

    seed_pack     spec relations only, evidence + regression test, publish (no LLM)
    generate      LLM proposes new relations from the series catalog and the current evidence; each candidate is
                  scored on the in-sample years only; the new pack must pass the regression gate (out-of-sample
                  Sharpe per target no worse than the current pack's) before it is published
    write_review  LLM turns one day's computed review into a short summary; it may only restate given numbers
"""
from __future__ import annotations

import json
import logging

from . import analytics as A
from . import llm
from . import pack as P
from .review import review
from .spec import TRANSFORMS, Market, Relation
from .store import Store, now

log = logging.getLogger("nevacore.gen")


def seed_pack(m: Market, st: Store) -> dict:
    fr = A.frame(m, st)
    pk = P.build(m, fr, list(m.relations), "seed")
    pk["gate"] = {"passed": True, "reasons": ["只用市场定义里写的种子关系"]}
    pk["published"] = True
    P.publish(m, pk)
    return _summary(pk)


def _catalog(m: Market, fr: A.Frame) -> list[dict]:
    out = []
    for s in m.all_series():
        x = fr.aligned.get(s.id)
        last = None if x is None or not len(x.dropna()) else round(float(x.dropna().iloc[-1]), 4)
        out.append({"id": s.id, "name": s.name, "unit": s.unit, "group": s.group, "calendar": s.calendar,
                    "formula": s.formula, "latest": last})
    return out


SYSTEM = """你是大宗商品研究员。你只提出“数据之间的逻辑关系”假设，每条都会被代码在历史数据上检验，检验不过就丢掉。
只能用给出的序列和品种；不要编造数据，不要写具体数字结论。只输出 JSON。"""


def _prompt(m: Market, fr: A.Frame, current: list[dict], n: int) -> str:
    rels = [{"id": r["id"], "driver": r["driver"], "target": r["target"], "transform": r["transform"],
             "window": r["window"], "lag": r["lag"], "horizon": r["horizon"], "sign": r["sign"], "months": r.get("months"),
             "name": r["name"], "inSample": r["inSample"]} for r in current]
    return f"""市场：{m.name}（{m.tagline}）
可交易品种（target 只能是这些）：{json.dumps([{"id": i.id, "name": i.name, "exchange": i.exchange, "unit": i.unit} for i in m.instruments], ensure_ascii=False)}
可用序列（driver 只能是这些 id）：{json.dumps(_catalog(m, fr), ensure_ascii=False)}
transform 可选：{json.dumps(TRANSFORMS, ensure_ascii=False)}
现有关系和样本内检验结果（ic>0 且 t≥2 为成立）：{json.dumps(rels, ensure_ascii=False)}

请再提出最多 {n} 条新的关系假设，要有产业或宏观逻辑，不要和现有关系重复（同一 driver+target+transform 算重复）。
可以是不同的窗口/滞后/季节，也可以是现有失败关系的更合理版本。每条一个对象：
{{"id": "小写下划线英文", "driver": "...", "target": "...", "transform": "...", "window": 1-250, "lag": 0-5, "horizon": 1-40,
  "sign": 1 或 -1, "threshold": 数字或 null（只有 count_below/count_above 要）, "months": [月份] 或 null,
  "name": "中文短名：A → B", "name_en": "English short name", "why": "中文：经济逻辑两句话以内", "why_en": "English logic"}}
只输出一个 JSON 数组。"""


def _validate(m: Market, c: dict, taken: set[str], keys: set[tuple]) -> tuple[Relation | None, str]:
    known = m.series_by_id()
    try:
        r = Relation(id=str(c["id"])[:40], driver=c["driver"], target=c["target"], transform=c["transform"],
                     window=int(c["window"]), lag=int(c["lag"]), horizon=int(c["horizon"]), sign=1 if int(c["sign"]) > 0 else -1,
                     threshold=None if c.get("threshold") is None else float(c["threshold"]),
                     months=[int(x) for x in c["months"]] if c.get("months") else None,
                     name=str(c["name"])[:60], name_en=str(c.get("name_en", ""))[:80],
                     why=str(c.get("why", ""))[:300], why_en=str(c.get("why_en", ""))[:300], origin="gen")
    except (KeyError, TypeError, ValueError) as e:
        return None, f"格式不对：{e}"
    if r.driver not in known:
        return None, f"没有序列 {r.driver}"
    if not m.instrument(r.target):
        return None, f"{r.target} 不是可交易品种"
    if r.driver == r.target and r.transform in ("pct", "diff"):
        return None, "自身动量不算数据之间的关系"
    if r.transform not in TRANSFORMS:
        return None, f"不支持的变换 {r.transform}"
    if r.transform.startswith("count_") and r.threshold is None:
        return None, "计数变换需要阈值"
    if not (1 <= r.window <= 250 and 0 <= r.lag <= 5 and 1 <= r.horizon <= 40):
        return None, "窗口/滞后/周期超出范围"
    if r.months and not all(1 <= x <= 12 for x in r.months):
        return None, "月份不对"
    if r.id in taken:
        r.id = f"{r.id}_{len(taken)}"
    if (r.driver, r.target, r.transform, r.window, r.lag, tuple(r.months or ())) in keys:
        return None, "和已有关系重复"
    return r, ""


def generate(m: Market, st: Store, dry: bool = False, n: int = 6) -> dict:
    fr = A.frame(m, st)
    cur = P.current(m)
    if cur is None:
        seed_pack(m, st)
        cur = P.current(m)
    # seeds come from the spec as it is now; generated relations carry over from the current pack
    carried = [r for r in P.relations_of(cur, m) if r.origin == "gen"]
    base = list(m.relations) + carried
    split = P.cutoff(fr)
    base_assessed = P.assess(fr, base, split)
    rejected, accepted = [], []
    if llm.enabled():
        try:
            reply = llm.chat(SYSTEM, _prompt(m, fr, base_assessed, n))
            cands = llm.json_block(reply)
        except Exception as e:
            log.warning("generation failed: %s", e)
            cands = []
            rejected.append({"id": "-", "reason": f"大模型没有给出可用结果：{e}"})
        taken = {r.id for r in base}
        keys = {(r.driver, r.target, r.transform, r.window, r.lag, tuple(r.months or ())) for r in base}
        for c in cands if isinstance(cands, list) else []:
            r, why = _validate(m, c, taken, keys)
            if r is None:
                rejected.append({"id": c.get("id") if isinstance(c, dict) else "-", "name": c.get("name") if isinstance(c, dict) else "", "reason": why})
                continue
            ins = A.evidence(fr, r, end=split)
            if ins["verdict"] in ("holds", "weak"):
                accepted.append(r)
                taken.add(r.id)
                keys.add((r.driver, r.target, r.transform, r.window, r.lag, tuple(r.months or ())))
            else:
                rejected.append({"id": r.id, "name": r.name, "reason": f"样本内不成立（ic {ins['ic']}，t {ins['t']}，{ins['verdict']}）",
                                 "relation": r.to_dict()})
    else:
        rejected.append({"id": "-", "reason": "没配 LLM_API_KEY，只重算现有关系"})
    new = P.build(m, fr, base + accepted, "gen", {"proposed": [r.id for r in accepted], "rejected": rejected})
    old_reg = P.regression(m, fr, P.assess(fr, P.relations_of(cur, m), split), split) if cur else None
    ok, reasons = P.gate(new["regression"], old_reg)
    new["gate"] = {"passed": ok, "reasons": reasons, "against": (cur or {}).get("version")}
    new["published"] = bool(ok and not dry)
    if new["published"]:
        P.publish(m, new)
    else:
        # keep the failed / dry pack for the record, without pointing `current` at it
        (P.pack_dir(m.key) / f"{new['version']}.json").write_text(json.dumps(new, ensure_ascii=False, indent=1), "utf-8")
    return _summary(new)


def _summary(pk: dict) -> dict:
    return {"version": pk["version"], "published": pk.get("published"), "gate": pk.get("gate"),
            "relations": [{"id": r["id"], "origin": r.get("origin"), "used": r["used"], "in": r["inSample"]["verdict"],
                           "out": r["outSample"]["verdict"], "ic": r["evidence"]["ic"]} for r in pk["relations"]],
            "proposed": pk.get("proposed"), "rejected": pk.get("rejected"),
            "regression": {k: {"in": (v.get("inSample") or {}).get("sharpe"), "out": (v.get("outSample") or {}).get("sharpe")}
                           for k, v in pk["regression"].items()}}


REVIEW_SYSTEM = """你在写期货复盘摘要。只能使用给你的数字和事实，不许出现给定数据里没有的数字、新闻或原因。
先写一句今天最重要的变化，再写逻辑链里哪些关系应验、哪些背离，最后一句写逻辑包对下一个交易日的看法（只说方向和强弱，不给投资建议）。
中文 120 字以内。然后另起一行写 "EN:" 加同样内容的英文。"""


def write_review(m: Market, st: Store, day: str | None = None) -> dict:
    rv = review(m, st, day)
    if rv.get("error"):
        return rv
    if not llm.enabled():
        return {"date": rv["date"], "skipped": "LLM_API_KEY not set"}
    facts = {k: rv[k] for k in ("date", "instruments", "composite", "movers")}
    facts["relations"] = [{k: r[k] for k in ("name", "used", "view", "targetD1", "check")} for r in rv["relations"]]
    text = llm.chat(REVIEW_SYSTEM, json.dumps(facts, ensure_ascii=False), temperature=0.2)
    zh, _, en = text.partition("EN:")
    with st.tx() as c:
        c.execute("INSERT INTO reviews (date,pack,narrative,narrative_en,created_at) VALUES (?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET "
                  "pack=excluded.pack, narrative=excluded.narrative, narrative_en=excluded.narrative_en, created_at=excluded.created_at",
                  (rv["date"], rv["pack"], zh.strip(), en.strip(), now()))
    return {"date": rv["date"], "narrative": zh.strip(), "narrativeEn": en.strip()}
