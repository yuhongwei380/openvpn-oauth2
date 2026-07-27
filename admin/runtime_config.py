"""Persistent runtime configuration shared by the Web UI and entrypoint."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


SETTINGS_PATH = Path(
    os.getenv("OPENVPN_RUNTIME_SETTINGS_PATH", "/etc/openvpn/admin/runtime-settings.json")
)

DEFAULTS = {
    "server": {
        "remoteHost": "",
        "port": 1194,
        "protocol": "udp",
        "device": "tun",
        "network": "10.7.0.0",
        "netmask": "255.255.0.0",
        "dns": "",
        "cipher": "AES-256-GCM",
    },
    "networking": {
        "outboundInterface": "eth0",
        "ipv4Nat": True,
        "ipv6Enabled": False,
        "ipv6Network": "fd12:3456:789a::/64",
        "ipv6Route": "2000::/3",
        "ipv6Dns": "",
        "ipv6Nat": True,
        "ipv6InternalRoutes": ["", "", ""],
    },
    "certificates": {
        "generate": True,
        "forceRegenerate": False,
        "generateDefaultProfile": True,
    },
    "oauth2": {
        "issuer": "",
        "clientId": "",
        "baseUrl": "",
        "httpListen": ":9000",
        "openvpnAddress": "unix:///run/openvpn/server.sock",
    },
}

ENV_MAP = {
    ("server", "remoteHost"): "OVPN_REMOTE_HOST",
    ("server", "port"): "OVPN_PORT",
    ("server", "protocol"): "OVPN_PROTO",
    ("server", "device"): "OVPN_DEV",
    ("server", "network"): "OVPN_NETWORK",
    ("server", "netmask"): "OVPN_NETMASK",
    ("server", "dns"): "OVPN_DNS_IPV4",
    ("server", "cipher"): "OVPN_CIPHER",
    ("networking", "ipv4Nat"): "ENABLE_IPV4_NAT",
    ("networking", "outboundInterface"): "NAT_OUTBOUND_INTERFACE",
    ("networking", "ipv6Enabled"): "OVPN_IPV6_ENABLE",
    ("networking", "ipv6Network"): "OVPN_IPV6_NETWORK",
    ("networking", "ipv6Route"): "OVPN_IPV6_ROUTE",
    ("networking", "ipv6Dns"): "OVPN_DNS_IPV6",
    ("networking", "ipv6Nat"): "ENABLE_IPV6_NAT",
    ("certificates", "generate"): "GENERATE_CERTS",
    ("certificates", "forceRegenerate"): "FORCE_REGENERATE",
    ("certificates", "generateDefaultProfile"): "GENERATE_DEFAULT_CLIENT_CONFIG",
    ("oauth2", "issuer"): "OAUTH2_ISSUER",
    ("oauth2", "clientId"): "OAUTH2_CLIENT_ID",
    ("oauth2", "baseUrl"): "OAUTH2_HTTP_BASEURL",
    ("oauth2", "httpListen"): "OAUTH2_HTTP_LISTEN",
    ("oauth2", "openvpnAddress"): "OAUTH2_OPENVPN_ADDR",
}

SECRET_ENV_MAP = {
    "clientSecret": "OAUTH2_CLIENT_SECRET",
    "httpSecret": "OAUTH2_HTTP_SECRET",
    "managementPassword": "OAUTH2_OPENVPN_PASSWORD",
}
SECRET_DEFAULTS = {"clientSecret": "", "httpSecret": "", "managementPassword": "admin"}

SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
SAFE_DEVICE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,24}$")
SAFE_CIPHER_RE = re.compile(r"^[A-Za-z0-9_-]{3,48}$")


def _copy_defaults() -> dict:
    return json.loads(json.dumps(DEFAULTS))


def _env_bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _bootstrap_from_environment() -> dict:
    settings = _copy_defaults()
    for (section, key), env_name in ENV_MAP.items():
        if env_name not in os.environ:
            continue
        current = settings[section][key]
        value = os.environ[env_name]
        if isinstance(current, bool):
            value = _env_bool(value)
        elif isinstance(current, int):
            value = int(value)
        settings[section][key] = value
    settings["networking"]["ipv6InternalRoutes"] = [
        os.getenv(f"OVPN_IPV6_INT_NETWORK{index}", "") for index in range(3)
    ]
    return settings


def _merge_settings(payload: dict) -> dict:
    result = _copy_defaults()
    for section, defaults in DEFAULTS.items():
        candidate = payload.get(section, {})
        if isinstance(candidate, dict):
            for key in defaults:
                if key in candidate:
                    result[section][key] = candidate[key]
    return result


def _encryption_key() -> str:
    return os.getenv("CONFIG_ENCRYPTION_KEY", "")


def _openssl(value: str, decrypt: bool = False) -> str:
    key = _encryption_key()
    if not key:
        raise ValueError("缺少 CONFIG_ENCRYPTION_KEY，无法安全保存敏感配置")
    command = ["openssl", "enc", "-aes-256-cbc", "-a", "-A", "-pbkdf2", "-md", "sha256"]
    if decrypt:
        command.append("-d")
    environment = {**os.environ, "OPENVPN_SETTINGS_KEY": key}
    command.extend(["-pass", "env:OPENVPN_SETTINGS_KEY"])
    try:
        completed = subprocess.run(
            command,
            input=value,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            env=environment,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ValueError("敏感配置加密或解密失败") from exc
    return completed.stdout.strip()


def _read_document() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load() -> dict:
    document = _read_document()
    if document.get("settings"):
        return _merge_settings(document["settings"])
    return _bootstrap_from_environment()


def _secret_configured(document: dict, key: str) -> bool:
    return bool((document.get("secrets") or {}).get(key) or os.getenv(SECRET_ENV_MAP[key], ""))


def public_settings() -> dict:
    document = _read_document()
    return {
        **load(),
        "secrets": {
            key: {"configured": _secret_configured(document, key)}
            for key in SECRET_ENV_MAP
        },
        "encryptionReady": bool(_encryption_key()),
        "persisted": bool(document.get("settings")),
        "updatedAt": document.get("updatedAt"),
    }


def _validate_url(value: str, label: str, allow_empty: bool = True) -> str:
    value = str(value).strip()
    if not value and allow_empty:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{label}必须是有效的 HTTP(S) 地址")
    return value


def validate(payload: dict) -> dict:
    value = _merge_settings(payload)
    server = value["server"]
    server["remoteHost"] = str(server["remoteHost"]).strip()
    if server["remoteHost"] and not SAFE_HOST_RE.fullmatch(server["remoteHost"]):
        raise ValueError("公网地址只能包含域名、IP 和端口字符")
    server["port"] = int(server["port"])
    if not 1 <= server["port"] <= 65535:
        raise ValueError("OpenVPN 端口必须在 1–65535 之间")
    if server["protocol"] not in ("udp", "tcp-server"):
        raise ValueError("OpenVPN 协议无效")
    if not SAFE_DEVICE_RE.fullmatch(str(server["device"])):
        raise ValueError("隧道设备名称无效")
    if not SAFE_CIPHER_RE.fullmatch(str(server["cipher"])):
        raise ValueError("数据通道加密算法无效")
    try:
        ipv4 = ipaddress.IPv4Network(
            f"{server['network']}/{server['netmask']}", strict=False
        )
    except ValueError as exc:
        raise ValueError("IPv4 地址池或子网掩码无效") from exc
    server["network"] = str(ipv4.network_address)
    server["netmask"] = str(ipv4.netmask)
    if server["dns"]:
        try:
            ipaddress.ip_address(server["dns"])
        except ValueError as exc:
            raise ValueError("IPv4 DNS 地址无效") from exc

    networking = value["networking"]
    networking["outboundInterface"] = str(networking["outboundInterface"]).strip()
    if not SAFE_DEVICE_RE.fullmatch(networking["outboundInterface"]):
        raise ValueError("NAT 出口网卡名称无效")
    for key in ("ipv4Nat", "ipv6Enabled", "ipv6Nat"):
        networking[key] = bool(networking[key])
    if networking["ipv6Enabled"]:
        for key, label in (
            ("ipv6Network", "IPv6 地址池"),
            ("ipv6Route", "IPv6 默认路由"),
        ):
            try:
                ipaddress.IPv6Network(str(networking[key]), strict=False)
            except ValueError as exc:
                raise ValueError(f"{label}无效") from exc
        if networking["ipv6Dns"]:
            try:
                ipaddress.IPv6Address(str(networking["ipv6Dns"]))
            except ValueError as exc:
                raise ValueError("IPv6 DNS 地址无效") from exc
        routes = networking.get("ipv6InternalRoutes") or []
        networking["ipv6InternalRoutes"] = [str(item).strip() for item in routes[:3]]
        networking["ipv6InternalRoutes"] += [""] * (3 - len(networking["ipv6InternalRoutes"]))
        for route in networking["ipv6InternalRoutes"]:
            if route:
                try:
                    ipaddress.IPv6Network(route, strict=False)
                except ValueError as exc:
                    raise ValueError("IPv6 内部路由无效") from exc

    certificates = value["certificates"]
    for key in ("generate", "forceRegenerate", "generateDefaultProfile"):
        certificates[key] = bool(certificates[key])

    oauth2 = value["oauth2"]
    oauth2["issuer"] = _validate_url(oauth2["issuer"], "OAuth2 Issuer")
    oauth2["baseUrl"] = _validate_url(oauth2["baseUrl"], "OAuth2 回调地址")
    oauth2["clientId"] = str(oauth2["clientId"]).strip()[:256]
    oauth2["httpListen"] = str(oauth2["httpListen"]).strip()
    oauth2["openvpnAddress"] = str(oauth2["openvpnAddress"]).strip()
    if not oauth2["httpListen"] or not oauth2["openvpnAddress"]:
        raise ValueError("OAuth2 监听地址和 OpenVPN 管理地址不能为空")
    return value


def save(payload: dict) -> dict:
    settings = validate(payload)
    existing = _read_document()
    secrets = dict(existing.get("secrets") or {})
    incoming = payload.get("secrets") or {}
    for key in SECRET_ENV_MAP:
        secret = str(incoming.get(key, "")).strip()
        if secret:
            if key == "httpSecret" and len(secret) not in (16, 24, 32):
                raise ValueError("HTTP 会话 Secret 必须为 16、24 或 32 个字符")
            if key == "managementPassword" and len(secret) < 8:
                raise ValueError("OpenVPN 管理接口密码至少需要 8 个字符")
            secrets[key] = _openssl(secret)
    document = {
        "version": 1,
        "updatedAt": int(time.time()),
        "settings": settings,
        "secrets": secrets,
    }
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=SETTINGS_PATH.parent,
        prefix=".runtime-settings-",
        delete=False,
    ) as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, SETTINGS_PATH)
    return public_settings()


def effective_environment() -> dict[str, str]:
    settings = load()
    result = {
        "OVPN_CA_CERT": os.getenv("OVPN_CA_CERT", "/etc/openvpn/certs/ca.crt"),
        "OVPN_SERVER_CERT": os.getenv("OVPN_SERVER_CERT", "/etc/openvpn/certs/server.crt"),
        "OVPN_SERVER_KEY": os.getenv("OVPN_SERVER_KEY", "/etc/openvpn/certs/server.key"),
        "OVPN_DH_PEM": os.getenv("OVPN_DH_PEM", "/etc/openvpn/certs/dh.pem"),
    }
    for (section, key), env_name in ENV_MAP.items():
        value = settings[section][key]
        result[env_name] = str(value).lower() if isinstance(value, bool) else str(value)
    for index, value in enumerate(settings["networking"]["ipv6InternalRoutes"]):
        result[f"OVPN_IPV6_INT_NETWORK{index}"] = value
    document = _read_document()
    encrypted = document.get("secrets") or {}
    for key, env_name in SECRET_ENV_MAP.items():
        if encrypted.get(key):
            result[env_name] = _openssl(encrypted[key], decrypt=True)
        else:
            result[env_name] = os.getenv(env_name, SECRET_DEFAULTS[key])
    return result


def write_shell_exports() -> None:
    for key, value in effective_environment().items():
        print(f"export {key}={shlex.quote(value)}")


if __name__ == "__main__":
    if sys.argv[1:] == ["export-shell"]:
        write_shell_exports()
    else:
        raise SystemExit("usage: runtime_config.py export-shell")
