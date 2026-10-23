"""nevacore: the framework every nevabase market (煤炭, 咖啡, later A 股 / 美股) is built on.

Like nevatown's framework, work is split in two phases that hand over through one file, the logic pack:

    offline (gen.py, slow, reviewable)                online (app.py, fast, deterministic)
    LLM proposes relations between series  ──pack──▶  code computes every number from market data:
    regression test on history gates publish          复盘 review, 回测 backtest, 虚拟交易 paper trading

No model is called while serving a request; the LLM only writes candidate relations and prose offline.
"""
