"""Turn stored data into aligned frames, relation features, evidence and positions. Pure code, no model calls.

Conventions (no look-ahead anywhere):
- the calendar is the trading days of the market's main instrument;
- a feature at day t only uses data dated ≤ t, shifted by the relation's lag;
- a position decided at the close of t earns the target's return of t+1;
- returns are measured inside one contract (sources.main_chain), so rolls are not returns.
"""
from __future__ import annotations

import json
import math
import threading

import numpy as np
import pandas as pd

from .spec import Market, Relation
from .store import Store

ZWIN = 250        # rolling window (trading days) used to standardize features
ZMIN = 60         # minimum history before a z-score is trusted


class Frame:
    """Everything a market's analytics need, loaded once per sync."""

    def __init__(self, m: Market, st: Store):
        self.m = m
        bars = {}
        for inst in m.instruments:
            rows = st.query("SELECT date,contract,open,high,low,close,settle,volume,oi,ret FROM bars WHERE inst=? ORDER BY date", (inst.id,))
            df = pd.DataFrame([dict(r) for r in rows])
            if len(df):
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            bars[inst.id] = df
        main = bars.get(m.main)
        self.cal = main.index if main is not None and len(main) else pd.DatetimeIndex([])
        self.bars = bars
        self.ret = pd.DataFrame({i: (b["ret"].reindex(self.cal).fillna(0.0) if len(b) else 0.0) for i, b in bars.items()}, index=self.cal)
        self.close = pd.DataFrame({i: (b["close"].reindex(self.cal).ffill() if len(b) else np.nan) for i, b in bars.items()}, index=self.cal)
        self.native: dict[str, pd.Series] = {}   # each series on its own dates (calendar days for weather / FX)
        self.aligned = pd.DataFrame(index=self.cal)
        for i in bars:
            self.native[i] = self.close[i]
            self.aligned[i] = self.close[i]
        for s in m.series:
            if s.derive is not None:
                continue
            rows = st.query("SELECT date,value FROM points WHERE series=? ORDER BY date", (s.id,))
            ser = pd.Series({pd.Timestamp(r["date"]): r["value"] for r in rows}, dtype=float).sort_index()
            self.native[s.id] = ser
            # as-of alignment: the value known on each trading day (forward fill, never backward)
            self.aligned[s.id] = ser.reindex(ser.index.union(self.cal)).ffill(limit=10).reindex(self.cal) if len(ser) else np.nan
        for s in m.series:
            if s.derive is not None:
                try:
                    ser = s.derive(self.aligned)
                except Exception:
                    ser = pd.Series(np.nan, index=self.cal)
                self.native[s.id] = ser
                self.aligned[s.id] = ser
        self.series_meta = m.series_by_id()
        self._memo: dict[tuple, pd.Series] = {}

    def _cached(self, kind: str, r: Relation, fn) -> pd.Series:
        key = (kind, r.driver, r.transform, r.window, r.lag, r.threshold, r.sign, tuple(r.months or ()))
        if key not in self._memo:
            if len(self._memo) > 600:  # custom backtests add variants; keep the cache bounded
                self._memo.clear()
            self._memo[key] = fn()
        return self._memo[key]

    @property
    def last_date(self) -> str | None:
        return self.cal[-1].date().isoformat() if len(self.cal) else None

    # ---- features -----------------------------------------------------------------------------------------
    def raw_feature(self, r: Relation) -> pd.Series:
        """The transform of the driver before standardization, on the trading calendar."""
        return self._cached("raw", r, lambda: self._raw_feature(r))

    def _raw_feature(self, r: Relation) -> pd.Series:
        meta = self.series_meta[r.driver]
        x = self.native.get(r.driver)
        if x is None or not len(x.dropna()):
            return pd.Series(np.nan, index=self.cal)
        x = x.dropna()
        w = r.window
        if r.transform == "pct":
            f = x.pct_change(w, fill_method=None)
        elif r.transform == "diff":
            f = x.diff(w)
        elif r.transform == "level":
            f = x
        elif r.transform == "sum":
            f = _daily(x, meta.calendar).rolling(w, min_periods=max(1, w // 2)).sum()
        elif r.transform == "anomaly":
            f = _seasonal_anomaly(_daily(x, meta.calendar).rolling(w, min_periods=max(1, w // 2)).sum())
        elif r.transform == "count_below":
            f = (_daily(x, meta.calendar) < r.threshold).astype(float).rolling(w, min_periods=1).sum()
        elif r.transform == "count_above":
            f = (_daily(x, meta.calendar) > r.threshold).astype(float).rolling(w, min_periods=1).sum()
        else:
            raise ValueError(r.transform)
        return f.reindex(f.index.union(self.cal)).ffill(limit=10).reindex(self.cal)

    def feature(self, r: Relation) -> pd.Series:
        """Standardized feature at each trading day, lag applied. Counts stay counts; anomalies are already z-scores."""
        return self._cached("feature", r, lambda: self._feature(r))

    def _feature(self, r: Relation) -> pd.Series:
        f = self.raw_feature(r)
        if r.transform in ("pct", "diff"):
            z = f / f.rolling(ZWIN, min_periods=ZMIN).std()
        elif r.transform in ("level", "sum"):
            w = max(r.window, 20) if r.transform == "level" else ZWIN  # level: "high versus the last `window` days"
            z = (f - f.rolling(w, min_periods=min(ZMIN, w)).mean()) / f.rolling(w, min_periods=min(ZMIN, w)).std()
        else:
            z = f
        return z.replace([np.inf, -np.inf], np.nan).shift(r.lag)

    def in_season(self, r: Relation) -> pd.Series:
        if not r.months:
            return pd.Series(True, index=self.cal)
        return pd.Series(self.cal.month.isin(r.months), index=self.cal)

    def signal(self, r: Relation) -> pd.Series:
        """−1..1 view on the target implied by the relation at each close (0 = no view)."""
        return self._cached("signal", r, lambda: self._signal(r))

    def _signal(self, r: Relation) -> pd.Series:
        z = self.feature(r)
        if r.transform.startswith("count_"):
            s = z.clip(0, 3) / 3
        else:
            s = z.clip(-2, 2) / 2
        s = (r.sign * s).where(self.in_season(r), 0.0)
        return s.fillna(0.0)

    def forward(self, inst: str, horizon: int) -> pd.Series:
        """Return of `inst` from the close of t to the close of t+horizon (inside contracts)."""
        lr = np.log1p(self.ret[inst])
        fwd = lr[::-1].rolling(horizon, min_periods=horizon).sum()[::-1].shift(-1)
        return np.expm1(fwd)


def _daily(x: pd.Series, calendar: str) -> pd.Series:
    """Weather is summed over calendar days: give it a complete daily index (missing days stay missing)."""
    if calendar != "day" or not len(x):
        return x
    return x.reindex(pd.date_range(x.index[0], x.index[-1], freq="D"))


def _seasonal_anomaly(s: pd.Series) -> pd.Series:
    """z-score of each value against the same calendar day in *earlier* years only (at least three of them)."""
    s = s.dropna()
    if not len(s):
        return s
    df = pd.DataFrame({"v": s.values, "y": s.index.year, "d": s.index.strftime("%m-%d")}, index=s.index)
    piv = df.pivot_table(index="d", columns="y", values="v")
    out = pd.Series(np.nan, index=s.index)
    years = sorted(piv.columns)
    for y in years:
        prior = [c for c in years if c < y]
        if len(prior) < 3:
            continue
        mu, sd = piv[prior].mean(axis=1), piv[prior].std(axis=1)
        sel = df["y"] == y
        d = df.loc[sel, "d"]
        out[sel] = (df.loc[sel, "v"].values - mu.reindex(d).values) / sd.reindex(d).replace(0, np.nan).values
    return out


# ---- evidence: does the relation hold on history? -------------------------------------------------------
def evidence(fr: Frame, r: Relation, start: str | None = None, end: str | None = None) -> dict:
    sig = fr.signal(r)
    z = fr.feature(r)
    fwd = fr.forward(r.target, r.horizon)
    mask = z.notna() & fwd.notna() & fr.in_season(r)
    if start:
        mask &= fr.cal >= pd.Timestamp(start)
    if end:
        mask &= fr.cal <= pd.Timestamp(end)
    n = int(mask.sum())
    out = {"n": n, "ic": None, "t": None, "hit": None, "active": 0, "avgActive": None, "verdict": "insufficient", "byYear": []}
    if n < 40:
        return out
    x, y = z[mask], fwd[mask]
    ic = float(r.sign * np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else 0.0
    t = ic * math.sqrt(max(n / r.horizon, 1))
    active = sig[mask].abs() >= (1 / 3 if r.transform.startswith("count_") else 0.5)
    na = int(active.sum())
    hit = avg = None
    if na:
        dirn = np.sign(sig[mask][active])
        hit = float((np.sign(y[active]) == dirn).mean())
        avg = float((dirn * y[active]).mean())
    by_year = []
    for yr, idx in x.groupby(x.index.year).groups.items():
        xx, yy = x[idx], y[idx]
        if len(xx) >= 30 and xx.std() > 0 and yy.std() > 0:
            by_year.append({"year": int(yr), "ic": round(float(r.sign * np.corrcoef(xx, yy)[0, 1]), 3), "n": len(xx)})
    if na < 10:
        verdict = "insufficient"
    elif ic > 0 and t >= 2 and (hit or 0) > 0.5:
        verdict = "holds"
    elif ic > 0 and t >= 1:
        verdict = "weak"
    else:
        verdict = "fails"
    out.update(ic=round(ic, 3), t=round(t, 2), hit=None if hit is None else round(hit, 3), active=na,
               avgActive=None if avg is None else round(avg, 5), verdict=verdict, byYear=by_year)
    return out


def comove(fr: Frame, r: Relation, start: str | None = None, end: str | None = None) -> dict:
    """Same-period evidence: does the driver's change over `horizon` days line up with the target's return over
    those same days? This explains moves (复盘) but, unlike evidence(), says nothing about predicting them."""
    h = max(r.horizon, 1)
    if r.kind == "self":  # a series against itself (or its own curve) co-moves by construction
        return {"n": 0, "corr": None, "t": None, "verdict": "na", "horizon": h}
    meta = fr.series_meta[r.driver]
    if r.transform in ("pct", "level") and meta.group in ("价格", "汇率", "现货"):
        dx = fr.aligned[r.driver].pct_change(h, fill_method=None)   # prices: percent change
    else:
        dx = fr.raw_feature(r).diff(h)                               # spreads, basis, weather: change of the reading
    lr = np.log1p(fr.ret[r.target])
    dy = np.expm1(lr.rolling(h, min_periods=h).sum())
    ok = dx.notna() & dy.notna() & fr.in_season(r)
    if start:
        ok &= fr.cal >= pd.Timestamp(start)
    if end:
        ok &= fr.cal <= pd.Timestamp(end)
    idx = fr.cal[ok][::h]                      # non-overlapping windows
    out = {"n": len(idx), "corr": None, "t": None, "verdict": "insufficient", "horizon": h}
    if len(idx) < 30:
        return out
    x, y = dx[idx].replace([np.inf, -np.inf], np.nan), dy[idx]
    keep = x.notna()
    x, y = x[keep], y[keep]
    if len(x) < 30 or x.std() == 0 or y.std() == 0:
        return out
    c = float(r.sign * np.corrcoef(x, y)[0, 1])
    t = c * math.sqrt(len(x) - 2) / math.sqrt(max(1 - c * c, 1e-9))
    out.update(corr=round(c, 3), t=round(t, 2), n=len(x),
               verdict="holds" if c > 0 and t >= 2 else "weak" if c > 0 and t >= 1 else "fails")
    return out


def latest_state(fr: Frame, r: Relation, at: pd.Timestamp | None = None) -> dict:
    """The relation's reading on one day: driver value, standardized feature, implied view."""
    if not len(fr.cal):
        return {}
    at = at if at is not None else fr.cal[-1]
    z, sig = fr.feature(r), fr.signal(r)
    raw = fr.raw_feature(r).shift(r.lag)
    drv = fr.aligned[r.driver] if r.driver in fr.aligned else pd.Series(dtype=float)
    val = lambda s: None if at not in s.index or pd.isna(s[at]) else round(float(s[at]), 4)
    return {"date": at.date().isoformat(), "driver": val(drv), "raw": val(raw), "z": val(z), "signal": val(sig),
            "inSeason": bool(fr.in_season(r)[at]) if at in fr.cal else False}


# ---- positions and backtests ----------------------------------------------------------------------------
def composite(fr: Frame, rels: list[Relation], target: str, weights: dict[str, float] | None = None) -> pd.Series:
    """Weighted average of the relations' views on one target, −1..1, at each close."""
    rs = [r for r in rels if r.target == target]
    if not rs:
        return pd.Series(0.0, index=fr.cal)
    w = {r.id: (weights or {}).get(r.id, 1.0) for r in rs}
    tot = sum(abs(v) for v in w.values()) or 1.0
    return (sum(fr.signal(r) * w[r.id] for r in rs) / tot).clip(-1, 1)


def backtest(fr: Frame, rels: list[Relation], target: str, *, start: str | None = None, end: str | None = None,
             cost_bps: float = 3.0, threshold: float = 0.0, discrete: bool = False, long_only: bool = False,
             weights: dict[str, float] | None = None, split: str | None = None) -> dict:
    """Trade `target` on the composite view of `rels`. Position at close t earns ret of t+1, minus cost on turnover."""
    pos = composite(fr, rels, target, weights)
    if discrete:
        pos = np.sign(pos).where(pos.abs() > threshold, 0.0)
    elif threshold:
        pos = pos.where(pos.abs() > threshold, 0.0)
    if long_only:
        pos = pos.clip(lower=0)
    ret = fr.ret[target]
    idx = fr.cal
    if start:
        idx = idx[idx >= pd.Timestamp(start)]
    if end:
        idx = idx[idx <= pd.Timestamp(end)]
    if len(idx) < 5:
        return {"error": "这个区间数据太少"}
    held = pos.shift(1).reindex(idx).fillna(0.0)        # position carried into each day
    turnover = held.diff().abs().fillna(held.abs())
    pnl = held * ret.reindex(idx).fillna(0.0) - turnover * cost_bps / 1e4
    eq = (1 + pnl).cumprod()
    bench = (1 + ret.reindex(idx).fillna(0.0)).cumprod()
    out = {
        "target": target, "relations": [r.id for r in rels if r.target == target],
        "dates": [d.date().isoformat() for d in idx],
        "equity": _r(eq), "benchmark": _r(bench), "position": _r(held, 3),
        "drawdown": _r(eq / eq.cummax() - 1),
        "metrics": _metrics(pnl, held, turnover), "benchmarkMetrics": _metrics(ret.reindex(idx).fillna(0.0), None, None),
        "byYear": [{"year": int(y), "ret": round(float((1 + p).prod() - 1), 4),
                    "bench": round(float((1 + ret.reindex(p.index).fillna(0)).prod() - 1), 4)}
                   for y, p in pnl.groupby(pnl.index.year)],
        "costBps": cost_bps,
    }
    if split:
        s = pd.Timestamp(split)
        out["split"] = split
        out["inSample"] = _metrics(pnl[pnl.index < s], held[held.index < s], turnover[turnover.index < s])
        out["outSample"] = _metrics(pnl[pnl.index >= s], held[held.index >= s], turnover[turnover.index >= s])
    return out


def _r(s: pd.Series, nd: int = 5) -> list:
    return [None if pd.isna(v) else round(float(v), nd) for v in s.values]


def _metrics(pnl: pd.Series, held: pd.Series | None, turnover: pd.Series | None) -> dict:
    n = len(pnl)
    if n < 2:
        return {}
    eq = (1 + pnl).cumprod()
    total = float(eq.iloc[-1] - 1)
    ann = float(eq.iloc[-1] ** (252 / n) - 1) if eq.iloc[-1] > 0 else -1.0
    vol = float(pnl.std() * math.sqrt(252))
    m = {"days": n, "total": round(total, 4), "annual": round(ann, 4), "vol": round(vol, 4),
         "sharpe": round(float(pnl.mean() / pnl.std() * math.sqrt(252)), 2) if pnl.std() > 0 else 0.0,
         "maxDrawdown": round(float((eq / eq.cummax() - 1).min()), 4)}
    if held is not None:
        on = held.abs() > 1e-9
        m["exposure"] = round(float(on.mean()), 3)
        m["winRate"] = round(float((pnl[on] > 0).mean()), 3) if on.any() else None
        m["turnover"] = round(float(turnover.sum() / n * 252), 2)
        flips = (np.sign(held).diff().fillna(0) != 0) & (np.sign(held) != 0)
        m["entries"] = int(flips.sum())
    return m


# ---- cache: one Frame per market, rebuilt after each sync -----------------------------------------------
_frames: dict[str, tuple[str, Frame]] = {}
_lock = threading.Lock()


def frame(m: Market, st: Store) -> Frame:
    stamp = st.get_state("last_sync", "") or ""
    with _lock:
        hit = _frames.get(m.key)
        if hit and hit[0] == stamp:
            return hit[1]
    fr = Frame(m, st)
    with _lock:
        _frames[m.key] = (stamp, fr)
    return fr


def sync_stamp(st: Store) -> dict:
    try:
        return json.loads(st.get_state("last_sync", "") or "{}")
    except ValueError:
        return {}
