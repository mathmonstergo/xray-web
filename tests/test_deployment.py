from tests import support

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from scripts.prepare_local import prepare
from scripts.export_source import export_source
from scripts import service_control
from core.runtime import XrayRuntime
import config


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_generated_units_are_portable_and_use_private_config(self):
        project = self.root / "project with spaces"
        files = prepare(self.root / "deploy", project=project, python="/usr/bin/python3")
        configuration = json.loads(files[0].read_text())
        self.assertEqual({ob["tag"] for ob in configuration["outbounds"]}, {"proxy", "direct", "block"})
        self.assertTrue(all(ib["listen"] == "127.0.0.1" for ib in configuration["inbounds"]))
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(files[1].stat().st_mode & 0o777, 0o600)
        self.assertIn("XRAY_SYSTEMD_USER=1", files[1].read_text())
        for unit in files[2:]:
            text = unit.read_text()
            self.assertNotIn("@PROJECT@", text)
            self.assertNotIn("User=adam", text)
            self.assertIn('WorkingDirectory="' + str(project) + '"', text)
            self.assertIn("EnvironmentFile=", text)

    def test_generator_refuses_to_overwrite_existing_configuration(self):
        files = prepare(self.root / "deploy")
        files[0].write_text("private existing config")
        with self.assertRaises(ValueError): prepare(self.root / "deploy")
        self.assertEqual(files[0].read_text(), "private existing config")

    @unittest.skipUnless(Path(config.XRAY_BIN).is_file(), "Xray binary is not installed")
    def test_generated_initial_config_passes_native_validation(self):
        files = prepare(self.root / "deploy")
        XrayRuntime().validate(json.loads(files[0].read_text()))

    @unittest.skipUnless(Path(config.XRAY_BIN).is_file(), "Xray binary is not installed")
    def test_validation_ignores_restricted_log_paths(self):
        cfg = {
            "log": {
                "loglevel": "warning",
                "access": "/root/cannot_write_access.log",
                "error": "/root/cannot_write_error.log",
            },
            "outbounds": [{"protocol": "freedom"}],
        }
        XrayRuntime().validate(cfg)

    def test_export_excludes_history_runtime_secrets_and_symlinks(self):
        for name, content in {
            "README.md": "public", "main.py": "public", ".env.example": "WEB_PASSWORD=",
            "data/store.json": "private", "data/custom_rules.json": "private", ".env": "private",
            ".git/config": "private", ".venv/secrets.py": "private", "core/module.py": "public",
            "core/__pycache__/secret.py": "private", "REVIEW_2026-09-15.md": "private",
        }.items():
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        (self.root / "core/link.py").symlink_to(self.root / ".env")
        count, digest = export_source(self.root / "dist/source.zip", self.root)
        with zipfile.ZipFile(self.root / "dist/source.zip") as archive:
            self.assertEqual(set(archive.namelist()), {"xray-web/README.md", "xray-web/main.py", "xray-web/.env.example", "xray-web/core/module.py"})
            self.assertTrue(all(b"private" not in archive.read(name) for name in archive.namelist()))
        self.assertEqual(count, 4)
        self.assertEqual(len(digest), 64)
        _, second = export_source(self.root / "dist/second.zip", self.root)
        self.assertEqual(digest, second)

    def test_export_refuses_to_overwrite(self):
        output = self.root / "source.zip"
        output.write_bytes(b"existing")
        with self.assertRaises(ValueError): export_source(output, self.root)
        self.assertEqual(output.read_bytes(), b"existing")

    def test_unowned_pid_never_receives_a_signal(self):
        marker = self.root / "web.pid"
        marker.write_text("99999")
        with patch.object(service_control.os, "kill") as kill, patch.object(service_control.os, "killpg") as killpg:
            service_control.stop(marker)
        kill.assert_not_called()
        killpg.assert_not_called()

    def test_pid_reuse_is_detected(self):
        marker = self.root / "web.pid"
        marker.write_text(json.dumps({"pid": 1234, "start_ticks": "old", "main": str(service_control.MAIN)}))
        with patch.object(service_control, "process_record", return_value={"pid": 1234, "start_ticks": "new", "main": str(service_control.MAIN)}):
            self.assertIsNone(service_control.owned_record(marker))

    def test_process_identity_checks_command_and_start_time(self):
        process = self.root / "1234"
        process.mkdir()
        (process / "cwd").symlink_to(service_control.PROJECT, target_is_directory=True)
        (process / "cmdline").write_bytes(b"python3\0" + str(service_control.MAIN).encode() + b"\0")
        fields = ["S"] + ["0"] * 18 + ["56789"] + ["0"] * 5
        (process / "stat").write_text("1234 (python with spaces) " + " ".join(fields))
        self.assertEqual(service_control.process_record(1234, proc_root=self.root)["start_ticks"], "56789")
        (process / "cmdline").write_bytes(b"unrelated-app\0")
        self.assertIsNone(service_control.process_record(1234, proc_root=self.root))

    def test_port_conflict_does_not_trigger_process_cleanup(self):
        probe = MagicMock()
        probe.__enter__.return_value.bind.side_effect = OSError("busy")
        with patch.object(service_control.socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 2017))]), patch.object(service_control.socket, "socket", return_value=probe), patch.object(service_control.os, "kill") as kill:
            with self.assertRaisesRegex(RuntimeError, "未终止任何进程"):
                service_control.ensure_port_available()
        kill.assert_not_called()

    def test_health_response_must_belong_to_child_pid(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"pid": 1234}'
        with patch.object(service_control.http.client, "HTTPConnection", return_value=connection):
            self.assertFalse(service_control.process_is_ready("127.0.0.1", 9999))
            self.assertTrue(service_control.process_is_ready("127.0.0.1", 1234))

    def test_download_failure_never_runs_installer(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        curl = binaries / "curl"
        curl.write_text("#!/bin/sh\nexit 22\n")
        curl.chmod(0o755)
        sudo = binaries / "sudo"
        marker = self.root / "installer-ran"
        sudo.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        sudo.chmod(0o755)
        result = subprocess.run(["bash", str(service_control.PROJECT / "scripts/update_xray.sh"), "v26.7.28"], env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 22)
        self.assertFalse(marker.exists())
