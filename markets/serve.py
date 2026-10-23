"""uvicorn entry for one market: NEVA_MARKET=coal uvicorn markets.serve:app"""
import os

from nevacore.app import create_market

app = create_market(os.environ["NEVA_MARKET"])
