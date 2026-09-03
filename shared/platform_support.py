#!/usr/bin/env python3
"""Everything the pipeline needs that differs per operating system.

The transcription and summarising stages are already portable. This module
holds the parts that are not: capturing a microphone, taking a lock, keeping
the machine awake, and telling the user something happened.
"""
import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WINDOWS = sys.platform.startswith("win")
MACOS   = sys.platform == "darwin"
LINUX   = not WINDOWS and not MACOS


# --- where machine-local scratch goes ---------------------------------------

def scratch_dir(name="lecture-pipeline"):
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif MACOS:
        base = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / name


def state_dir(name="lecture-pipeline"):
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / name / "state"
    if MACOS:
        return Path.home() / "Library" / "Application Support" / name
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / name


def venv_python(venv_dir):
    """The interpreter inside a venv. Windows puts it somewhere else, and
    sys.executable is the system Python, which has none of the dependencies."""
    venv_dir = Path(venv_dir)
    exe = venv_dir / ("Scripts/python.exe" if WINDOWS else "bin/python")
    return str(exe) if exe.exists() else sys.executable


def venv_pythonw(venv_dir):
    """The console-less interpreter on Windows, so a GUI launched from a
    shortcut does not drag a black cmd window along with it. Elsewhere the
    ordinary interpreter, which has no such distinction."""
    exe = venv_python(venv_dir)
    if WINDOWS and exe.lower().endswith("python.exe"):
        w = Path(exe[:-len("python.exe")] + "pythonw.exe")
        if w.exists():
            return str(w)
    return exe


def quiet_popen_kwargs():
    """Extra Popen arguments so a child process opens no console window.
    Only Windows creates one per child; the flag does not exist elsewhere."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# --- microphone capture -----------------------------------------------------

def default_input_device():
    """The ffmpeg input spec for the default microphone.

    Windows has no 'default' pseudo-device for dshow, so the first audio device
    has to be found by name. That listing is written to stderr and exits
    non-zero by design, which is why the return code is ignored.
    """
    if LINUX:
        return ["-f", "pulse", "-i", "default"]
    if MACOS:
        return ["-f", "avfoundation", "-i", ":0"]

    # ffmpeg writes UTF-8, but text mode decodes with the Windows locale
    # encoding, which turns a device named "... Intel(R) ..." into mojibake and
    # then no longer matches any device when passed back. Decode explicitly.
    r = subprocess.run(["ffmpeg", "-hide_banner", "-list_devices", "true",
                        "-f", "dshow", "-i", "dummy"],
                       capture_output=True, encoding="utf-8", errors="replace")
    name = None
    for line in (r.stderr or "").splitlines():
        if "(audio)" in line and '"' in line:
            name = line.split('"')[1]
            break
    if not name:
        raise RuntimeError(
            "No DirectShow audio device found. List them with:\n"
            "  ffmpeg -list_devices true -f dshow -i dummy")
    # DirectShow's default real-time buffer is small; give it headroom so a
    # brief stall on the reading side does not drop audio.
    return ["-f", "dshow", "-rtbufsize", "64M", "-i", f"audio={name}"]


# --- keeping the machine awake while recording ------------------------------

class KeepAwake:
    """Stop the machine sleeping mid-recording. A no-op where unsupported,
    because failing to inhibit is better than failing to record."""

    ES_CONTINUOUS        = 0x80000000
    ES_SYSTEM_REQUIRED   = 0x00000001
    ES_AWAYMODE_REQUIRED = 0x00000040

    def __init__(self, reason="Recording a lecture"):
        self.reason = reason
        self._proc = None

    def __enter__(self):
        if WINDOWS:
            ctypes.windll.kernel32.SetThreadExecutionState(
                self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_AWAYMODE_REQUIRED)
        elif MACOS:
            self._proc = subprocess.Popen(["caffeinate", "-i"])
        return self

    def __exit__(self, *a):
        if WINDOWS:
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
        elif self._proc:
            self._proc.terminate()


def inhibit_wrapper(reason="Recording a lecture"):
    """On Linux the reliable way to hold off sleep and a closing lid is to run
    under systemd-inhibit, so this returns a command prefix rather than a
    context manager. Empty elsewhere; those platforms use KeepAwake instead."""
    if LINUX and _has("systemd-inhibit"):
        return ["systemd-inhibit", "--what=sleep:idle:handle-lid-switch",
                "--who=ai-notes", f"--why={reason}"]
    return []


# --- notifications ----------------------------------------------------------

def notify(title, body="", replace_id=None):
    """Best effort. A missing notification must never stop a recording."""
    try:
        if LINUX and _has("notify-send"):
            cmd = ["notify-send", "-a", "Lecture", "-i", "media-record"]
            if replace_id:
                cmd += ["-r", str(replace_id)]
            cmd += ["-p", title, body]
            r = subprocess.run(cmd, capture_output=True, text=True)
            return r.stdout.strip() or None
        if MACOS:
            subprocess.run(["osascript", "-e",
                            f'display notification "{body}" with title "{title}"'],
                           capture_output=True)
        elif WINDOWS:
            ps = (f'[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,'
                  f' ContentType=WindowsRuntime] > $null; Write-Host "{title}: {body}"')
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True)
    except Exception:
        pass
    return None


# --- running on a schedule -------------------------------------------------

def register_periodic(name, command, minutes=1):
    """Run `command` every `minutes`. Returns a description of what it did, or
    raises if the platform has no supported scheduler.

    systemd on Linux, Task Scheduler on Windows, launchd on macOS. Each is
    idempotent: registering twice replaces rather than duplicates.
    """
    if WINDOWS:
        quoted = " ".join(f'"{c}"' for c in command)
        subprocess.run(["schtasks", "/Create", "/F", "/TN", name,
                        "/SC", "MINUTE", "/MO", str(minutes),
                        "/TR", quoted], check=True, capture_output=True)
        return f"scheduled task {name}, every {minutes} min"

    if MACOS:
        plist = Path.home() / "Library/LaunchAgents" / f"{name}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"        <string>{c}</string>\n" for c in command)
        plist.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f'  <key>Label</key><string>{name}</string>\n'
            f'  <key>ProgramArguments</key><array>\n{args}  </array>\n'
            f'  <key>StartInterval</key><integer>{minutes * 60}</integer>\n'
            '</dict></plist>\n')
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], check=True, capture_output=True)
        return f"launch agent {plist.name}, every {minutes} min"

    unit = Path.home() / ".config/systemd/user"
    unit.mkdir(parents=True, exist_ok=True)
    exe = " ".join(command)
    (unit / f"{name}.service").write_text(
        f"[Unit]\nDescription={name}\n\n[Service]\nType=oneshot\nExecStart={exe}\n")
    (unit / f"{name}.timer").write_text(
        f"[Unit]\nDescription={name}\n\n[Timer]\nOnBootSec=3min\n"
        f"OnUnitActiveSec={minutes}min\nAccuracySec=30s\n\n"
        "[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{name}.timer"],
                   check=True, capture_output=True)
    return f"systemd user timer {name}.timer, every {minutes} min"


# --- single-instance lock ---------------------------------------------------

class Lock:
    """Exclusive lock held for the life of the process. flock on POSIX,
    msvcrt on Windows. Returns False rather than raising when already held."""

    def __init__(self, path):
        self.path = Path(path)
        self._fh = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            if WINDOWS:
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False

    def release(self):
        if not self._fh:
            return
        try:
            if WINDOWS:
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_UN)
        except OSError:
            pass
        self._fh.close()
        self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *a):
        self.release()


def _has(cmd):
    from shutil import which
    return which(cmd) is not None
