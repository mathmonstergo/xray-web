"""Bounded systemd commands and atomic Xray configuration installation."""

import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import uuid

import config
from core.persistence import atomic_write_bytes


class XrayRuntime:
    @staticmethod
    def run(args, *, check=True):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=config.COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Xray 系统操作超时") from exc
        except OSError as exc:
            raise RuntimeError(f"无法执行系统操作：{exc}") from exc
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"命令退出码 {result.returncode}")
        return result

    def is_active(self):
        command = ["systemctl", "--user"] if config.XRAY_SYSTEMD_USER else ["systemctl"]
        return self.run([*command, "is-active", config.XRAY_SERVICE_NAME], check=False).stdout.strip() == "active"

    def service_command(self, action):
        command = ["systemctl", "--user"] if config.XRAY_SYSTEMD_USER else ["sudo", "-n", "systemctl"]
        return self.run([*command, action, config.XRAY_SERVICE_NAME])

    def restart(self):
        self.service_command("restart")
        deadline = time.monotonic() + config.CORE_START_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if self.is_active():
                return
        raise RuntimeError("Xray 重启后未进入 active 状态")

    def stop(self):
        self.service_command("stop")

    def validate(self, candidate):
        with tempfile.TemporaryDirectory(prefix="xray-web-check-") as directory:
            if isinstance(candidate, (str, bytes)):
                try:
                    test_candidate = json.loads(candidate)
                except Exception:
                    test_candidate = candidate
            else:
                test_candidate = copy.deepcopy(candidate)

            if isinstance(test_candidate, dict):
                log_cfg = test_candidate.get("log")
                if isinstance(log_cfg, dict):
                    test_candidate["log"] = {**log_cfg, "access": "none", "error": "none"}
                elif log_cfg is None:
                    test_candidate["log"] = {"access": "none", "error": "none"}

            path = Path(directory) / "config.json"
            content = (json.dumps(test_candidate) + "\n").encode() if not isinstance(test_candidate, (bytes, bytearray)) else test_candidate
            atomic_write_bytes(path, content, mode=0o600)
            self.run([config.XRAY_BIN, "run", "-test", "-config", str(path)])

    def install(self, path, content, *, private=False):
        """An unsuccessful staging write never truncates the live file."""
        path = Path(path).expanduser().resolve()
        try:
            metadata = path.stat()
        except FileNotFoundError:
            metadata = None
        mode = 0o600 if private or metadata is None else stat.S_IMODE(metadata.st_mode) & 0o777
        try:
            atomic_write_bytes(path, content, mode=mode)
            return
        except PermissionError:
            pass

        # Legacy /etc deployments can retain sudo access. New installations
        # should give the service user ownership of its configuration directory.
        stage = path.with_name(f".{path.name}.xray-web-{uuid.uuid4().hex}.tmp")
        with tempfile.TemporaryDirectory(prefix="xray-web-install-") as directory:
            source = Path(directory) / "config.json"
            atomic_write_bytes(source, content)
            args = ["sudo", "-n", "install", "-m", f"{mode:o}"]
            if metadata is not None and not private:
                args += ["-o", str(metadata.st_uid), "-g", str(metadata.st_gid)]
            args += ["--", str(source), str(stage)]
            try:
                self.run(args)
                self.run(["sudo", "-n", "mv", "-f", "--", str(stage), str(path)])
            finally:
                try:
                    if stage.exists():
                        self.run(["sudo", "-n", "rm", "-f", "--", str(stage)], check=False)
                except (OSError, RuntimeError):
                    pass

    def read(self):
        try:
            return config.XRAY_CONFIG_PATH.read_bytes()
        except FileNotFoundError:
            return None

    def backup(self, content):
        if config.XRAY_CONFIG_PATH.resolve() == config.XRAY_BACKUP_PATH.resolve():
            raise ValueError("Xray 主配置和备份路径不能相同")
        if content is not None:
            self.install(config.XRAY_BACKUP_PATH, content, private=True)

    def write(self, content):
        self.install(config.XRAY_CONFIG_PATH, content)

    def restore(self, content):
        if content is not None:
            self.write(content)
        else:
            try:
                config.XRAY_CONFIG_PATH.unlink(missing_ok=True)
            except PermissionError:
                self.run(["sudo", "-n", "rm", "-f", "--", str(config.XRAY_CONFIG_PATH)])
