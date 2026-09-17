import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import config
from core.runtime import ProcessRuntime, SystemdRuntime, create_runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config_path.write_text('{"log":{"loglevel":"warning"}}')

    def test_create_runtime_respects_env(self):
        with patch.dict(os.environ, {"XRAY_RUNTIME_MODE": "process"}):
            rt = create_runtime()
            self.assertIsInstance(rt, ProcessRuntime)

        with patch.dict(os.environ, {"XRAY_RUNTIME_MODE": "systemd"}):
            rt = create_runtime()
            self.assertIsInstance(rt, SystemdRuntime)

    def test_process_runtime_lifecycle(self):
        rt = ProcessRuntime()
        self.assertFalse(rt.is_active())

        # 模拟一个长期存活的子进程（例如 sleep 10）
        mock_proc = subprocess.Popen(["sleep", "10"])
        try:
            rt._proc = mock_proc
            self.assertTrue(rt.is_active())
            rt.stop()
            self.assertFalse(rt.is_active())
            self.assertIsNone(rt._proc)
        finally:
            if mock_proc.poll() is None:
                mock_proc.kill()

    def test_process_runtime_restart_failure_when_missing_config(self):
        rt = ProcessRuntime()
        missing_path = Path(self.temp_dir.name) / "not_found.json"
        with patch.object(config, "XRAY_CONFIG_PATH", missing_path):
            with self.assertRaises(RuntimeError) as ctx:
                rt.restart()
            self.assertIn("配置文件不存在", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
