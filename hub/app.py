"""nevabase.com hub: the homepage that lists every market, sign-in, legal pages, and the shared static assets.

Markets run as their own services (sites.json); the hub only reads their /api/summary for the homepage cards.
"""
from __future__ import annotations

import asyncio
import re
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from nevacore import auth, registry
from nevacore.config import FIREBASE_WEB_CONFIG, FRONTEND_DIR

app = FastAPI(title="nevabase", docs_url=None, redoc_url=None, openapi_url=None)
PAGES = {"": "index.html", "login": "login.html", "privacy": "privacy.html", "terms": "terms.html"}
RETIRED = {"games", "monitor", "github", "console", "dashboard", "docs", "pricing"}   # the 2026-09/10 search product
ASSET_RE = re.compile(r"(/static/(?:css|js)/[\w./-]+)")
_cache: dict[str, tuple[float, dict]] = {}


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.get("/api/auth/config")
def auth_config():
    return {"enabled": auth.enabled(), "firebase": FIREBASE_WEB_CONFIG}


@app.get("/api/auth/me")
def auth_me(request: Request):
    return auth.current_user(request).to_dict()


async def _summary(client: httpx.AsyncClient, site: dict) -> dict:
    hit = _cache.get(site["key"])
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    try:
        r = await client.get(f"http://127.0.0.1:{site['port']}/{site['key']}/api/summary", timeout=8)
        data = {**r.json(), "online": r.status_code == 200}
    except Exception:
        data = {"key": site["key"], "name": site["zh"], "nameEn": site["en"], "online": False, "ready": False}
    data["group"] = site.get("group")
    _cache[site["key"]] = (time.time(), data)
    return data


@app.get("/api/markets")
async def markets():
    async with httpx.AsyncClient() as client:
        out = await asyncio.gather(*[_summary(client, s) for s in registry.market_sites()])
    return {"markets": out}


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/favicon.svg", methods=["GET", "HEAD"], include_in_schema=False)
def favicon():
    return FileResponse(FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")


@app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
def robots():
    return FileResponse(FRONTEND_DIR / "robots.txt", media_type="text/plain")


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
def sitemap():
    return FileResponse(FRONTEND_DIR / "sitemap.xml", media_type="application/xml")


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/{page}", methods=["GET", "HEAD"], include_in_schema=False)
def page(page: str = ""):
    key = page.strip("/")
    if key in RETIRED:
        return RedirectResponse("/", status_code=302)
    name = PAGES.get(key)
    if not name:
        raise HTTPException(404, {"error": "not found"})
    version = int(max(p.stat().st_mtime for p in FRONTEND_DIR.rglob("*") if p.is_file()))
    html = ASSET_RE.sub(rf"\1?v={version}", (FRONTEND_DIR / name).read_text("utf-8"))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
