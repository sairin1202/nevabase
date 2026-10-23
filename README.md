# nevabase

One market per commodity (煤炭 coal, 咖啡 coffee; A 股 / 美股 next). Each market collects the data around its
instruments, tests stated relations between those series on history, and turns the ones that hold into
**复盘** (daily review), **回测** (backtests) and **虚拟交易** (paper trading). Built like nevatown: a shared framework,
one service per market, a hub that lists them.

```
core/nevacore/      framework
  spec.py           define_market: instruments, series, seed relations, graph layout
  sources.py        AkShare/Sina (domestic contracts, spot & basis), Yahoo/Sina (foreign), Frankfurter (FX), Open-Meteo (weather)
  sync.py           idempotent sync; domestic futures are chained from single contracts by open interest (no roll returns)
  analytics.py      aligned frame, relation features, evidence (leading: in/out of sample), comove (same-period), backtest
  pack.py           the logic pack: relations + evidence + regression test; packs/<version>.json, `current`
  gen.py            offline: LLM proposes relations → in-sample test → regression gate → publish; review summaries
  review.py         复盘 of one trading day
  paper.py          paper accounts: manual fills at Sina realtime prices, or the pack rebalances them after each close
  app.py            create_market(key): page + /<key>/api/*, hourly sync loop
markets/<key>/market.py   one file per market
hub/app.py          nevabase.com: homepage, login, legal pages, /api/markets
frontend/           shared static (style.css, market.css, app.js, auth.js, charts.js, market.js, market.html)
sites.json          registry: key, path, port
deploy/             systemd units (nevabase, nevabase-market@, nevabase-daily@ + timers) and the Caddy block
```

Run locally: `./run.sh hub`, `./run.sh coal`, `./run.sh coffee`. CLI: `PYTHONPATH=core .venv/bin/python -m nevacore.cli
{sync|pack|gen|review|agent|daily} <market>`.

Adding a market: write `markets/<key>/market.py`, add it to `sites.json` (new port), add a `handle` to the Caddy block,
`systemctl enable --now nevabase-market@<key>` and a `nevabase-daily-<key>.timer`, and list it in `frontend/js/app.js`.

Rules: no look-ahead (features use data dated ≤ t; positions decided at close t earn t+1); the online services never
call an LLM; every number shown is computed from stored data. The old game-industry search product is archived at
`/home/ubuntu/archive/nevabase-games-20261023`.
