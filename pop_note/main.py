#!/usr/bin/env python3
"""pop-note: a single note you can pop up and hide with a keybinding."""
import os
import sys
import socket
import threading
import datetime
import tkinter as tk
from pathlib import Path

import subprocess
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib

CONFIG_PATH = Path.home() / ".config" / "pop-note" / "config.toml"
DEFAULT_NOTE_PATH = Path.home() / "notes" / "pop-note.md"
DEFAULT_VERSIONS_DIR = Path.home() / ".local" / "share" / "pop-note" / "versions"
SOCKET_PATH = Path(f"/tmp/pop-note-{os.getuid()}.sock")
PIDFILE_PATH = Path(f"/tmp/pop-note-{os.getuid()}.pid")
LOG_DIR = Path.home() / ".local" / "share" / "pop-note" / "logs"
STATE_PATH = Path.home() / ".local" / "share" / "pop-note" / "state.toml"

VERSION = "8"


def load_config():
    note_path = DEFAULT_NOTE_PATH
    versions_dir = DEFAULT_VERSIONS_DIR
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
        if "note_path" in cfg:
            note_path = Path(os.path.expanduser(cfg["note_path"]))
        if "versions_dir" in cfg:
            versions_dir = Path(os.path.expanduser(cfg["versions_dir"]))
    note_path.parent.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)
    if not note_path.exists():
        note_path.write_text("")
    return note_path, versions_dir


