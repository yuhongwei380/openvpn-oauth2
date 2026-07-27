#!/usr/bin/env python3
"""Small, dependency-free administration API for the OpenVPN OAuth2 image."""

from __future__ import annotations

import base64
import binascii
import csv
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import subprocess
import tempfile
import time
import hashlib
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import geoip_service
import monitors
import runtime_config
import storage


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATUS_PATH = Path(os.getenv("OPENVPN_STATUS_PATH", "/run/openvpn/openvpn-status.log"))
CLIENT_DIR = Path(os.getenv("OPENVPN_CLIENT_CONFIG_DIR", "/etc/openvpn/client-configs"))
STARTED_AT = time.time()
CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CERT_DIR = Path(os.getenv("OPENVPN_CERT_DIR", "/etc/openvpn/certs"))
DOC_PATH = Path(os.getenv("WEB_UI_DOCUMENT_PATH", "/opt/openvpn-admin/README.md"))
TRAFFIC_MONITOR = None
GEOIP = None


def _number(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _iso_time(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.isdigit():
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%a %b %d %H:%M:%S %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return value


def parse_openvpn_status(content: str) -> dict:
    """Parse OpenVPN status format 2/3 and the older human-readable format."""
    clients: list[dict] = []
    updated_at = ""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in lines:
        fields = line.split(",")
        if fields[0] == "TIME" and len(fields) >= 3:
            updated_at = _iso_time(fields[2])
        elif fields[0] == "CLIENT_LIST" and len(fields) >= 8:
            connected = fields[8] if len(fields) > 8 else fields[7]
            clients.append(
                {
                    "username": fields[1],
                    "realAddress": fields[2],
                    "virtualAddress": fields[3],
                    "virtualIpv6Address": fields[4] if len(fields) > 10 else "",
                    "bytesReceived": _number(fields[5] if len(fields) > 10 else fields[4]),
                    "bytesSent": _number(fields[6] if len(fields) > 10 else fields[5]),
                    "connectedAt": _iso_time(connected),
                }
            )
    if clients:
        return {"updatedAt": updated_at, "clients": clients}

    in_clients = False
    for line in lines:
        if line == "OpenVPN CLIENT LIST":
            in_clients = True
            continue
        if line.startswith("Updated,"):
            updated_at = _iso_time(line.split(",", 1)[1])
            continue
        if line.startswith("ROUTING TABLE"):
            in_clients = False
        if in_clients and not line.startswith(("Common Name,", "Updated,")) and len(line.split(",")) >= 5:
            fields = line.split(",")
            clients.append(
                {
                    "username": fields[0],
                    "realAddress": fields[1],
                    "virtualAddress": "",
                    "virtualIpv6Address": "",
                    "bytesReceived": _number(fields[2]),
                    "bytesSent": _number(fields[3]),
                    "connectedAt": _iso_time(fields[4]),
                }
            )
    return {"updatedAt": updated_at, "clients": clients}


def read_status() -> dict:
    try:
        parsed = parse_openvpn_status(STATUS_PATH.read_text(encoding="utf-8", errors="replace"))
        parsed["available"] = True
        parsed["ageSeconds"] = max(0, int(time.time() - STATUS_PATH.stat().st_mtime))
        return parsed
    except OSError:
        return {"available": False, "updatedAt": "", "ageSeconds": None, "clients": []}


def public_config() -> dict:
    settings = runtime_config.load()
    server = settings["server"]
    networking = settings["networking"]
    oauth2 = settings["oauth2"]
    public = runtime_config.public_settings()
    return {
        "server": {
            **server,
            "ipv6Enabled": networking["ipv6Enabled"],
            "ipv6Network": networking["ipv6Network"],
        },
        "oauth2": {
            "issuer": oauth2["issuer"],
            "clientId": oauth2["clientId"],
            "baseUrl": oauth2["baseUrl"],
            "configured": bool(
                oauth2["issuer"]
                and oauth2["clientId"]
                and public["secrets"]["clientSecret"]["configured"]
            ),
        },
    }


def list_profiles() -> list[dict]:
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    profiles = []
    for path in sorted(CLIENT_DIR.glob("*.ovpn"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        profiles.append(
            {
                "name": path.stem,
                "filename": path.name,
                "size": stat.st_size,
                "updatedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    return profiles


def certificate_status() -> list[dict]:
    files = {"ca": "ca.crt", "certificate": "server.crt", "privateKey": "server.key", "dh": "dh.pem"}
    present = {key: (CERT_DIR / name).is_file() for key, name in files.items()}
    metadata = {}
    certificate = CERT_DIR / files["certificate"]
    if certificate.is_file():
        try:
            output = subprocess.run(
                ["openssl", "x509", "-in", str(certificate), "-noout", "-subject", "-issuer", "-dates"],
                capture_output=True, check=True, text=True, timeout=5,
            ).stdout
            for line in output.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    metadata[key.strip()] = value.strip()
        except subprocess.SubprocessError:
            pass
    return [{
        "name": "default",
        "ready": all(present.values()),
        "files": present,
        "assignedInstances": 1,
        "subject": metadata.get("subject", ""),
        "issuer": metadata.get("issuer", ""),
        "notBefore": metadata.get("notBefore", ""),
        "notAfter": metadata.get("notAfter", ""),
    }]


def update_certificate_bundle(payload: dict) -> dict:
    allowed = {
        "ca": ("ca.crt", ["openssl", "x509", "-in", "{path}", "-noout"]),
        "certificate": ("server.crt", ["openssl", "x509", "-in", "{path}", "-noout"]),
        "privateKey": ("server.key", ["openssl", "pkey", "-in", "{path}", "-check", "-noout"]),
        "dh": ("dh.pem", ["openssl", "dhparam", "-in", "{path}", "-check", "-noout"]),
    }
    files = payload.get("files") or {}
    if not files or any(key not in allowed for key in files):
        raise ValueError("请选择有效的证书材料")
    decoded = {}
    total = 0
    for key, value in files.items():
        try:
            content = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(f"{key} 文件编码无效") from None
        total += len(content)
        if not content or total > 2 * 1024 * 1024:
            raise ValueError("证书材料为空或总大小超过 2 MB")
        decoded[key] = content
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CERT_DIR) as directory:
        staged = {}
        for key, content in decoded.items():
            filename, command = allowed[key]
            path = Path(directory) / filename
            path.write_bytes(content)
            check = [str(path) if value == "{path}" else value for value in command]
            try:
                subprocess.run(check, check=True, capture_output=True, timeout=10)
            except subprocess.SubprocessError:
                raise ValueError(f"{filename} 无法通过 OpenSSL 校验") from None
            staged[key] = path
        for key, path in staged.items():
            filename = allowed[key][0]
            os.replace(path, CERT_DIR / filename)
            os.chmod(CERT_DIR / filename, 0o600 if key == "privateKey" else 0o644)
    return certificate_status()[0]


def branding_settings() -> dict:
    return {
        "brandName": "OpenVPN",
        "productName": "OAuth2 Control",
        "title": "OpenVPN 控制台",
        "description": "OAuth2 身份认证与 VPN 运维工作台",
        "copyright": "",
        **(storage.get_setting("branding", {}) or {}),
    }


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError, binascii.Error):
        return False


def security_settings() -> dict:
    fallback = {
        "authEnabled": os.getenv("WEB_UI_AUTH_ENABLED", "true").lower() == "true",
        "username": os.getenv("WEB_UI_USERNAME", "admin"),
        "passwordHash": "",
        "source": "bootstrap",
    }
    try:
        persisted = storage.get_setting("console_security", None)
    except OSError:
        persisted = None
    if not isinstance(persisted, dict):
        return fallback
    return {**fallback, **persisted, "source": "web"}


def public_security_settings() -> dict:
    settings = security_settings()
    return {
        "authEnabled": bool(settings["authEnabled"]),
        "username": settings["username"],
        "passwordConfigured": bool(
            settings.get("passwordHash") or os.getenv("WEB_UI_PASSWORD", "")
        ),
        "source": settings["source"],
    }


def save_security_settings(payload: dict) -> dict:
    current = security_settings()
    username = str(payload.get("username", current["username"])).strip()
    password = str(payload.get("password", ""))
    if not re.fullmatch(r"[A-Za-z0-9._@-]{3,64}", username):
        raise ValueError("控制台账号须为 3–64 位字母、数字或 . _ @ -")
    if password and len(password) < 10:
        raise ValueError("新密码至少需要 10 个字符")
    value = {
        "authEnabled": bool(payload.get("authEnabled", current["authEnabled"])),
        "username": username,
        "passwordHash": _password_hash(password) if password else current.get("passwordHash", ""),
    }
    if value["authEnabled"] and not value["passwordHash"] and not os.getenv("WEB_UI_PASSWORD"):
        raise ValueError("启用控制台认证时必须设置密码")
    storage.set_setting("console_security", value)
    return public_security_settings()


def audit_settings() -> dict:
    defaults = {
        "trafficEnabled": os.getenv("ENABLE_TRAFFIC_AUDIT", "true").lower() == "true",
    }
    return {**defaults, **(storage.get_setting("audit", {}) or {})}


def settings_payload() -> dict:
    return {
        "runtime": runtime_config.public_settings(),
        "audit": audit_settings(),
        "console": public_security_settings(),
        "restartRequired": False,
    }


def query_since(query: dict) -> int:
    range_value = (query.get("range") or ["24h"])[0]
    seconds = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}.get(range_value, 86400)
    return int(time.time()) - seconds


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "OpenVPN-OAuth2-WebUI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web-ui] {self.address_string()} {fmt % args}", flush=True)

    def _authenticated(self) -> bool:
        settings = security_settings()
        expected_user = settings["username"]
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
            username, password = raw.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        if not hmac.compare_digest(username, expected_user):
            return False
        if settings.get("passwordHash"):
            return _password_matches(password, settings["passwordHash"])
        return hmac.compare_digest(password, os.getenv("WEB_UI_PASSWORD", "admin"))

    def _require_auth(self) -> bool:
        auth_enabled = security_settings()["authEnabled"]
        if not auth_enabled or self.path == "/api/health" or self._authenticated():
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="OpenVPN Control Center"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _csv(self, filename: str, headers: list[str], rows: list[list]) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        writer.writerows(rows)
        body = ("\ufeff" + buffer.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, max_length: int = 16_384) -> dict:
        length = _number(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_length:
            raise ValueError("请求内容无效")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if not self._require_auth():
            return
        parsed_url = urlparse(self.path)
        route = parsed_url.path
        query = parse_qs(parsed_url.query)
        if route == "/api/health":
            self._json({"ok": True})
        elif route == "/api/status":
            status = read_status()
            self._json(
                {
                    "service": "online",
                    "uptimeSeconds": int(time.time() - STARTED_AT),
                    "connections": len(status["clients"]),
                    "bytesReceived": sum(item["bytesReceived"] for item in status["clients"]),
                    "bytesSent": sum(item["bytesSent"] for item in status["clients"]),
                    "status": status,
                    "config": public_config(),
                }
            )
        elif route == "/api/connections":
            self._json(read_status())
        elif route == "/api/profiles":
            self._json({"profiles": list_profiles()})
        elif route == "/api/instance":
            current = read_status()
            self._json({
                "name": "default",
                "state": "running",
                "locked": False,
                "online": len(current["clients"]),
                "statusAvailable": current["available"],
                "config": public_config()["server"],
                "certificate": certificate_status()[0],
                "management": "container",
            })
        elif route == "/api/audit/connections":
            events = storage.query_connection_events(
                (query.get("keyword") or [""])[0],
                (query.get("event") or [""])[0],
                query_since(query),
            )
            self._json({"events": events})
        elif route == "/api/audit/connections.csv":
            events = storage.query_connection_events(
                (query.get("keyword") or [""])[0],
                (query.get("event") or [""])[0],
                query_since(query),
                1000,
            )
            self._csv(
                "connection-audit.csv",
                ["time", "event", "user", "source", "vpn_ip", "received", "sent", "duration_seconds"],
                [[item["timestamp"], item["event"], item["username"], item["realAddress"], item["virtualAddress"],
                  item["bytesReceived"], item["bytesSent"], item["durationSeconds"]] for item in events],
            )
        elif route == "/api/audit/traffic":
            dashboard = storage.traffic_dashboard(
                (query.get("keyword") or [""])[0], query_since(query)
            )
            dashboard["capture"] = TRAFFIC_MONITOR.status() if TRAFFIC_MONITOR else {
                "state": "waiting", "message": "采集器正在启动", "enabled": True
            }
            dashboard["geoip"] = {
                "state": GEOIP.state if GEOIP else "unavailable",
                "message": GEOIP.message if GEOIP else "GeoIP 服务正在启动",
                "countries": GEOIP.aggregate(dashboard["recent"]) if GEOIP else [],
                "countryLevelOnly": True,
            }
            self._json(dashboard)
        elif route == "/api/audit/targets":
            self._json({"targets": storage.traffic_targets(
                (query.get("keyword") or [""])[0], query_since(query)
            )})
        elif route == "/api/audit/traffic.csv":
            records = storage.traffic_dashboard(
                (query.get("keyword") or [""])[0], query_since(query), 1000
            )["recent"]
            self._csv(
                "traffic-audit.csv",
                ["time", "user", "vpn_ip", "domain", "target_ip", "port", "protocol", "upload", "download", "connections"],
                [[item["timestamp"], item["username"], item["vpnIp"], item["domain"], item["targetIp"],
                  item["targetPort"], item["protocol"], item["uploadBytes"], item["downloadBytes"], item["connections"]]
                 for item in records],
            )
        elif route == "/api/geoip":
            self._json({
                "settings": GEOIP.settings() if GEOIP else geoip_service.DEFAULTS,
                "state": GEOIP.state if GEOIP else "unavailable",
                "message": GEOIP.message if GEOIP else "GeoIP 服务正在启动",
            })
        elif route == "/api/certificates":
            self._json({"certificates": certificate_status()})
        elif route == "/api/branding":
            self._json(branding_settings())
        elif route == "/api/settings":
            self._json(settings_payload())
        elif route == "/api/docs":
            try:
                content = DOC_PATH.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = "# 本地文档\n\nREADME 文档尚未打包到镜像。"
            self._json({"content": content})
        elif route.startswith("/api/profiles/") and route.endswith("/download"):
            filename = unquote(route[len("/api/profiles/") : -len("/download")]).strip("/")
            self._download_profile(filename)
        elif route.startswith("/api/"):
            self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        else:
            self._serve_static(route)

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        route = urlparse(self.path).path
        if route != "/api/profiles":
            self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            name = str(payload.get("name", "")).strip()
            host = str(payload.get("remoteHost", "")).strip()
            if not CLIENT_NAME_RE.fullmatch(name):
                raise ValueError("名称只能包含字母、数字、点、短横线和下划线，最长 64 位")
            if not host or len(host) > 253 or any(char.isspace() for char in host):
                raise ValueError("服务器地址无效")
            subprocess.run(
                ["/usr/local/bin/generate-client-config.sh", name, str(CLIENT_DIR), host],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            profile = next(item for item in list_profiles() if item["name"] == name)
            self._json({"profile": profile}, HTTPStatus.CREATED)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (subprocess.SubprocessError, StopIteration) as exc:
            self._json({"error": f"生成客户端配置失败：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PUT(self) -> None:
        if not self._require_auth():
            return
        route = urlparse(self.path).path
        try:
            payload = self._read_json(3 * 1024 * 1024 if route == "/api/certificates/default" else 16_384)
            if route == "/api/geoip":
                if GEOIP is None:
                    raise ValueError("GeoIP 服务尚未启动")
                self._json({"settings": GEOIP.save(payload)})
            elif route == "/api/branding":
                allowed = ("brandName", "productName", "title", "description", "copyright")
                value = {key: str(payload.get(key, "")).strip()[:160] for key in allowed}
                if not value["brandName"] or not value["title"]:
                    raise ValueError("品牌名称和页面标题不能为空")
                storage.set_setting("branding", value)
                self._json(value)
            elif route == "/api/settings":
                runtime = runtime_config.save(payload.get("runtime") or {})
                audit = {
                    "trafficEnabled": bool(
                        (payload.get("audit") or {}).get("trafficEnabled", True)
                    )
                }
                storage.set_setting("audit", audit)
                if TRAFFIC_MONITOR:
                    TRAFFIC_MONITOR.configure(audit["trafficEnabled"])
                console = save_security_settings(payload.get("console") or {})
                self._json({
                    "runtime": runtime,
                    "audit": audit,
                    "console": console,
                    "restartRequired": True,
                })
            elif route == "/api/certificates/default":
                self._json({"certificate": update_certificate_bundle(payload)})
            else:
                self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _download_profile(self, filename: str) -> None:
        if not filename.endswith(".ovpn") or not CLIENT_NAME_RE.fullmatch(filename[:-5]):
            self._json({"error": "文件名无效"}, HTTPStatus.BAD_REQUEST)
            return
        path = CLIENT_DIR / filename
        if not path.is_file():
            self._json({"error": "配置文件不存在"}, HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-openvpn-profile")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_static(self, route: str) -> None:
        if route in ("", "/"):
            route = "/index.html"
        relative = Path(unquote(route).lstrip("/"))
        if ".." in relative.parts:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = STATIC_DIR / relative
        if not path.is_file():
            path = STATIC_DIR / "index.html"
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    global TRAFFIC_MONITOR, GEOIP
    storage.initialize()
    connection_monitor = monitors.ConnectionMonitor(read_status)
    TRAFFIC_MONITOR = monitors.TrafficMonitor(read_status)
    GEOIP = geoip_service.GeoIPService()
    connection_monitor.start()
    TRAFFIC_MONITOR.start()
    GEOIP.start()
    listen = os.getenv("WEB_UI_LISTEN", "0.0.0.0:8080")
    host, port = listen.rsplit(":", 1)
    if os.getenv("WEB_UI_PASSWORD", "admin") == "admin":
        print("[web-ui] warning: WEB_UI_PASSWORD uses the default value; change it before exposing the service", flush=True)
    server = ThreadingHTTPServer((host, int(port)), AdminHandler)
    print(f"[web-ui] listening on http://{host or '0.0.0.0'}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
