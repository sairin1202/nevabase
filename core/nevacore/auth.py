"""Firebase Authentication: the hub signs people in with the Firebase web SDK; every service verifies the ID token itself."""
from __future__ import annotations

import json
import logging
import os
import threading

from fastapi import HTTPException, Request

from .config import FIREBASE_CREDENTIALS, FIREBASE_CREDENTIALS_JSON

log = logging.getLogger("nevacore.auth")
_lock = threading.Lock()
_app = None
_init_error: str | None = None


def _init():
    """Initialise the Admin SDK once. Returns None (and remembers why) if credentials are missing."""
    global _app, _init_error
    if _app is not None or _init_error is not None:
        return _app
    with _lock:
        if _app is not None or _init_error is not None:
            return _app
        try:
            import firebase_admin
            from firebase_admin import credentials
        except ImportError:
            _init_error = "firebase-admin is not installed (pip install firebase-admin)."
            log.warning(_init_error)
            return None
        try:
            if FIREBASE_CREDENTIALS_JSON:
                cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
            elif FIREBASE_CREDENTIALS and os.path.exists(FIREBASE_CREDENTIALS):
                cred = credentials.Certificate(FIREBASE_CREDENTIALS)
            else:
                _init_error = f"Firebase service account not found at {FIREBASE_CREDENTIALS} (set NEVA_FIREBASE_CREDENTIALS)."
                log.warning(_init_error)
                return None
            _app = firebase_admin.initialize_app(cred)
            log.info("firebase auth enabled for project %s", cred.project_id)
        except Exception as e:  # bad JSON / key
            _init_error = f"Firebase credentials could not be loaded: {e}"
            log.warning(_init_error)
    return _app


def enabled() -> bool:
    return _init() is not None


def verify(id_token: str) -> dict:
    """Verify a Firebase ID token; returns the decoded claims or raises 401."""
    if _init() is None:
        raise HTTPException(503, {"error": "Login is not configured on this server. " + (_init_error or "")})
    from firebase_admin import auth as fb_auth
    try:
        return fb_auth.verify_id_token(id_token, check_revoked=False)
    except fb_auth.ExpiredIdTokenError:
        raise HTTPException(401, {"error": "Session expired. Please sign in again."})
    except (fb_auth.InvalidIdTokenError, ValueError) as e:
        raise HTTPException(401, {"error": f"Invalid login token: {e}"})
    except Exception as e:  # network / cert fetch problems
        log.exception("token verification failed")
        raise HTTPException(503, {"error": f"Could not verify login: {e}"})


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        if tok and tok.count(".") == 2:  # Firebase ID tokens are JWTs
            return tok
    return None


class User:
    def __init__(self, claims: dict):
        self.uid: str = claims["uid"]
        self.email: str | None = claims.get("email")
        self.name: str | None = claims.get("name")
        self.picture: str | None = claims.get("picture")
        self.provider: str = (claims.get("firebase") or {}).get("sign_in_provider", "")
        self.email_verified: bool = bool(claims.get("email_verified"))

    def to_dict(self) -> dict:
        return {"uid": self.uid, "email": self.email, "name": self.name, "picture": self.picture,
                "provider": self.provider, "emailVerified": self.email_verified}


def current_user(request: Request) -> User:
    """FastAPI dependency: requires `Authorization: Bearer <Firebase ID token>`."""
    tok = _bearer(request)
    if not tok:
        raise HTTPException(401, {"error": "Sign in required.", "code": "auth_required"})
    return User(verify(tok))


def optional_user(request: Request) -> User | None:
    tok = _bearer(request)
    return User(verify(tok)) if tok else None
