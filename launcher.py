"""
mhr-ggate | Windows Launcher
==============================
A self-contained tkinter GUI that manages every mhr-ggate process
on Windows (and works fine on Linux/macOS too).

Features:
  - One-click start/stop for each service (Client Relay, MITM Proxy, Xray)
  - Live log output per service
  - Inline config editor with save + validation
  - Dependency checker (installs missing pip packages automatically)
  - Status dashboard with connection info
  - System tray–style task-bar title update

Usage:
  python launcher.py              # from project root
  python launcher.py --config path/to/config.json

Requirements:
  Python 3.10+ (tkinter is bundled with the Windows Python installer)
  No additional packages needed for the launcher itself.
"""

import argparse
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, scrolledtext, ttk

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).parent.resolve()
CLIENT_DIR  = ROOT / "client"
SERVER_DIR  = ROOT / "server"
DEFAULT_CFG = ROOT / "config.json"
EXAMPLE_CFG = ROOT / "config.example.json"

# ── Colours (dark-ish theme) ──────────────────────────────────────────────────

C_BG     = "#1e1e2e"
C_PANEL  = "#2a2a3e"
C_ACCENT = "#89b4fa"   # blue
C_GREEN  = "#a6e3a1"
C_RED    = "#f38ba8"
C_YELLOW = "#f9e2af"
C_TEXT   = "#cdd6f4"
C_DIM    = "#6c7086"
C_ENTRY  = "#313244"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _python() -> str:
    """Return the Python interpreter path."""
    return sys.executable


def _find_xray() -> str | None:
    """Try to find xray binary in PATH or common Windows locations."""
    for name in ("xray", "xray.exe"):
        found = shutil.which(name)
        if found:
            return found
    # Common Windows side-by-side installs
    for candidate in [
        ROOT / "xray.exe",
        ROOT / "xray" / "xray.exe",
        Path(os.environ.get("ProgramFiles", "")) / "xray" / "xray.exe",
    ]:
        if candidate.is_file():
            return str(candidate)
    return None


