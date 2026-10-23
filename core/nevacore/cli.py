"""nevabase command line.

    python -m nevacore.cli sync <market>            fetch / refresh all data of a market
    python -m nevacore.cli gen <market> [--dry]     offline: propose relations with the LLM, regression-test, publish a pack
    python -m nevacore.cli pack <market>            rebuild the pack from the spec's seed relations only (no LLM)
    python -m nevacore.cli review <market> [date]   write the AI summary of a day's review (numbers come from code)
    python -m nevacore.cli agent <market>           let the logic pack rebalance accounts in agent mode
    python -m nevacore.cli daily <market>           the timer's job: sync, weekly gen (Mondays or when stale), review summary
"""
from __future__ import annotations

import json
import logging
import sys

from . import registry


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, key, rest = argv[0], argv[1], argv[2:]
    m, st = registry.load(key), registry.store(key)
    if cmd == "sync":
        from .sync import sync_market
        print(json.dumps(sync_market(m, st), ensure_ascii=False, indent=1))
    elif cmd == "gen":
        from .gen import generate
        print(json.dumps(generate(m, st, dry="--dry" in rest), ensure_ascii=False, indent=1)[:4000])
    elif cmd == "pack":
        from .gen import seed_pack
        print(json.dumps(seed_pack(m, st), ensure_ascii=False, indent=1)[:4000])
    elif cmd == "review":
        from .gen import write_review
        print(json.dumps(write_review(m, st, rest[0] if rest else None), ensure_ascii=False, indent=1))
    elif cmd == "agent":
        from .paper import run_agents
        print(json.dumps(run_agents(m, st), ensure_ascii=False, indent=1))
    elif cmd == "daily":
        from datetime import date, datetime, timedelta
        from . import pack as P
        from .gen import generate, write_review
        from .sync import sync_market
        out = {"sync": sync_market(m, st)}
        cur = P.current(m)
        last_gen = max((h["createdAt"] for h in P.history(m) if h.get("origin") == "gen"), default="")
        stale = not last_gen or datetime.fromisoformat(last_gen).date() < date.today() - timedelta(days=7)
        if cur is None or date.today().weekday() == 0 or stale:
            out["gen"] = generate(m, st)
        try:
            out["review"] = write_review(m, st)
        except Exception as e:
            out["review"] = {"error": str(e)}
        from .paper import run_agents
        out["agents"] = run_agents(m, st)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:6000])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
