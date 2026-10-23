"""`define_market`: what one market (one 品种) is made of.

A market lists its tradable instruments, the data series around them (prices, spreads, basis, FX, weather…),
and seed relations: hypotheses of the form "driver moves → target follows, with this sign, after this lag".
Relations are only claims; analytics.evidence() measures each one on history and the logic pack (pack.py)
keeps the ones that survive the regression test.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Callable

# feature transforms a relation may apply to its driver (analytics.feature implements each)
TRANSFORMS = {
    "pct": "N 日涨跌幅（标准化）",
    "diff": "N 日变化（标准化）",
    "level": "水平相对过去一年的位置（标准化）",
    "sum": "N 日累计（标准化）",
    "anomaly": "N 日累计相对往年同期的偏离（标准化）",
    "count_below": "N 日内低于阈值的天数",
    "count_above": "N 日内高于阈值的天数",
}


@dataclass
class Instrument:
    id: str                    # "JM" — also the series id of its close
    name: str                  # 焦煤
    name_en: str
    exchange: str              # DCE / SHFE / ICE
    currency: str              # CNY / USD
    unit: str                  # 元/吨, ¢/lb
    multiplier: float          # contract size in price units (60 t, 37 500 lb → 375 USD per ¢)
    margin: float              # margin rate used by paper trading
    fee_rate: float            # commission as a fraction of notional
    tick: float
    source: dict               # {"kind": "cn_future", "symbol": "JM", "months": [1, 5, 9]} | {"kind": "foreign_future", "symbol": "KC"}
    quote: str = ""            # Sina realtime code prefix: "nf_" (per contract) or "hf_KC"
    note: str = ""             # caveat shown in the UI (e.g. unadjusted continuous contract)
    note_en: str = ""


@dataclass
class Series:
    id: str
    name: str
    name_en: str
    unit: str
    group: str                 # 价格 / 价差 / 基差 / 汇率 / 天气 …
    group_en: str
    source: dict | None = None # fetched by sources.fetch_series; None for derived series
    derive: Callable | None = None   # f(frame of trading-day series) -> pd.Series, for derived series
    formula: str = ""          # human readable formula of a derived series
    calendar: str = "trade"    # "trade" (one value per trading day) or "day" (calendar days: weather, FX)


@dataclass
class Relation:
    id: str
    driver: str                # series id
    target: str                # instrument id
    transform: str             # key of TRANSFORMS
    window: int                # days the transform looks back over (calendar days for "day" series)
    lag: int                   # trading days between the driver reading and acting on it
    horizon: int               # trading days of target return the relation predicts
    sign: int                  # +1: driver up → target up; -1: driver up → target down
    name: str
    name_en: str
    why: str                   # the economic logic, in Chinese
    why_en: str
    threshold: float | None = None   # for count_below / count_above
    months: list[int] | None = None  # only active in these calendar months (seasonal logic)
    origin: str = "seed"       # seed (written in the market spec) | gen (proposed by the LLM offline)
    kind: str = "cross"        # cross: one series drives another · self: a regularity of the instrument's own prices

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Node:
    id: str                    # series id
    x: float                   # 0..1 position in the chain diagram
    y: float
    tier: str = ""             # 上游 / 中游 / 下游 / 外部


@dataclass
class Market:
    key: str
    name: str
    name_en: str
    tagline: str
    tagline_en: str
    currency: str
    start: str                 # first date of history to sync (YYYY-MM-DD)
    instruments: list[Instrument]
    series: list[Series]
    relations: list[Relation]
    nodes: list[Node] = field(default_factory=list)
    main: str = ""             # headline instrument
    timezone: str = "Asia/Shanghai"
    capital: float = 1_000_000  # starting cash of a paper account, in `currency`

    def instrument(self, iid: str) -> Instrument | None:
        return next((i for i in self.instruments if i.id == iid), None)

    def all_series(self) -> list[Series]:
        """Instrument closes first (they are series too), then the spec's own series."""
        out = [Series(i.id, i.name, i.name_en, i.unit, "价格", "Price") for i in self.instruments]
        return out + self.series

    def series_by_id(self) -> dict[str, Series]:
        return {s.id: s for s in self.all_series()}


def define_market(**kw) -> Market:
    m = Market(**kw)
    m.main = m.main or m.instruments[0].id
    known = m.series_by_id()
    for r in m.relations:
        assert r.driver in known, f"{m.key}: relation {r.id} driver {r.driver} is not a series"
        assert m.instrument(r.target), f"{m.key}: relation {r.id} target {r.target} is not an instrument"
        assert r.transform in TRANSFORMS, f"{m.key}: relation {r.id} transform {r.transform}"
    for n in m.nodes:
        assert n.id in known, f"{m.key}: node {n.id} is not a series"
    return m


# ---- regularities of an instrument's own prices (kind="self") ---------------------------------------------
def momentum(iid: str, name: str, name_en: str, window: int = 60, horizon: int = 20) -> Relation:
    """Time-series momentum: the instrument's own trend over `window` days, held `horizon` days."""
    return Relation(f"{iid.lower()}_momentum", iid, iid, "pct", window=window, lag=0, horizon=horizon, sign=1,
                    name=f"{name} {window} 日趋势 → 延续", name_en=f"{name_en} {window}-day trend → continues",
                    why="商品的供需调整慢（产能、库存、物流都要时间），价格信息被逐步消化，趋势往往会延续一段时间。",
                    why_en="Commodity supply and demand adjust slowly, so price information is absorbed gradually and trends tend to persist.",
                    kind="self")


def carry_series(iid: str, name: str, name_en: str) -> Series:
    return Series(f"{iid}.carry", f"{name}期限结构", f"{name_en} term structure", "%/年", "期限结构", "Term structure",
                  source={"kind": "cn_carry"}, formula="(主力 ÷ 下一个合约 − 1)，年化；正数 = 近月贵（贴水结构）")


def carry(iid: str, name: str, name_en: str, horizon: int = 20) -> Relation:
    """Term structure: backwardation (near dearer than far) → longs earn the roll and spot is tight."""
    return Relation(f"{iid.lower()}_carry", f"{iid}.carry", iid, "level", window=250, lag=0, horizon=horizon, sign=1,
                    name=f"{name}近月升水 → 上涨", name_en=f"{name_en} backwardation → up",
                    why="近月比远月贵说明现货偏紧；做多远一点的合约，随着到期会向现货靠拢，赚到展期收益。",
                    why_en="A dearer near month signals tight spot supply; a long position rolls up the curve toward spot.",
                    kind="self")
