"""Runtime configuration shared by the hub and every market service (environment overridable)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("NEVA_DATA_DIR", ROOT / "data"))
FRONTEND_DIR = Path(os.environ.get("NEVA_FRONTEND_DIR", ROOT / "frontend"))
SITES_FILE = ROOT / "sites.json"

ADMIN_TOKEN = os.environ.get("NEVA_ADMIN_TOKEN", "")

# Offline generation only (gen.py): OpenAI-compatible chat completions through the Nevatoken relay.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://nevatoken.com/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "MaaS_Deepseek_V4_pro_20260813")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))

# Market services re-sync their data on this interval (seconds); every fetch is an idempotent upsert.
SYNC_INTERVAL = int(os.environ.get("NEVA_SYNC_INTERVAL", "3600"))
# Market services skip the background sync loop when this is 0 (tests, local runs on a copy of the data).
SYNC_ENABLED = os.environ.get("NEVA_SYNC", "1") != "0"

FIREBASE_CREDENTIALS = os.environ.get("NEVA_FIREBASE_CREDENTIALS", str(ROOT / "secrets" / "firebase-service-account.json"))
FIREBASE_CREDENTIALS_JSON = os.environ.get("NEVA_FIREBASE_CREDENTIALS_JSON", "")
FIREBASE_WEB_CONFIG = {
    "apiKey": os.environ.get("NEVA_FIREBASE_API_KEY", "AIzaSyAQZDSF5AntmV00II325eQbfBwI3Y7Bm70"),
    "authDomain": os.environ.get("NEVA_FIREBASE_AUTH_DOMAIN", "nevabase-eca52.firebaseapp.com"),
    "projectId": os.environ.get("NEVA_FIREBASE_PROJECT_ID", "nevabase-eca52"),
    "storageBucket": os.environ.get("NEVA_FIREBASE_STORAGE_BUCKET", "nevabase-eca52.firebasestorage.app"),
    "messagingSenderId": os.environ.get("NEVA_FIREBASE_SENDER_ID", "210333871701"),
    "appId": os.environ.get("NEVA_FIREBASE_APP_ID", "1:210333871701:web:c637478cdb7551058daedc"),
    "measurementId": os.environ.get("NEVA_FIREBASE_MEASUREMENT_ID", "G-ZPGPNK2T68"),
}
