import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import Request
from fastapi.responses import JSONResponse


ALLOWED_OPS_ROLES = {"super_admin", "admin", "operator", "analyst"}
JWKS_CACHE_TTL_SECONDS = 300
_jwks_cache: Dict[str, Any] = {"keys": {}, "fetched_at": 0.0}
_jwks_lock = asyncio.Lock()


def load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()


def get_jwks_url() -> str:
    jwks_url = os.getenv("JWKS_URL", "").strip()
    if not jwks_url:
        raise RuntimeError("JWKS_URL is not configured")
    return jwks_url


def get_expected_issuer() -> str:
    return os.getenv("JWT_ISSUER", "air-quality-api")


def get_expected_audience() -> str:
    return os.getenv("JWT_AUDIENCE", "air-quality-clients")


def extract_bearer_token(auth_header: Optional[str]) -> str:
    if not auth_header:
        raise ValueError("Bearer token is required")

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ValueError("Invalid authorization header")

    return token.strip()


async def fetch_jwks(force_refresh: bool = False) -> Dict[str, Any]:
    now = time.time()
    if (
        not force_refresh
        and _jwks_cache["keys"]
        and now - _jwks_cache["fetched_at"] < JWKS_CACHE_TTL_SECONDS
    ):
        return _jwks_cache["keys"]

    async with _jwks_lock:
        now = time.time()
        if (
            not force_refresh
            and _jwks_cache["keys"]
            and now - _jwks_cache["fetched_at"] < JWKS_CACHE_TTL_SECONDS
        ):
            return _jwks_cache["keys"]

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(get_jwks_url())
            response.raise_for_status()
            payload = response.json()

        keys: Dict[str, Any] = {}
        for jwk in payload.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))

        if not keys:
            raise RuntimeError("No signing keys published by JWKS endpoint")

        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = time.time()
        return keys


async def verify_access_token(token: str) -> Dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid token header") from exc

    kid = header.get("kid")
    if not kid:
        raise ValueError("Missing token kid")

    keys = await fetch_jwks()
    key = keys.get(kid)
    if key is None:
        key = (await fetch_jwks(force_refresh=True)).get(kid)
    if key is None:
        raise ValueError("Unknown signing key")

    try:
        return jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=get_expected_audience(),
            issuer=get_expected_issuer(),
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid token") from exc


async def protect_ops_request(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    if not request.url.path.startswith("/api/v1/ops"):
        return await call_next(request)

    try:
        token = extract_bearer_token(request.headers.get("authorization"))
        claims = await verify_access_token(token)
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=401, content={"detail": str(exc)})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"detail": "Unable to fetch JWKS"})

    roles = set(claims.get("roles") or [])
    if not roles.intersection(ALLOWED_OPS_ROLES):
        return JSONResponse(status_code=403, content={"detail": "Insufficient role"})

    request.state.auth = claims
    return await call_next(request)
