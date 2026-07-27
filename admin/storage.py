"""SQLite persistence for connection and destination audit data."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(os.getenv("WEB_UI_DATABASE_PATH", "/etc/openvpn/admin/admin.db"))
_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with _LOCK, _database() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS connection_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp INTEGER NOT NULL,
              event TEXT NOT NULL,
              username TEXT NOT NULL,
              real_address TEXT NOT NULL,
              virtual_address TEXT NOT NULL,
              bytes_received INTEGER NOT NULL DEFAULT 0,
              bytes_sent INTEGER NOT NULL DEFAULT 0,
              duration_seconds INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_connection_events_time
              ON connection_events(timestamp DESC);
            CREATE TABLE IF NOT EXISTS access_records (
              minute INTEGER NOT NULL,
              username TEXT NOT NULL,
              vpn_ip TEXT NOT NULL,
              target_ip TEXT NOT NULL,
              target_port INTEGER NOT NULL,
              protocol TEXT NOT NULL,
              domain TEXT NOT NULL DEFAULT '',
              upload_bytes INTEGER NOT NULL DEFAULT 0,
              download_bytes INTEGER NOT NULL DEFAULT 0,
              connections INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(minute, username, vpn_ip, target_ip, target_port, protocol, domain)
            );
            CREATE INDEX IF NOT EXISTS idx_access_records_time ON access_records(minute DESC);
            CREATE INDEX IF NOT EXISTS idx_access_records_target ON access_records(target_ip, domain);
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            );
            """
        )


def get_setting(key: str, default=None):
    try:
        with _LOCK, _database() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return default


def set_setting(key: str, value) -> None:
    with _LOCK, _database() as db:
        db.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), int(time.time())),
        )


