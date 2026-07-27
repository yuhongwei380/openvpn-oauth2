import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


ADMIN_DIR = Path(__file__).parents[1] / "admin"
sys.path.insert(0, str(ADMIN_DIR))
SPEC = importlib.util.spec_from_file_location("admin_server", ADMIN_DIR / "server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
import geoip_service
import monitors
import runtime_config
import storage


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
    def test_auth_can_be_disabled_for_authenticated_reverse_proxy(self):
        handler = object.__new__(server.AdminHandler)
        handler.path = "/api/status"
        original = os.environ.get("WEB_UI_AUTH_ENABLED")
        try:
            os.environ["WEB_UI_AUTH_ENABLED"] = "false"
            self.assertTrue(handler._require_auth())
        finally:
            if original is None:
                os.environ.pop("WEB_UI_AUTH_ENABLED", None)
            else:
                os.environ["WEB_UI_AUTH_ENABLED"] = original


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


if __name__ == "__main__":
    unittest.main()
