import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ADMIN_DIR = Path(__file__).parents[1] / "admin"
sys.path.insert(0, str(ADMIN_DIR))
SPEC = importlib.util.spec_from_file_location("admin_server", ADMIN_DIR / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
import geoip_service
import monitors
import runtime_config
import storage
import vpn_control
import vpn_control_client


class StatusParserTest(unittest.TestCase):
    def test_parses_status_version_three(self):
        content = """TITLE,OpenVPN 2.6
TIME,1710000000,1710000000
HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,Bytes Received,Bytes Sent,Connected Since,Connected Since (time_t),Username,Client ID,Peer ID,Data Channel Cipher
CLIENT_LIST,alice@example.com,198.51.100.2:51000,10.7.0.2,,2048,4096,2026-07-26 08:00:00,1785052800,alice@example.com,0,0,AES-256-GCM
END
"""
        parsed = server.parse_openvpn_status(content)
        self.assertEqual(len(parsed["clients"]), 1)
        self.assertEqual(parsed["clients"][0]["username"], "alice@example.com")
        self.assertEqual(parsed["clients"][0]["virtualAddress"], "10.7.0.2")
        self.assertEqual(parsed["clients"][0]["bytesReceived"], 2048)
        self.assertEqual(parsed["clients"][0]["bytesSent"], 4096)

    def test_parses_legacy_status(self):
        content = """OpenVPN CLIENT LIST
Updated,Sat Jul 26 08:00:00 2026
Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
bob,203.0.113.8:4000,12,34,Sat Jul 26 07:50:00 2026
ROUTING TABLE
END
"""
        parsed = server.parse_openvpn_status(content)
        self.assertEqual(parsed["clients"][0]["username"], "bob")
        self.assertEqual(parsed["clients"][0]["bytesSent"], 34)


class ProfileValidationTest(unittest.TestCase):
    def test_profile_name_allowlist(self):
        self.assertIsNotNone(server.CLIENT_NAME_RE.fullmatch("alice-macbook_01"))
        self.assertIsNone(server.CLIENT_NAME_RE.fullmatch("../server"))
        self.assertIsNone(server.CLIENT_NAME_RE.fullmatch("name with spaces"))

    def test_profile_listing_only_includes_ovpn(self):
        with tempfile.TemporaryDirectory() as directory:
            original = server.CLIENT_DIR
            try:
                server.CLIENT_DIR = Path(directory)
                (server.CLIENT_DIR / "alice.ovpn").write_text("client", encoding="utf-8")
                (server.CLIENT_DIR / "secret.key").write_text("secret", encoding="utf-8")
                self.assertEqual([item["filename"] for item in server.list_profiles()], ["alice.ovpn"])
            finally:
                server.CLIENT_DIR = original

    def test_rejects_invalid_certificate_upload(self):
        with self.assertRaises(ValueError):
            server.update_certificate_bundle({"files": {"privateKey": "not-base64"}})


class AuthenticationTest(unittest.TestCase):
    def setUp(self):
        server.invalidate_sessions()
        server._LOGIN_ATTEMPTS.clear()

    def test_web_session_expires(self):
        token = server.create_session("admin", now=100)
        self.assertEqual(server.session_value(token, now=101)["username"], "admin")
        self.assertIsNone(
            server.session_value(token, now=100 + server.SESSION_TTL_SECONDS + 1)
        )

    def test_bootstrap_credentials_are_supported(self):
        original_password = os.environ.get("WEB_UI_PASSWORD")
        original_username = os.environ.get("WEB_UI_USERNAME")
        original_db = storage.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as directory:
                storage.DB_PATH = Path(directory) / "admin.db"
                storage.initialize()
                os.environ["WEB_UI_USERNAME"] = "admin"
                os.environ["WEB_UI_PASSWORD"] = "bootstrap-password"
                self.assertTrue(server.credentials_match("admin", "bootstrap-password"))
                self.assertFalse(server.credentials_match("admin", "wrong"))
        finally:
            storage.DB_PATH = original_db
            if original_password is None:
                os.environ.pop("WEB_UI_PASSWORD", None)
            else:
                os.environ["WEB_UI_PASSWORD"] = original_password
            if original_username is None:
                os.environ.pop("WEB_UI_USERNAME", None)
            else:
                os.environ["WEB_UI_USERNAME"] = original_username

    def test_login_failures_are_rate_limited(self):
        for timestamp in range(server.LOGIN_MAX_ATTEMPTS):
            server.record_login_failure("127.0.0.1", now=timestamp)
        blocked, retry = server.login_blocked(
            "127.0.0.1", now=server.LOGIN_MAX_ATTEMPTS
        )
        self.assertTrue(blocked)
        self.assertGreater(retry, 0)
        server.clear_login_failures("127.0.0.1")
        self.assertFalse(server.login_blocked("127.0.0.1", now=10)[0])


class TrafficAuditTest(unittest.TestCase):
    def test_parses_outbound_tls_sni(self):
        monitor = monitors.TrafficMonitor(lambda: {
            "clients": [{"virtualAddress": "10.7.0.2", "username": "alice@example.com"}]
        })
        values = [
            "1785060000", "10.7.0.2", "", "1.1.1.1", "", "50123", "",
            "443", "", "120", "", "", "", "example.com", "",
        ]
        record = monitor.parse_line("\t".join(values))
        self.assertEqual(record["username"], "alice@example.com")
        self.assertEqual(record["targetIp"], "1.1.1.1")
        self.assertEqual(record["domain"], "example.com")
        self.assertEqual(record["uploadBytes"], 120)
        self.assertEqual(record["downloadBytes"], 0)

    def test_traffic_storage_aggregates_records(self):
        with tempfile.TemporaryDirectory() as directory:
            original = storage.DB_PATH
            try:
                storage.DB_PATH = Path(directory) / "audit.db"
                storage.initialize()
                base = {
                    "minute": 1785060000,
                    "username": "alice",
                    "vpnIp": "10.7.0.2",
                    "targetIp": "1.1.1.1",
                    "targetPort": 443,
                    "protocol": "TCP",
                    "domain": "example.com",
                    "uploadBytes": 100,
                    "downloadBytes": 200,
                    "connections": 1,
                }
                storage.upsert_access(base)
                storage.upsert_access(base)
                result = storage.traffic_dashboard(since=1785050000)
                self.assertEqual(result["summary"]["uploadBytes"], 200)
                self.assertEqual(result["summary"]["downloadBytes"], 400)
                self.assertEqual(result["summary"]["targets"], 1)
            finally:
                storage.DB_PATH = original


class GeoIPSettingsTest(unittest.TestCase):
    def test_validates_country_database_settings(self):
        value = geoip_service.validate_settings({
            "repository": "Loyalsoldier/geoip",
            "ref": "release",
            "file": "Country.mmdb",
            "updateIntervalHours": 168,
            "retentionDays": 30,
        })
        self.assertEqual(value["retentionDays"], 30)
        with self.assertRaises(ValueError):
            geoip_service.validate_settings({"repository": "../private"})


class RuntimeSettingsTest(unittest.TestCase):
    def test_validates_and_persists_web_managed_runtime_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            original = runtime_config.SETTINGS_PATH
            try:
                runtime_config.SETTINGS_PATH = Path(directory) / "runtime-settings.json"
                value = runtime_config.save({
                    "server": {
                        "remoteHost": "vpn.example.com",
                        "port": 443,
                        "protocol": "tcp-server",
                        "network": "10.20.0.0",
                        "netmask": "255.255.0.0",
                    },
                    "oauth2": {
                        "issuer": "https://id.example.com/realms/vpn",
                        "baseUrl": "https://vpn.example.com/oauth2/callback",
                    },
                })
                self.assertTrue(value["persisted"])
                self.assertEqual(value["server"]["port"], 443)
                self.assertEqual(runtime_config.load()["server"]["remoteHost"], "vpn.example.com")
                self.assertEqual(
                    runtime_config.SETTINGS_PATH.stat().st_size > 0, True
                )
            finally:
                runtime_config.SETTINGS_PATH = original

    def test_rejects_invalid_runtime_network(self):
        with self.assertRaises(ValueError):
            runtime_config.validate({
                "server": {"network": "not-a-network", "netmask": "255.255.255.0"}
            })


class ConsoleSecurityTest(unittest.TestCase):
    def test_passwords_are_salted_and_verified(self):
        encoded = server._password_hash("a-strong-console-password")
        self.assertNotIn("a-strong-console-password", encoded)
        self.assertTrue(server._password_matches("a-strong-console-password", encoded))
        self.assertFalse(server._password_matches("wrong-password", encoded))


class VpnInstanceControlTest(unittest.TestCase):
    def test_desired_instance_state_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            original_path = vpn_control.STATE_PATH
            try:
                vpn_control.STATE_PATH = Path(directory) / "instance-state.json"
                manager = vpn_control.InstanceManager()
                manager.desired_running = False
                manager._save_desired_state()
                restored = vpn_control.InstanceManager()
                self.assertFalse(restored.desired_running)
                self.assertEqual(restored.status()["state"], "stopped")
            finally:
                vpn_control.STATE_PATH = original_path

    def test_control_client_uses_private_bearer_api(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"controller":"online","state":"running"}'

        original_url = vpn_control_client.CONTROL_URL
        original_token = vpn_control_client.CONTROL_TOKEN
        try:
            vpn_control_client.CONTROL_URL = "http://127.0.0.1:9090"
            vpn_control_client.CONTROL_TOKEN = "test-token"
            with mock.patch.object(
                vpn_control_client, "urlopen", return_value=Response()
            ) as open_request:
                result = vpn_control_client.request("reload")
            request_value = open_request.call_args.args[0]
            self.assertEqual(request_value.full_url, "http://127.0.0.1:9090/reload")
            self.assertEqual(request_value.method, "POST")
            self.assertEqual(
                request_value.get_header("Authorization"), "Bearer test-token"
            )
            self.assertEqual(result["state"], "running")
        finally:
            vpn_control_client.CONTROL_URL = original_url
            vpn_control_client.CONTROL_TOKEN = original_token

    def test_reload_targets_only_openvpn_process_in_instance_group(self):
        with tempfile.TemporaryDirectory() as directory:
            original_proc = vpn_control.PROC_ROOT
            try:
                vpn_control.PROC_ROOT = Path(directory)
                process_dir = vpn_control.PROC_ROOT / "123"
                process_dir.mkdir()
                (process_dir / "cmdline").write_bytes(b"/usr/sbin/openvpn\0--config\0")
                (process_dir / "stat").write_text(
                    "123 (openvpn) S 500 500 500 0 0\n", encoding="utf-8"
                )
                manager = vpn_control.InstanceManager()
                manager.process = mock.Mock(pid=500)
                manager.process.poll.return_value = None
                with mock.patch.object(vpn_control.os, "kill") as kill:
                    manager.reload()
                kill.assert_called_once_with(123, vpn_control.RELOAD_SIGNAL)
            finally:
                vpn_control.PROC_ROOT = original_proc

    def test_instance_lock_is_persisted(self):
        with mock.patch.object(storage, "set_setting") as set_setting:
            self.assertTrue(server.set_instance_locked(True))
        set_setting.assert_called_once_with("instance-lock", True)


if __name__ == "__main__":
    unittest.main()