def add_connection_event(event: str, client: dict, duration_seconds: int = 0) -> None:
    connected_at = client.get("connectedAt", "")
    try:
        timestamp = int(datetime.fromisoformat(connected_at).timestamp())
    except (ValueError, TypeError):
        timestamp = int(time.time())
    if event == "disconnect":
        timestamp = int(time.time())
    with _LOCK, _database() as db:
        db.execute(
            """
            INSERT INTO connection_events(
              timestamp,event,username,real_address,virtual_address,
              bytes_received,bytes_sent,duration_seconds
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                timestamp,
                event,
                client.get("username", ""),
                client.get("realAddress", ""),
                client.get("virtualAddress") or client.get("virtualIpv6Address", ""),
                int(client.get("bytesReceived", 0)),
                int(client.get("bytesSent", 0)),
                max(0, int(duration_seconds)),
            ),
        )


def query_connection_events(keyword="", event="", since=0, limit=250) -> list[dict]:
    where = ["timestamp >= ?"]
    params: list = [int(since)]
    if keyword:
        where.append("(username LIKE ? OR real_address LIKE ? OR virtual_address LIKE ?)")
        term = f"%{keyword}%"
        params.extend([term, term, term])
    if event in ("connect", "disconnect"):
        where.append("event = ?")
        params.append(event)
    params.append(min(max(int(limit), 1), 1000))
    with _LOCK, _database() as db:
        rows = db.execute(
            f"SELECT * FROM connection_events WHERE {' AND '.join(where)} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "timestamp": datetime.fromtimestamp(row["timestamp"], timezone.utc).isoformat(),
            "event": row["event"],
            "username": row["username"],
            "realAddress": row["real_address"],
            "virtualAddress": row["virtual_address"],
            "bytesReceived": row["bytes_received"],
            "bytesSent": row["bytes_sent"],
            "durationSeconds": row["duration_seconds"],
        }
        for row in rows
    ]


def upsert_access(record: dict) -> None:
    with _LOCK, _database() as db:
        db.execute(
            """
            INSERT INTO access_records(
              minute,username,vpn_ip,target_ip,target_port,protocol,domain,
              upload_bytes,download_bytes,connections
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(minute,username,vpn_ip,target_ip,target_port,protocol,domain)
            DO UPDATE SET
              upload_bytes=upload_bytes+excluded.upload_bytes,
              download_bytes=download_bytes+excluded.download_bytes,
              connections=connections+excluded.connections
            """,
            (
                record["minute"],
                record.get("username", ""),
                record["vpnIp"],
                record["targetIp"],
                int(record.get("targetPort", 0)),
                record.get("protocol", "").upper(),
                record.get("domain", ""),
                int(record.get("uploadBytes", 0)),
                int(record.get("downloadBytes", 0)),
                int(record.get("connections", 0)),
            ),
        )


def cleanup_access_records(retention_days: int) -> int:
    cutoff = int(time.time()) - int(retention_days) * 86400
    with _LOCK, _database() as db:
        cursor = db.execute("DELETE FROM access_records WHERE minute < ?", (cutoff,))
        return cursor.rowcount


def _traffic_where(keyword: str, since: int) -> tuple[str, list]:
    where = ["minute >= ?"]
    params: list = [int(since)]
    if keyword:
        where.append("(username LIKE ? OR domain LIKE ? OR target_ip LIKE ?)")
        term = f"%{keyword}%"
        params.extend([term, term, term])
    return " AND ".join(where), params


def traffic_dashboard(keyword="", since=0, limit=200) -> dict:
    where, params = _traffic_where(keyword, since)
    with _LOCK, _database() as db:
        summary = db.execute(
            f"""
            SELECT COALESCE(SUM(upload_bytes),0) upload,
                   COALESCE(SUM(download_bytes),0) download,
                   COALESCE(SUM(connections),0) connections,
                   COUNT(DISTINCT CASE WHEN domain != '' THEN domain ELSE target_ip END) targets,
                   COUNT(DISTINCT CASE WHEN username != '' THEN username END) users
            FROM access_records WHERE {where}
            """,
            params,
        ).fetchone()
        trend = db.execute(
            f"""
            SELECT minute, SUM(upload_bytes) upload, SUM(download_bytes) download
            FROM access_records WHERE {where}
            GROUP BY minute ORDER BY minute ASC LIMIT 720
            """,
            params,
        ).fetchall()
        destinations = db.execute(
            f"""
            SELECT CASE WHEN domain != '' THEN domain ELSE target_ip END target,
                   SUM(upload_bytes) upload, SUM(download_bytes) download,
                   SUM(connections) connections
            FROM access_records WHERE {where}
            GROUP BY target ORDER BY upload + download DESC LIMIT 8
            """,
            params,
        ).fetchall()
        recent_params = list(params) + [min(max(int(limit), 1), 1000)]
        recent = db.execute(
            f"""SELECT * FROM access_records WHERE {where}
                ORDER BY minute DESC, upload_bytes + download_bytes DESC LIMIT ?""",
            recent_params,
        ).fetchall()
    return {
        "summary": {
            "uploadBytes": summary["upload"],
            "downloadBytes": summary["download"],
            "connections": summary["connections"],
            "targets": summary["targets"],
            "users": summary["users"],
        },
        "trend": [
            {
                "timestamp": datetime.fromtimestamp(row["minute"], timezone.utc).isoformat(),
                "uploadBytes": row["upload"],
                "downloadBytes": row["download"],
            }
            for row in trend
        ],
        "destinations": [dict(row) for row in destinations],
        "recent": [
            {
                "timestamp": datetime.fromtimestamp(row["minute"], timezone.utc).isoformat(),
                "username": row["username"],
                "vpnIp": row["vpn_ip"],
                "targetIp": row["target_ip"],
                "targetPort": row["target_port"],
                "protocol": row["protocol"],
                "domain": row["domain"],
                "uploadBytes": row["upload_bytes"],
                "downloadBytes": row["download_bytes"],
                "connections": row["connections"],
            }
            for row in recent
        ],
    }


def traffic_targets(keyword="", since=0, limit=500) -> list[dict]:
    where, params = _traffic_where(keyword, since)
    params.append(min(max(int(limit), 1), 2000))
    with _LOCK, _database() as db:
        rows = db.execute(
            f"""
            SELECT CASE WHEN domain != '' THEN domain ELSE target_ip END target,
                   domain, GROUP_CONCAT(DISTINCT target_ip) ips,
                   COUNT(DISTINCT CASE WHEN username != '' THEN username END) users,
                   SUM(upload_bytes) upload, SUM(download_bytes) download,
                   SUM(connections) connections, MAX(minute) last_seen
            FROM access_records WHERE {where}
            GROUP BY target, domain
            ORDER BY upload + download DESC LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "target": row["target"],
            "type": "domain" if row["domain"] else "ip",
            "ips": row["ips"].split(",") if row["ips"] else [],
            "users": row["users"],
            "uploadBytes": row["upload"],
            "downloadBytes": row["download"],
            "connections": row["connections"],
            "lastSeen": datetime.fromtimestamp(row["last_seen"], timezone.utc).isoformat(),
        }
        for row in rows
    ]
