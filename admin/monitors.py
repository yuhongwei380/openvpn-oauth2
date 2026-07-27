"""Background observers for OpenVPN sessions and VPN-side TCP/UDP metadata."""

from __future__ import annotations

import ipaddress
import os
import subprocess
import threading
import time
from collections import defaultdict

import storage


class ConnectionMonitor(threading.Thread):
    daemon = True

    def __init__(self, read_status):
        super().__init__(name="connection-monitor")
        self.read_status = read_status
        self.active: dict[str, dict] = {}

    @staticmethod
    def identity(client: dict) -> str:
        return "|".join(
            (
                client.get("username", ""),
                client.get("realAddress", ""),
                client.get("virtualAddress", ""),
                client.get("connectedAt", ""),
            )
        )

    def run(self) -> None:
        while True:
            try:
                clients = self.read_status().get("clients", [])
                current = {self.identity(client): client for client in clients}
                for key, client in current.items():
                    if key not in self.active:
                        storage.add_connection_event("connect", client)
                for key, client in self.active.items():
                    if key not in current:
                        duration = 0
                        try:
                            duration = int(time.time() - time.mktime(time.strptime(
                                client.get("connectedAt", "")[:19], "%Y-%m-%dT%H:%M:%S"
                            )))
                        except (ValueError, OverflowError):
                            pass
                        storage.add_connection_event("disconnect", client, duration)
                self.active = current
            except Exception as exc:
                print(f"[audit] connection monitor error: {exc}", flush=True)
            time.sleep(5)


class TrafficMonitor(threading.Thread):
    daemon = True
    FIELDS = (
        "frame.time_epoch",
        "ip.src",
        "ipv6.src",
        "ip.dst",
        "ipv6.dst",
        "tcp.srcport",
        "udp.srcport",
        "tcp.dstport",
        "udp.dstport",
        "frame.len",
        "dns.qry.name",
        "dns.a",
        "dns.aaaa",
        "tls.handshake.extensions_server_name",
        "http.host",
    )

    def __init__(self, read_status):
        super().__init__(name="traffic-monitor")
        self.read_status = read_status
        default_enabled = os.getenv("ENABLE_TRAFFIC_AUDIT", "true").lower() == "true"
        try:
            self.enabled = bool(
                (storage.get_setting("audit", {}) or {}).get("trafficEnabled", default_enabled)
            )
        except OSError:
            self.enabled = default_enabled
        self.state = "waiting" if self.enabled else "disabled"
        self.message = "等待抓包进程启动" if self.enabled else "流量审计已禁用"
        self._process = None
        self.networks = []
        self.dns_cache: dict[tuple[str, str], tuple[str, float]] = {}
        self.seen_connections: set[tuple] = set()
        self.last_cleanup = 0.0
        ipv4 = os.getenv("OVPN_NETWORK", "10.7.0.0")
        netmask = os.getenv("OVPN_NETMASK", "255.255.0.0")
        for value in (f"{ipv4}/{netmask}", os.getenv("OVPN_IPV6_NETWORK", "")):
            if not value:
                continue
            try:
                self.networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError:
                pass

    def status(self) -> dict:
        return {"state": self.state, "message": self.message, "enabled": self.enabled}

    def configure(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.state = "waiting" if self.enabled else "disabled"
        self.message = "等待抓包进程启动" if self.enabled else "流量审计已禁用"
        if not self.enabled and self._process and self._process.poll() is None:
            self._process.terminate()

    def _is_vpn(self, address: str) -> bool:
        try:
            ip = ipaddress.ip_address(address)
            return any(ip in network for network in self.networks)
        except ValueError:
            return False

    def parse_line(self, line: str) -> dict | None:
        values = line.rstrip("\n").split("\t")
        values += [""] * (len(self.FIELDS) - len(values))
        data = dict(zip(self.FIELDS, values))
        source = data["ip.src"] or data["ipv6.src"]
        target = data["ip.dst"] or data["ipv6.dst"]
        outbound = self._is_vpn(source) and not self._is_vpn(target)
        inbound = self._is_vpn(target) and not self._is_vpn(source)
        if not outbound and not inbound:
            return None
        vpn_ip, destination = (source, target) if outbound else (target, source)
        source_port = data["tcp.srcport"] or data["udp.srcport"]
        destination_port = data["tcp.dstport"] or data["udp.dstport"]
        protocol = "TCP" if data["tcp.srcport"] or data["tcp.dstport"] else "UDP"
        domain = data["tls.handshake.extensions_server_name"] or data["http.host"]
        dns_name = data["dns.qry.name"].rstrip(".")
        answers = [item for item in (data["dns.a"] + "," + data["dns.aaaa"]).split(",") if item]
        if dns_name and answers:
            for answer in answers:
                self.dns_cache[(vpn_ip, answer)] = (dns_name, time.time() + 3600)
        if not domain:
            cached = self.dns_cache.get((vpn_ip, destination))
            if cached and cached[1] > time.time():
                domain = cached[0]
        minute = int(float(data["frame.time_epoch"] or time.time()) // 60 * 60)
        port = int(destination_port if outbound else source_port or 0)
        users = {
            item.get("virtualAddress") or item.get("virtualIpv6Address"): item.get("username", "")
            for item in self.read_status().get("clients", [])
        }
        connection_key = (minute, vpn_ip, destination, port, protocol, domain)
        is_new = connection_key not in self.seen_connections
        self.seen_connections.add(connection_key)
        if len(self.seen_connections) > 20000:
            self.seen_connections = {key for key in self.seen_connections if key[0] >= minute - 120}
        size = int(data["frame.len"] or 0)
        return {
            "minute": minute,
            "username": users.get(vpn_ip, ""),
            "vpnIp": vpn_ip,
            "targetIp": destination,
            "targetPort": port,
            "protocol": protocol,
            "domain": domain,
            "uploadBytes": size if outbound else 0,
            "downloadBytes": size if inbound else 0,
            "connections": 1 if is_new else 0,
        }

    def run(self) -> None:
        network_filter = " or ".join(f"net {network.with_prefixlen}" for network in self.networks)
        capture_filter = f"({network_filter}) and (tcp or udp)" if network_filter else "tcp or udp"
        command = [
            "tshark", "-l", "-n", "-i", "any", "-f", capture_filter,
            "-T", "fields", "-E", "separator=/t", "-E", "occurrence=a", "-E", "aggregator=,"
        ]
        for field in self.FIELDS:
            command.extend(["-e", field])
        while True:
            if not self.enabled:
                self.state, self.message = "disabled", "流量审计已禁用"
                time.sleep(1)
                continue
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                self._process = process
                self.state, self.message = "running", "正在采集 VPN 侧 TCP/UDP 元数据"
                for line in process.stdout or []:
                    if not self.enabled:
                        process.terminate()
                        break
                    record = self.parse_line(line)
                    if record:
                        storage.upsert_access(record)
                    if time.time() - self.last_cleanup >= 3600:
                        settings = storage.get_setting("geoip", {}) or {}
                        storage.cleanup_access_records(int(settings.get("retentionDays", 30)))
                        self.last_cleanup = time.time()
                if self.enabled:
                    self.state, self.message = "failed", "抓包进程已退出，正在重试"
            except FileNotFoundError:
                self.state, self.message = "failed", "镜像中缺少 tshark"
                return
            except Exception as exc:
                self.state, self.message = "failed", f"采集失败：{exc}"
            time.sleep(5)
