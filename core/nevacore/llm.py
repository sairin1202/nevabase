"""OpenAI-compatible chat completions (Nevatoken relay). Offline generation only; the online services never call it."""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT

log = logging.getLogger("nevacore.llm")


def enabled() -> bool:
    return bool(LLM_API_KEY)


def chat(system: str, user: str, *, temperature: float = 0.4, retries: int = 3) -> str:
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not set")
    body = {"model": LLM_MODEL, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    last = None
    for i in range(retries):
        try:
            r = httpx.post(f"{LLM_BASE_URL}/chat/completions", json=body, timeout=LLM_TIMEOUT,
                           headers={"Authorization": f"Bearer {LLM_API_KEY}"})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except Exception as e:
            last = e
            log.warning("llm attempt %d failed: %s", i + 1, e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"LLM failed: {last}")


def json_block(text: str):
    """The first JSON value in a reply (models like to wrap it in ```json fences)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    start = min([i for i in (raw.find("["), raw.find("{")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON in reply")
    return json.JSONDecoder().raw_decode(raw[start:])[0]
