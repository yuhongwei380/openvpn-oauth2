"""Client for the private OpenVPN instance controller."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONTROL_URL = os.getenv("OPENVPN_CONTROL_URL", "http://127.0.0.1:9090").rstrip("/")
CONTROL_TOKEN = os.getenv("OPENVPN_CONTROL_TOKEN", "")


def request(action: str = "status", timeout: float = 1) -> dict:
    if action not in ("status", "start", "stop", "restart"):
        raise ValueError("unsupported instance action")
    if not CONTROL_TOKEN:
        return {
            "controller": "unavailable",
            "state": "unknown",
            "desiredState": "unknown",
            "message": "OPENVPN_CONTROL_TOKEN is not configured",
        }
    method = "GET" if action == "status" else "POST"
    target = f"{CONTROL_URL}/{action}"
    request_value = Request(
        target,
        method=method,
        headers={
            "Authorization": f"Bearer {CONTROL_TOKEN}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request_value, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {
            "controller": "unavailable",
            "state": "unknown",
            "desiredState": "unknown",
            "message": str(exc),
        }