def _read_pid():
    try:
        return int(PIDFILE_PATH.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _cleanup_stale():
    for p in (SOCKET_PATH, PIDFILE_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _ask_version():
    """Ask the running daemon what version it is. Returns string or None."""
    if not SOCKET_PATH.exists():
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(str(SOCKET_PATH))
        s.sendall(b"version\n")
        data = s.recv(64)
        s.close()
        return data.decode().strip()
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
        return None


def try_toggle_existing():
    """If a matching-version daemon is running, toggle it and return True.
    If a stale-version daemon is running, kill it and return False so we restart."""
    pid = _read_pid()
    if not _pid_alive(pid):
        _cleanup_stale()
        return False
    if not SOCKET_PATH.exists():
        return False
    running_version = _ask_version()
    if running_version != VERSION:
        print(f"pop-note: running daemon is version {running_version!r}, "
              f"need {VERSION!r} — restarting", file=sys.stderr)
        kill_existing()
        # Give it a moment to clean up
        import time
        time.sleep(0.2)
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(str(SOCKET_PATH))
        s.sendall(b"toggle\n")
        s.close()
        return True
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
        _cleanup_stale()
        return False


def kill_existing():
    pid = _read_pid()
    if not _pid_alive(pid):
        _cleanup_stale()
        print("pop-note: not running")
        return
    try:
        os.kill(pid, 15)
        print(f"pop-note: killed pid {pid}")
    except ProcessLookupError:
        pass
    _cleanup_stale()


def daemonise(log_path):
    """Standard double-fork daemonisation. Redirects stdout/stderr to log_path."""
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)


def latest_log():
    if not LOG_DIR.exists():
        return None
    logs = sorted(LOG_DIR.glob("*.log"))
    return logs[-1] if logs else None


def show_last_log():
    log = latest_log()
    if log is None:
        print("pop-note: no logs found")
        return
    print(f"# {log}")
    sys.stdout.write(log.read_text())


class PopNote:
    def __init__(self, note_path, versions_dir):
        self.note_path = note_path
        self.versions_dir = versions_dir
        self.visible = False

        self.root = tk.Tk()
        self._wm_title = f"pop-note-{os.getpid()}"
        self.root.title(self._wm_title)
        self.root.geometry("600x400")
        self.text = tk.Text(self.root, wrap="word", font=("monospace", 11),
                            undo=True)
        self.text.pack(fill="both", expand=True)

        # Override window close to hide instead of quit
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<Configure>", self._on_configure)

        # Start hidden — first toggle invocation will show it
        self.root.withdraw()

        # Listen for toggle messages
        self._start_socket_thread()

    def _start_socket_thread(self):
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except FileNotFoundError:
                pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(SOCKET_PATH))
        srv.listen(4)
        self._srv = srv

        def loop():
            while True:
                try:
                    conn, _ = srv.accept()
                    data = conn.recv(64)
                    if b"version" in data:
                        try:
                            conn.sendall(VERSION.encode() + b"\n")
                        except OSError:
                            pass
                    elif b"toggle" in data:
                        self.root.after(0, self.toggle)
                    conn.close()
                except OSError:
                    break

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def _snapshot(self, label):
        ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        content = self.text.get("1.0", "end-1c") if self.visible else self.note_path.read_text()
        path = self.versions_dir / f"{ts}-{label}.md"
        path.write_text(content)

    def _load_into_text(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.note_path.read_text())

    def _save_live(self):
        content = self.text.get("1.0", "end-1c")
        self.note_path.write_text(content)

    def _on_configure(self, event):
        # Configure fires for child widgets too — only act on the toplevel.
        if event.widget is not self.root:
            return
        if not self.visible:
            return
        self._save_geometry()

    def _load_geometry(self):
        try:
            with open(STATE_PATH, "rb") as f:
                state = tomllib.load(f)
            return state.get("geometry")
        except (FileNotFoundError, Exception):
            return None

    def _save_geometry(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            geom = self.root.winfo_geometry()  # "WxH+X+Y"
            STATE_PATH.write_text(f'geometry = "{geom}"\n')
        except Exception as e:
            print(f"failed to save geometry: {e}", flush=True)

    def _wmctrl_raise(self):
        try:
            # Match by exact title (-F) and activate (-a)
            r = subprocess.run(
                ["wmctrl", "-F", "-a", self._wm_title],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"wmctrl raise failed rc={r.returncode} "
                      f"stderr={r.stderr.strip()}", flush=True)
                # Fallback: list windows so we can see what's there
                lst = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True)
                print(f"wmctrl -l:\n{lst.stdout}", flush=True)
                self.root.lift()
                self.root.focus_force()
        except FileNotFoundError:
            print("wmctrl not installed; falling back to tk lift", flush=True)
            self.root.lift()
            self.root.focus_force()

    def _center_on_pointer(self):
        # Center the window on whichever monitor the mouse is currently on.
        self.root.update_idletasks()
        w = self.root.winfo_width() or 600
        h = self.root.winfo_height() or 400
        px = self.root.winfo_pointerx()
        py = self.root.winfo_pointery()
        x = px - w // 2
        y = py - h // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def show(self):
        if self.visible:
            return
        self._load_into_text()
        self._snapshot("show")
        self.visible = True
        self.root.deiconify()
        saved = self._load_geometry()
        if saved:
            self.root.geometry(saved)
        else:
            self._center_on_pointer()
        self.root.update_idletasks()
        self._wmctrl_raise()
        self.text.focus_set()

    def hide(self):
        if not self.visible:
            return
        self._save_live()
        self._save_geometry()
        self._snapshot("hide")
        self.visible = False
        self.root.withdraw()

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            try:
                self._srv.close()
            except Exception:
                pass
            try:
                SOCKET_PATH.unlink()
            except FileNotFoundError:
                pass
            try:
                PIDFILE_PATH.unlink()
            except FileNotFoundError:
                pass


def main():
    if "--kill" in sys.argv[1:]:
        kill_existing()
        return

    if "--last-log" in sys.argv[1:]:
        show_last_log()
        return

    if try_toggle_existing():
        return

    # No live instance — start one as a daemon and toggle it open.
    note_path, versions_dir = load_config()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    log_path = LOG_DIR / f"{ts}.log"
    daemonise(log_path)
    PIDFILE_PATH.write_text(str(os.getpid()))
    print(f"pop-note daemon started, pid={os.getpid()}", flush=True)
    try:
        app = PopNote(note_path, versions_dir)
        app.root.after(50, app.show)
        app.run()
    except Exception:
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()