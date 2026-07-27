"""Keep the VPN container alive while managing the OpenVPN instance process."""

from __future__ import annotations

import hmac
import json
import os
import signal
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


LISTEN_HOST = os.getenv("OPENVPN_CONTROL_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.getenv("OPENVPN_CONTROL_LISTEN_PORT", "9090"))
CONTROL_TOKEN = os.getenv("OPENVPN_CONTROL_TOKEN", "")
STATE_PATH = Path(
    os.getenv("OPENVPN_INSTANCE_STATE_PATH", "/etc/openvpn/admin/instance-state.json")
)
INSTANCE_COMMAND = os.getenv(
    "OPENVPN_INSTANCE_COMMAND", "/usr/local/bin/entrypoint.sh"
)
AUTOSTART = os.getenv("OPENVPN_AUTOSTART", "true").lower() in ("1", "true", "yes", "on")
RESTART_DELAY_SECONDS = 3
STATUS_PATH = Path(
    os.getenv("OPENVPN_STATUS_PATH", "/run/openvpn/openvpn-status.log")
)


class InstanceManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.last_exit_code: int | None = None
        self.last_error = ""
        self.next_start_at = 0.0
        self.stopping = False
        self.shutdown_requested = False
        self.desired_running = self._load_desired_state()
        self.monitor = threading.Thread(
            target=self._monitor, name="vpn-instance-monitor", daemon=True
        )

    def _load_desired_state(self) -> bool:
        try:
            value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return value.get("desiredState") == "running"
        except (OSError, json.JSONDecodeError, AttributeError):
            return AUTOSTART

    def _save_desired_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "desiredState": "running" if self.desired_running else "stopped",
                    "updatedAt": int(time.time()),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, STATE_PATH)

    def start_monitor(self) -> None:
        self.monitor.start()

    def _spawn(self) -> None:
        try:
            STATUS_PATH.unlink(missing_ok=True)
            self.process = subprocess.Popen(
                [INSTANCE_COMMAND],
                start_new_session=True,
            )
            self.started_at = time.time()
            self.next_start_at = 0.0
            print(f"[vpn-control] instance started with pid {self.process.pid}", flush=True)
        except OSError as exc:
            self.process = None
            self.last_error = str(exc)
            print(f"[vpn-control] unable to start instance: {exc}", flush=True)

    def _terminate(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            self.process = None
            return
        self.stopping = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        finally:
            self.last_exit_code = process.returncode
            self.process = None
            self.started_at = None
            self.stopping = False
            print("[vpn-control] instance stopped", flush=True)

    def _monitor(self) -> None:
        while not self.shutdown_requested:
            with self.lock:
                process = self.process
                if process is not None and process.poll() is not None:
                    self.last_exit_code = process.returncode
                    self.process = None
                    self.started_at = None
                    if self.desired_running:
                        self.last_error = (
                            f"instance exited with code {self.last_exit_code}; retrying"
                        )
                        self.next_start_at = time.time() + RESTART_DELAY_SECONDS
                if (
                    self.desired_running
                    and self.process is None
                    and not self.stopping
                    and time.time() >= self.next_start_at
                ):
                    self._spawn()
            time.sleep(RESTART_DELAY_SECONDS)

    def start(self) -> dict:
        with self.lock:
            self.desired_running = True
            self._save_desired_state()
            if self.process is None or self.process.poll() is not None:
                self.last_error = ""
                self.next_start_at = 0.0
                self._spawn()
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            self.desired_running = False
            self._save_desired_state()
            self._terminate()
            return self.status()

    def restart(self) -> dict:
        with self.lock:
            self.desired_running = True
            self._save_desired_state()
            self._terminate()
            self.last_error = ""
            self.next_start_at = 0.0
            self._spawn()
            return self.status()

    def shutdown(self) -> None:
        with self.lock:
            self.shutdown_requested = True
            self._terminate()

    def status(self) -> dict:
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            try:
                ready = (
                    running
                    and self.started_at is not None
                    and STATUS_PATH.stat().st_mtime >= self.started_at
                )
            except OSError:
                ready = False
            if self.stopping:
                state = "stopping"
            elif ready:
                state = "running"
            elif running:
                state = "starting"
            elif self.desired_running:
                state = "failed" if self.last_error else "starting"
            else:
                state = "stopped"
            return {
                "controller": "online",
                "state": state,
                "desiredState": "running" if self.desired_running else "stopped",
                "pid": self.process.pid if running else None,
                "startedAt": self.started_at,
                "uptimeSeconds": int(time.time() - self.started_at)
                if running and self.started_at
                else 0,
                "lastExitCode": self.last_exit_code,
                "message": self.last_error,
            }


MANAGER = InstanceManager()


class ControlHandler(BaseHTTPRequestHandler):
    server_version = "OpenVPNInstanceControl/1.0"

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        value = self.headers.get("Authorization", "")
        expected = f"Bearer {CONTROL_TOKEN}"
        return bool(CONTROL_TOKEN) and hmac.compare_digest(value, expected)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/health":
            self._json({"ok": True, **MANAGER.status()})
        elif route == "/status":
            if not self._authorized():
                self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            self._json(MANAGER.status())
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if not self._authorized():
            self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        action = route.removeprefix("/")
        if action not in ("start", "stop", "restart"):
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self._json(getattr(MANAGER, action)())

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[vpn-control] {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    if not CONTROL_TOKEN:
        raise SystemExit("OPENVPN_CONTROL_TOKEN is required")
    MANAGER.start_monitor()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ControlHandler)

    def stop_server(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    print(
        f"[vpn-control] listening on http://{LISTEN_HOST}:{LISTEN_PORT}; "
        f"desired state is {'running' if MANAGER.desired_running else 'stopped'}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        MANAGER.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