def _check_deps() -> list[str]:
    """Return list of missing pip packages."""
    missing = []
    for pkg in ("fastapi", "uvicorn", "httpx", "cryptography"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def _install_deps(pkgs: list[str], log_cb) -> bool:
    """pip-install missing packages, streaming output to log_cb."""
    cmd = [_python(), "-m", "pip", "install", "--quiet"] + pkgs
    log_cb(f"[pip] Installing: {' '.join(pkgs)}\n")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            log_cb(line)
        proc.wait()
        return proc.returncode == 0
    except Exception as exc:
        log_cb(f"[pip] Error: {exc}\n")
        return False


# ── ProcessManager ────────────────────────────────────────────────────────────

class ManagedProcess:
    """Wraps a subprocess with non-blocking stdout streaming to a queue."""

    def __init__(self, name: str, cmd: list[str], cwd: Path, env: dict | None = None):
        self.name  = name
        self.cmd   = cmd
        self.cwd   = cwd
        self.env   = env
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        if self.running:
            return True
        env = {**os.environ, **(self.env or {})}
        try:
            self._proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            self._thread = threading.Thread(
                target=self._pump, daemon=True, name=f"pump-{self.name}"
            )
            self._thread.start()
            return True
        except Exception as exc:
            self._q.put(f"[launcher] Failed to start: {exc}\n")
            return False

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def drain(self) -> list[str]:
        lines = []
        while True:
            try:
                lines.append(self._q.get_nowait())
            except queue.Empty:
                break
        return lines

    def _pump(self) -> None:
        try:
            for line in self._proc.stdout:
                self._q.put(line)
        except Exception:
            pass
        rc = self._proc.wait()
        self._q.put(f"[launcher] Process exited (code {rc})\n")


# ── Main GUI ──────────────────────────────────────────────────────────────────

class Launcher(tk.Tk):
    def __init__(self, config_path: Path):
        super().__init__()

        self.config_path = config_path
        self.config_data: dict = {}
        self._load_config()

        self.title("mhr-ggate Launcher")
        self.geometry("920x680")
        self.minsize(780, 560)
        self.configure(bg=C_BG)

        # Font
        self._mono = font.Font(family="Consolas", size=9)
        self._head = font.Font(family="Segoe UI", size=11, weight="bold")
        self._norm = font.Font(family="Segoe UI", size=9)

        self._build_ui()
        self._build_services()

        # Periodic UI refresh
        self._poll()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    self.config_data = json.load(f)
                return
            except Exception:
                pass
        if EXAMPLE_CFG.exists():
            try:
                with open(EXAMPLE_CFG) as f:
                    self.config_data = json.load(f)
            except Exception:
                self.config_data = {}

    def _save_config(self, new_text: str) -> bool:
        try:
            data = json.loads(new_text)
        except json.JSONDecodeError as exc:
            messagebox.showerror("JSON Error", f"Invalid JSON:\n{exc}")
            return False
        self.config_data = data
        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=2)
        messagebox.showinfo("Saved", f"Config saved to:\n{self.config_path}")
        return True

    # ── Services ──────────────────────────────────────────────────────────────

    def _build_services(self) -> None:
        cfg_path = str(self.config_path)

        xray_bin = _find_xray() or "xray"

        self.services: dict[str, ManagedProcess] = {
            "Client Relay": ManagedProcess(
                "Client Relay",
                cmd=[_python(), str(CLIENT_DIR / "client_relay.py"), "-c", cfg_path],
                cwd=CLIENT_DIR,
            ),
            "MITM Proxy": ManagedProcess(
                "MITM Proxy",
                cmd=[_python(), str(CLIENT_DIR / "proxy.py"), "-c", cfg_path],
                cwd=CLIENT_DIR,
            ),
            "Local Xray": ManagedProcess(
                "Local Xray",
                cmd=[xray_bin, "run", "-config", str(CLIENT_DIR / "xray_client.json")],
                cwd=CLIENT_DIR,
            ),
        }
        self.log_widgets: dict[str, scrolledtext.ScrolledText] = {}

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Title bar
        top = tk.Frame(self, bg=C_BG, pady=8)
        top.pack(fill="x", padx=16)
        tk.Label(top, text="⚡  mhr-ggate", font=self._head,
                 bg=C_BG, fg=C_ACCENT).pack(side="left")
        tk.Label(top, text="Domain-Fronting Relay | Iran Censorship Bypass",
                 font=self._norm, bg=C_BG, fg=C_DIM).pack(side="left", padx=8)

        # Notebook
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("TNotebook",        background=C_BG,   borderwidth=0)
        style.configure("TNotebook.Tab",    background=C_PANEL, foreground=C_TEXT,
                        padding=[12, 4])
        style.map("TNotebook.Tab",
                  background=[("selected", C_BG)],
                  foreground=[("selected", C_ACCENT)])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self._tab_status = self._build_status_tab(nb)
        self._tab_config = self._build_config_tab(nb)
        self._tab_deps   = self._build_deps_tab(nb)

        nb.add(self._tab_status, text="  Services  ")
        nb.add(self._tab_config, text="  Config  ")
        nb.add(self._tab_deps,   text="  Setup  ")

    # ── Status tab ────────────────────────────────────────────────────────────

    def _build_status_tab(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=C_BG)

        # Info panel
        info = tk.Frame(frame, bg=C_PANEL, padx=12, pady=8)
        info.pack(fill="x", padx=8, pady=(8, 4))

        self._status_vars: dict[str, tk.StringVar] = {}

        rows = [
            ("SOCKS5 proxy",  f"127.0.0.1:{self.config_data.get('socks5_port', 1080)}"),
            ("HTTP proxy",    f"127.0.0.1:{self.config_data.get('listen_port', 8085)}"),
            ("Client relay",  f"127.0.0.1:{self.config_data.get('relay_port', 10002)}"),
            ("Fronting SNI",  self.config_data.get("front_domain", "www.google.com")),
            ("GAS script ID", (self.config_data.get("script_id", "—")[:18] + "…")
             if len(self.config_data.get("script_id", "")) > 18
             else self.config_data.get("script_id", "—")),
        ]
        for i, (label, val) in enumerate(rows):
            tk.Label(info, text=label + ":", font=self._norm,
                     bg=C_PANEL, fg=C_DIM, width=18, anchor="w").grid(
                row=i, column=0, sticky="w")
            tk.Label(info, text=val, font=self._mono,
                     bg=C_PANEL, fg=C_TEXT).grid(row=i, column=1, sticky="w", padx=4)

        # Service cards
        cards = tk.Frame(frame, bg=C_BG)
        cards.pack(fill="both", expand=True, padx=8, pady=4)

        service_names = ["Client Relay", "MITM Proxy", "Local Xray"]
        self._svc_indicators: dict[str, tk.Label] = {}
        self._svc_buttons:    dict[str, tk.Button] = {}

        for col, name in enumerate(service_names):
            card = tk.Frame(cards, bg=C_PANEL, padx=10, pady=8)
            card.grid(row=0, column=col, sticky="nsew", padx=4)
            cards.columnconfigure(col, weight=1)

            # Service name
            tk.Label(card, text=name, font=self._head,
                     bg=C_PANEL, fg=C_TEXT).pack(anchor="w")

            # Status indicator
            ind = tk.Label(card, text="●  Stopped", font=self._norm,
                           bg=C_PANEL, fg=C_RED)
            ind.pack(anchor="w", pady=(2, 6))
            self._svc_indicators[name] = ind

            # Start / Stop button
            btn = tk.Button(
                card, text="Start", font=self._norm,
                bg=C_GREEN, fg="#000000", activebackground=C_ACCENT,
                relief="flat", padx=10, pady=4, cursor="hand2",
                command=lambda n=name: self._toggle(n),
            )
            btn.pack(anchor="w")
            self._svc_buttons[name] = btn

            # Log area
            log_box = scrolledtext.ScrolledText(
                card, height=12, font=self._mono,
                bg=C_ENTRY, fg=C_TEXT, insertbackground=C_TEXT,
                borderwidth=0, relief="flat",
            )
            log_box.pack(fill="both", expand=True, pady=(6, 0))
            log_box.configure(state="disabled")
            self.log_widgets[name] = log_box

        cards.rowconfigure(0, weight=1)
        return frame

    def _toggle(self, name: str) -> None:
        svc = self.services[name]
        if svc.running:
            svc.stop()
            self._append_log(name, f"[launcher] {name} stopped.\n")
        else:
            ok = svc.start()
            if ok:
                self._append_log(name, f"[launcher] {name} starting…\n")
            else:
                self._append_log(name, f"[launcher] Failed to start {name}.\n")

    def _append_log(self, name: str, text: str) -> None:
        box = self.log_widgets.get(name)
        if not box:
            return
        box.configure(state="normal")
        box.insert("end", text)
        box.see("end")
        box.configure(state="disabled")

    # ── Config tab ────────────────────────────────────────────────────────────

    def _build_config_tab(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=C_BG)

        toolbar = tk.Frame(frame, bg=C_BG, pady=6)
        toolbar.pack(fill="x", padx=8)

        def _reload():
            self._load_config()
            txt.delete("1.0", "end")
            txt.insert("1.0", json.dumps(self.config_data, indent=2))

        def _save():
            self._save_config(txt.get("1.0", "end").strip())

        def _browse():
            path = filedialog.askopenfilename(
                title="Select config.json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if path:
                self.config_path = Path(path)
                _reload()

        for (label, cmd, color) in [
            ("Reload", _reload, C_ACCENT),
            ("Save",   _save,   C_GREEN),
            ("Browse…",_browse, C_YELLOW),
        ]:
            tk.Button(
                toolbar, text=label, font=self._norm, bg=color, fg="#000000",
                relief="flat", padx=10, pady=3, cursor="hand2", command=cmd,
            ).pack(side="left", padx=3)

        tk.Label(toolbar, textvariable=tk.StringVar(value=str(self.config_path)),
                 font=self._mono, bg=C_BG, fg=C_DIM).pack(side="left", padx=8)

        txt = scrolledtext.ScrolledText(
            frame, font=self._mono, bg=C_ENTRY, fg=C_TEXT,
            insertbackground=C_TEXT, borderwidth=0, relief="flat",
        )
        txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        txt.insert("1.0", json.dumps(self.config_data, indent=2))

        return frame

    # ── Setup / deps tab ─────────────────────────────────────────────────────

    def _build_deps_tab(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=C_BG)

        tk.Label(frame, text="Setup & Dependency Check",
                 font=self._head, bg=C_BG, fg=C_ACCENT).pack(
            anchor="w", padx=16, pady=(12, 4))

        log_box = scrolledtext.ScrolledText(
            frame, height=22, font=self._mono,
            bg=C_ENTRY, fg=C_TEXT, insertbackground=C_TEXT,
            borderwidth=0, relief="flat",
        )
        log_box.pack(fill="both", expand=True, padx=8)

        def _log(text):
            log_box.configure(state="normal")
            log_box.insert("end", text)
            log_box.see("end")
            log_box.configure(state="disabled")

        def _run_check():
            log_box.configure(state="normal")
            log_box.delete("1.0", "end")
            log_box.configure(state="disabled")

            _log(f"Python:     {sys.version}\n")
            _log(f"Project:    {ROOT}\n")
            _log(f"Config:     {self.config_path}\n")

            # Config check
            _log("\n─── Config ──────────────────────────\n")
            required = ["google_ip", "front_domain", "script_id", "auth_key"]
            for key in required:
                val = self.config_data.get(key, "")
                ok  = bool(val) and "YOUR" not in str(val) and "PASTE" not in str(val)
                icon = "✔" if ok else "✘"
                _log(f"  {icon} {key}: {val or '(missing)'}\n")

            # Pip deps
            _log("\n─── Python packages ─────────────────\n")
            missing = _check_deps()
            if missing:
                _log(f"  Missing: {', '.join(missing)}\n")
                _log("  Installing…\n")
                ok = _install_deps(missing, _log)
                _log("  Done.\n" if ok else "  Install failed — run manually.\n")
            else:
                _log("  All packages present ✔\n")

            # Xray
            _log("\n─── xray-core ───────────────────────\n")
            xray = _find_xray()
            if xray:
                _log(f"  Found: {xray}\n")
                try:
                    out = subprocess.check_output([xray, "version"], text=True, timeout=4,
                                                  stderr=subprocess.STDOUT)
                    _log(f"  {out.strip().splitlines()[0]}\n")
                except Exception as exc:
                    _log(f"  Version check failed: {exc}\n")
            else:
                _log("  ✘ xray not found in PATH.\n")
                _log("    Download from https://github.com/XTLS/Xray-install\n")
                _log("    or place xray.exe in the project root.\n")

            # GAS URL
            _log("\n─── GAS endpoint ────────────────────\n")
            sid = self.config_data.get("script_id", "")
            if sid and "PASTE" not in sid:
                _log(f"  URL: https://script.google.com/macros/s/{sid}/exec\n")
            else:
                _log("  ✘ script_id not configured — edit Config tab.\n")

            _log("\n─── Done ────────────────────────────\n")

        tk.Button(
            frame, text="Run Check & Install Deps", font=self._norm,
            bg=C_ACCENT, fg="#000000", relief="flat", padx=14, pady=5,
            cursor="hand2", command=lambda: threading.Thread(
                target=_run_check, daemon=True).start(),
        ).pack(anchor="w", padx=8, pady=8)

        return frame

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        for name, svc in self.services.items():
            # Drain log lines
            for line in svc.drain():
                self._append_log(name, line)

            # Update indicator
            ind = self._svc_indicators[name]
            btn = self._svc_buttons[name]
            if svc.running:
                ind.configure(text="●  Running", fg=C_GREEN)
                btn.configure(text="Stop", bg=C_RED)
            else:
                ind.configure(text="●  Stopped", fg=C_RED)
                btn.configure(text="Start", bg=C_GREEN)

        # Window title
        running = sum(1 for s in self.services.values() if s.running)
        total   = len(self.services)
        self.title(f"mhr-ggate Launcher  [{running}/{total} running]")

        self.after(500, self._poll)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        for svc in self.services.values():
            svc.stop()
        super().destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="mhr-ggate Windows/GUI Launcher")
    parser.add_argument("-c", "--config", default=str(DEFAULT_CFG),
                        help="Path to config.json")
    args = parser.parse_args()

    app = Launcher(Path(args.config))
    app.mainloop()


if __name__ == "__main__":
    main()
