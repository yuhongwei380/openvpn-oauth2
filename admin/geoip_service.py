"""Configurable Country.mmdb updater and hot-reloading country lookup."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import storage

try:
    import maxminddb
except ImportError:  # pragma: no cover - optional outside the image
    maxminddb = None


DEFAULTS = {
    "repository": "Loyalsoldier/geoip",
    "ref": "release",
    "file": "Country.mmdb",
    "updateIntervalHours": 168,
    "retentionDays": 30,
}
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_settings(payload: dict) -> dict:
    settings = {**DEFAULTS, **payload}
    if not REPOSITORY_RE.fullmatch(str(settings["repository"])):
        raise ValueError("GitHub 仓库必须使用 owner/repository 格式")
    if any(part in (".", "..") for part in str(settings["repository"]).split("/")):
        raise ValueError("GitHub 仓库路径无效")
    if not SAFE_PATH_RE.fullmatch(str(settings["ref"])) or not SAFE_PATH_RE.fullmatch(str(settings["file"])):
        raise ValueError("分支和数据库文件名不能包含路径")
    interval = int(settings["updateIntervalHours"])
    retention = int(settings["retentionDays"])
    if not 0 <= interval <= 8760:
        raise ValueError("更新频率必须在 0–8760 小时之间")
    if not 1 <= retention <= 3650:
        raise ValueError("保留天数必须在 1–3650 天之间")
    settings["updateIntervalHours"] = interval
    settings["retentionDays"] = retention
    return settings


class GeoIPService(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__(name="geoip-updater")
        self.database_path = Path(os.getenv("GEOIP_DATABASE_PATH", "/geoip/Country.mmdb"))
        self.reader = None
        self.loaded_mtime = 0.0
        self.state = "unavailable"
        self.message = "GeoIP 数据库尚未下载"
        self.last_checked = 0
        self.reload()

    def settings(self) -> dict:
        return validate_settings(storage.get_setting("geoip", DEFAULTS))

    def save(self, payload: dict) -> dict:
        settings = validate_settings(payload)
        storage.set_setting("geoip", settings)
        removed = storage.cleanup_access_records(settings["retentionDays"])
        self.last_checked = 0
        return {**settings, "removedRecords": removed}

    def reload(self) -> None:
        if not self.database_path.is_file() or maxminddb is None:
            self.state = "unavailable"
            self.message = "国家数据库未就绪" if maxminddb else "缺少 maxminddb 读取组件"
            return
        mtime = self.database_path.stat().st_mtime
        if self.reader is not None and mtime == self.loaded_mtime:
            return
        if self.reader is not None:
            self.reader.close()
        self.reader = maxminddb.open_database(str(self.database_path))
        self.loaded_mtime = mtime
        self.state = "ready"
        self.message = "国家级归属数据库已加载"

    def lookup(self, address: str) -> dict | None:
        self.reload()
        if self.reader is None:
            return None
        try:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_reserved:
                return None
            result = self.reader.get(address) or {}
            country = result.get("country") or result.get("registered_country") or {}
            iso = country.get("iso_code")
            if not iso:
                return None
            names = country.get("names", {})
            return {"code": iso, "name": names.get("zh-CN") or names.get("en") or iso}
        except (ValueError, OSError):
            return None

    def aggregate(self, records: list[dict]) -> list[dict]:
        countries: dict[str, dict] = {}
        for record in records:
            country = self.lookup(record.get("targetIp", ""))
            if not country:
                continue
            item = countries.setdefault(country["code"], {**country, "bytes": 0, "connections": 0})
            item["bytes"] += record.get("uploadBytes", 0) + record.get("downloadBytes", 0)
            item["connections"] += record.get("connections", 0)
        return sorted(countries.values(), key=lambda item: item["bytes"], reverse=True)

    def download(self) -> None:
        settings = self.settings()
        repository, ref, filename = settings["repository"], settings["ref"], settings["file"]
        base = f"https://cdn.jsdelivr.net/gh/{repository}@{ref}/{filename}"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.database_path.parent) as directory:
            target = Path(directory) / filename
            checksum = Path(directory) / f"{filename}.sha256sum"
            urllib.request.urlretrieve(base, target)
            urllib.request.urlretrieve(f"{base}.sha256sum", checksum)
            expected = checksum.read_text(encoding="utf-8").split()[0].lower()
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if not expected or not hmac_compare(expected, actual):
                raise ValueError("GeoIP SHA-256 校验失败")
            os.replace(target, self.database_path)
        self.reload()

    def run(self) -> None:
        while True:
            try:
                settings = self.settings()
                interval = settings["updateIntervalHours"]
                due = not self.database_path.exists()
                if interval and self.database_path.exists():
                    due = time.time() - self.database_path.stat().st_mtime >= interval * 3600
                if due and time.time() - self.last_checked >= 300:
                    self.last_checked = time.time()
                    self.state, self.message = "updating", "正在更新国家数据库"
                    self.download()
                else:
                    self.reload()
            except Exception as exc:
                self.state, self.message = "failed", f"GeoIP 更新失败：{exc}"
            time.sleep(60)


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
