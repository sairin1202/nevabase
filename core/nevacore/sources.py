"""Data adapters. Each returns plain rows; sync.py decides what to fetch and stores it.

- cn_future:      single contracts from Sina via AkShare (futures_zh_daily_sina "JM2701"), chained by main_chain()
- foreign_future: Sina continuous foreign futures via AkShare (futures_foreign_hist "KC"), not roll-adjusted
- cn_basis:       spot price and basis of the dominant contract via AkShare (futures_spot_price_daily, 100ppi)
- fx:             ECB reference rates via Frankfurter
- weather:        Open-Meteo archive (history) + forecast (last two weeks and the next 16 days)
- quotes:         Sina realtime quotes for paper-trading fills
"""
from __future__ import annotations

import logging
import warnings
from datetime import date, datetime, timedelta

import httpx

log = logging.getLogger("nevacore.sources")
warnings.filterwarnings("ignore")
UA = {"User-Agent": "Mozilla/5.0 (nevabase.com market data)"}


def _ak():
    import akshare as ak  # heavy import (pandas, requests…); only the sync path needs it
    return ak


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# ---- domestic futures ------------------------------------------------------------------------------------
def contract_codes(symbol: str, months: list[int], start_year: int, today: date | None = None) -> list[str]:
    """Every contract of `symbol` in `months` that can have traded since `start_year` (plus the next year's)."""
    today = today or date.today()
    out = []
    for y in range(start_year, today.year + 2):
        for m in months:
            out.append(f"{symbol}{y % 100:02d}{m:02d}")
    return out


def contract_expiry(code: str) -> date:
    """Approximate last trading day of a contract: mid delivery month."""
    yy, mm = int(code[-4:-2]), int(code[-2:])
    return date(2000 + yy, mm, 15)


def fetch_contract(code: str) -> list[tuple]:
    """(date, open, high, low, close, settle, volume, oi) for one contract; [] if Sina has no data."""
    try:
        df = _ak().futures_zh_daily_sina(symbol=code)
    except Exception as e:  # unlisted / too old contracts raise a length-mismatch error
        log.debug("contract %s: %s", code, e)
        return []
    rows = []
    for r in df.itertuples(index=False):
        rows.append((str(r.date)[:10], _num(r.open), _num(r.high), _num(r.low), _num(r.close), _num(r.settle),
                     _num(r.volume), _num(r.hold)))
    return rows


def main_chain(contract_rows: dict[str, list[tuple]]) -> list[tuple]:
    """Chain single contracts into one row per trading day.

    The main contract of day t is chosen from day t-1 open interest (what a trader knew before the open),
    and only rolls forward to a later contract. `ret` is always measured inside one contract, so a roll
    never shows up as a return.
    Returns (date, contract, open, high, low, close, settle, volume, oi, ret).
    """
    by_code = {c: {r[0]: r for r in rows if r[4]} for c, rows in contract_rows.items() if rows}
    order = sorted(by_code, key=contract_expiry)
    dates = sorted({d for rows in by_code.values() for d in rows})
    oi = lambda c, d: (by_code[c][d][7] or 0) if d in by_code[c] else 0
    out, main, prev = [], None, None
    for d in dates:
        if main is None:
            main = max((oi(c, d), c) for c in order if d in by_code[c])[1]
        elif prev is not None:
            later = [c for c in order if contract_expiry(c) >= contract_expiry(main)]
            best_oi, best = max((oi(c, prev), c) for c in later)
            if best != main and best_oi > oi(main, prev):
                main = best
        if d not in by_code[main]:  # main stopped trading: the most active later contract today
            later = [c for c in order if d in by_code[c] and contract_expiry(c) >= contract_expiry(main)]
            if not later:
                prev = d
                continue
            main = max((oi(c, d), c) for c in later)[1]
        row, prev_row = by_code[main][d], by_code[main].get(prev) if prev else None
        ret = (row[4] / prev_row[4] - 1) if prev_row and prev_row[4] else None
        out.append((d, main, row[1], row[2], row[3], row[4], row[5], row[6], row[7], ret))
        prev = d
    return out


def carry(chain: list[tuple], contract_rows: dict[str, list[tuple]]) -> list[tuple[str, float]]:
    """Term structure per day: main contract against the next later contract, annualized, in %.
    Positive = backwardation (the nearer contract is dearer), negative = contango."""
    closes = {c: {r[0]: r[4] for r in rows if r[4]} for c, rows in contract_rows.items()}
    order = sorted(closes, key=contract_expiry)
    out = []
    for d, main, *_ in chain:
        if main not in closes or d not in closes[main]:
            continue
        later = [c for c in order if contract_expiry(c) > contract_expiry(main) and d in closes[c]]
        if not later:
            continue
        nxt = later[0]
        months = (contract_expiry(nxt).year - contract_expiry(main).year) * 12 + contract_expiry(nxt).month - contract_expiry(main).month
        if months <= 0:
            continue
        out.append((d, (closes[main][d] / closes[nxt][d] - 1) * 12 / months * 100))
    return out


