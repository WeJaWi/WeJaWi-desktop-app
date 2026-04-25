
# core/vpn_control.py
# Minimal Proton VPN CLI wrapper + custom-command backend.
# Avoids non-stdlib dependencies and shells out to available tools.

import shutil
import subprocess
from typing import Tuple

def _exists_on_path(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None

class ProtonVPNController:
    def __init__(self):
        self._exe = _exists_on_path(["protonvpn-cli","protonvpn","protonvpn-cli.exe","protonvpn.exe"])

    def is_available(self) -> bool:
        return bool(self._exe)

    def _run(self, *args) -> Tuple[bool, str]:
        if not self._exe:
            return False, "Proton VPN CLI not found"
        try:
            proc = subprocess.run([self._exe, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
            out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            return proc.returncode == 0, out or f"Exit code {proc.returncode}"
        except subprocess.TimeoutExpired:
            return False, "Timed out"
        except Exception as e:
            return False, str(e)

    def status(self) -> Tuple[bool, str]:
        ok, out = self._run("status")
        if not ok and "Unknown command" in out:
            ok, out = self._run("s")
        return ok, out

    def disconnect(self) -> Tuple[bool, str]:
        ok, out = self._run("disconnect")
        if not ok:
            ok, out = self._run("d")
        return ok, out or "Disconnected"

    def connect_country(self, code: str) -> Tuple[bool, str]:
        ok, out = self._run("connect", "--cc", code.upper())
        if not ok:
            ok, out = self._run("c", "--cc", code.upper())
        return ok, out or f"Connected to {code.upper()}"

    def connect_server(self, name: str) -> Tuple[bool, str]:
        ok, out = self._run("connect", "--server", name)
        if not ok:
            ok, out = self._run("c", "--server", name)
        return ok, out or f"Connected to {name}"

class CustomCommandVPN:
    def __init__(self):
        self.connect_cmd: str = ""
        self.disconnect_cmd: str = ""

    def _run_shell(self, cmd: str) -> Tuple[bool, str]:
        if not cmd:
            return False, "No command set"
        try:
            proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            return proc.returncode == 0, out or f"Exit code {proc.returncode}"
        except subprocess.TimeoutExpired:
            return False, "Timed out"
        except Exception as e:
            return False, str(e)

    def run_connect(self) -> Tuple[bool, str]:
        return self._run_shell(self.connect_cmd)

    def run_disconnect(self) -> Tuple[bool, str]:
        return self._run_shell(self.disconnect_cmd)
