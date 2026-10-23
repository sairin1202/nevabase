"""Markets are registered in sites.json (like nevatown's homepage/hub/sites.json); each has markets/<key>/market.py."""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache

from .config import DATA_DIR, ROOT, SITES_FILE
from .spec import Market
from .store import Store


def sites() -> list[dict]:
    return json.loads(SITES_FILE.read_text("utf-8"))


def market_sites() -> list[dict]:
    return [s for s in sites() if s.get("kind") == "market"]


@lru_cache(maxsize=None)
def load(key: str) -> Market:
    path = ROOT / "markets" / key / "market.py"
    spec = importlib.util.spec_from_file_location(f"market_{key}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MARKET


def data_dir(key: str):
    d = DATA_DIR / key
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache(maxsize=None)
def store(key: str) -> Store:
    return Store(data_dir(key) / "market.sqlite3")