# ---- foreign futures -------------------------------------------------------------------------------------
def fetch_foreign(symbol: str, yahoo: str | None = None) -> list[tuple]:
    """(date, contract, open, high, low, close, settle, volume, oi, ret) of a continuous foreign contract.
    Yahoo (e.g. KC=F) reaches back to 2000; Sina's series only to 2021 and is the fallback."""
    raw: list[tuple] = []
    if yahoo:
        try:
            raw = _yahoo_daily(yahoo)
        except Exception as e:
            log.warning("yahoo %s failed, falling back to sina: %s", yahoo, e)
    if not raw:
        df = _ak().futures_foreign_hist(symbol=symbol)
        raw = [(str(r.date)[:10], _num(r.open), _num(r.high), _num(r.low), _num(r.close), _num(r.volume))
               for r in df.itertuples(index=False)]
    out, prev = [], None
    for d, o, h, lo, c, v in raw:
        if not c:
            continue
        out.append((d, symbol, o, h, lo, c, None, v, None, (c / prev - 1) if prev else None))
        prev = c
    return out


def _yahoo_daily(ticker: str) -> list[tuple]:
    r = httpx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", headers=UA, timeout=30,
                  params={"period1": 946684800, "period2": int(datetime.now().timestamp()) + 86400, "interval": "1d"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    q = res["indicators"]["quote"][0]
    out = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        d = datetime.utcfromtimestamp(ts + off).date().isoformat()
        out[d] = (d, _num(q["open"][i]), _num(q["high"][i]), _num(q["low"][i]), _num(q["close"][i]), _num(q["volume"][i]))
    return [out[d] for d in sorted(out)]


# ---- spot & basis ----------------------------------------------------------------------------------------
def fetch_basis(variables: list[str], start: date, end: date) -> dict[str, list[tuple[str, float]]]:
    """{"JM.spot": [(date, spot)], "JM.basis": [(date, (spot − dominant futures) / spot in %)], …} for trading days in [start, end]."""
    df = _ak().futures_spot_price_daily(start_day=start.strftime("%Y%m%d"), end_day=end.strftime("%Y%m%d"),
                                        vars_list=variables)
    out: dict[str, list] = {}
    if df is None or len(df) == 0:
        return out
    for r in df.itertuples(index=False):
        d = str(r.date)
        d = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d[:10]
        spot, rate = _num(r.spot_price), _num(r.dom_basis_rate)
        if spot:
            out.setdefault(f"{r.symbol}.spot", []).append((d, spot))
        if rate is not None:  # AkShare's basis is futures − spot; ours is the usual 现货 − 期货
            out.setdefault(f"{r.symbol}.basis", []).append((d, -rate * 100))
    return out


# ---- FX --------------------------------------------------------------------------------------------------
def fetch_fx(base: str, quote: str, start: date) -> list[tuple[str, float]]:
    r = httpx.get(f"https://api.frankfurter.dev/v1/{start.isoformat()}..", params={"from": base, "to": quote},
                  headers=UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    rates = r.json().get("rates", {})
    return sorted((d, v[quote]) for d, v in rates.items() if quote in v)


# ---- weather ---------------------------------------------------------------------------------------------
def fetch_weather(lat: float, lon: float, var: str, start: date, end: date) -> list[tuple[str, float]]:
    """Daily history from the Open-Meteo archive (it lags about five days behind today)."""
    r = httpx.get("https://archive-api.open-meteo.com/v1/archive", headers=UA, timeout=60, params={
        "latitude": lat, "longitude": lon, "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": var, "timezone": "auto"})
    r.raise_for_status()
    d = r.json().get("daily", {})
    return [(t, v) for t, v in zip(d.get("time", []), d.get(var, [])) if v is not None]


def fetch_weather_recent(lat: float, lon: float, var: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """(last 14 days observed/analysed, next 16 days forecast). Forecasts are shown, never stored as history."""
    r = httpx.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=30, params={
        "latitude": lat, "longitude": lon, "daily": var, "past_days": 14, "forecast_days": 16, "timezone": "auto"})
    r.raise_for_status()
    d = r.json().get("daily", {})
    today = r.json().get("current_date") or date.today().isoformat()
    rows = [(t, v) for t, v in zip(d.get("time", []), d.get(var, [])) if v is not None]
    return [x for x in rows if x[0] < today], [x for x in rows if x[0] >= today]


# ---- realtime quotes -------------------------------------------------------------------------------------
def quotes(codes: list[str]) -> dict[str, dict]:
    """Sina realtime: codes like "nf_JM2701" (domestic contract) or "hf_KC" (foreign continuous).
    Returns {code: {"price", "prevSettle"|"prevClose", "time", "date"}} for codes that answered."""
    if not codes:
        return {}
    try:
        r = httpx.get("https://hq.sinajs.cn/list=" + ",".join(codes), timeout=8,
                      headers={**UA, "Referer": "https://finance.sina.com.cn"})
        text = r.content.decode("gbk", errors="replace")
    except Exception as e:
        log.warning("quotes failed: %s", e)
        return {}
    out = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        code = line.split("=")[0].replace("var hq_str_", "").strip()
        f = line.split('"')[1].split(",") if '"' in line else []
        if len(f) < 10:
            continue
        if code.startswith("nf_"):
            price = _num(f[8])
            out[code] = {"price": price, "prev": _num(f[10]), "time": f[1], "date": f[17] if len(f) > 17 else ""}
        elif code.startswith("hf_"):
            out[code] = {"price": _num(f[0]), "prev": _num(f[7]), "time": f[6], "date": f[12] if len(f) > 12 else ""}
        if code in out and not out[code]["price"]:
            del out[code]
    return out


def today_str() -> str:
    return datetime.now().date().isoformat()


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)
