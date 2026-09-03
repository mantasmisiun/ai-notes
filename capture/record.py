#!/usr/bin/env python3
"""Start or stop a lecture recording. Run it again to stop the one in progress.

Replaces toggle.sh. Stopping works through a file rather than a signal, because
Windows has no SIGTERM and a stop file behaves identically everywhere.
"""
import os, shutil
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE))

import platform_support as ps
import rawnote
import timetable


def say(*a):
    """print() that survives pythonw, where sys.stdout is None."""
    if sys.stdout is not None:
        try:
            print(*a, flush=True)
        except Exception:
            pass


def read_config(path):
    """config.sh is shell, but only ever KEY="value". Parse rather than source,
    so this works where there is no shell."""
    cfg = {}
    if not Path(path).exists():
        sys.exit(f"no config found at {path}\nrun the installer first")
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r'^\s*([A-Z_]+)="?(.*?)"?\s*$', line)
        if m and not line.lstrip().startswith("#"):
            cfg[m.group(1)] = os.path.expandvars(m.group(2))
    return cfg


cfg     = read_config(ROOT / "config.sh")
VAULT   = Path(cfg["VAULT"])
NOTES   = VAULT / cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
UNI     = VAULT / cfg.get("UNIVERSITY_DIR", "University")
SCRATCH = Path(cfg.get("AUDIO_SCRATCH") or ps.scratch_dir())
STATE   = ps.state_dir()
STOP    = STATE / "stop"
READY     = STATE / "ready"        # touched by the worker once the model is loaded
CAPTURING = STATE / "capturing"    # touched when the first audio byte arrives
LOCK    = STATE / "record.lock"


def main():
    STATE.mkdir(parents=True, exist_ok=True)

    lock = ps.Lock(LOCK)
    if not lock.acquire():
        # something is already recording: ask it to finish
        STOP.touch()
        ps.notify("Transcription stopped", "Writing the last chunk.")
        say("stopping the recording in progress")
        return 0

    STOP.unlink(missing_ok=True)
    READY.unlink(missing_ok=True)
    CAPTURING.unlink(missing_ok=True)

    # Plasma runs a dock launcher inside a systemd unit of its own and, while
    # that unit is alive, treats the launcher as "running": a click does
    # nothing, so the icon that started a recording could not stop it, while
    # the tray icon, which runs this script directly, could. The recording
    # therefore hands itself to a unit of its own and the launcher's unit ends
    # at once, so the next click runs this script again and stops it.
    # OOMPolicy=continue: systemd's default stops the whole unit when the
    # kernel kills any process in it, which took this script down with the
    # worker and left the audio unconverted and the note without its footer.
    # Only when detached from a terminal; run by hand it stays in front.
    if (ps.LINUX and not os.environ.get("LECTURE_IN_UNIT")
            and not sys.stdout.isatty() and shutil.which("systemd-run")):
        lock.release()
        keep = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
                "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_DATA_DIRS", "XAUTHORITY",
                "PATH", "HOME", "LANG", "LC_ALL", "PULSE_SERVER", "QT_QPA_PLATFORMTHEME")
        passed = [f"--setenv={k}" for k in os.environ
                  if k in keep or k.startswith("LECTURE_")]
        unit = "lecture-recording-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        subprocess.run(["systemd-run", "--user", "--quiet", "--collect",
                        f"--unit={unit}", "--description=Lecture recording",
                        "-p", "OOMPolicy=continue", "--setenv=LECTURE_IN_UNIT=1",
                        *passed, "--", sys.executable, *sys.argv])
        return 0

    stamp = datetime.now().strftime("%Y-%m-%d %H%M")

    entry = timetable.match(timetable.load(str(UNI)), timetable.parse_stamp(stamp))
    code  = entry["code"] if entry else ""
    kind  = entry["kind"] if entry else ""
    label = f"{code} {kind}".strip() or "unscheduled"

    for sub in ("live", "transcripts", "audio", "unfiled", "raw notes"):
        (NOTES / sub).mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    note    = NOTES / "live" / (f"{stamp} {code} {kind}.md" if code else f"{stamp}.md")
    mynotes = NOTES / "raw notes" / f"{stamp}.md"
    raw     = SCRATCH / f"{stamp}.pcm"
    ogg     = NOTES / "audio" / f"{stamp}.ogg"

    tr = cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
    note_link    = f"{tr}/live/{note.stem}"
    mynotes_link = f"{tr}/raw notes/{mynotes.stem}"
    audio_link   = f"{tr}/audio/{stamp}.ogg"

    front = [f'stamp: "{stamp}"', f"date: {datetime.now():%Y-%m-%d}",
             f"time: {datetime.now():%H:%M}", "type: lecture-live"]
    if entry:
        front += [f"module: {code}", f'module_folder: "{entry["module_folder"]}"',
                  f"session: {kind}"]
    note.write_text(
        "---\n" + "\n".join(front) + "\n---\n\n"
        "> [!warning] Do not edit this file while recording\n"
        "> It is rewritten every few seconds as transcription catches up, so\n"
        f"> anything you type here is lost. Put your own notes in [[{mynotes_link}|your notes for this lecture]]\n"
        "> instead. They are picked up automatically when the summary is written.\n\n"
        f"# {stamp} {label}\n\n", encoding="utf-8")

    # The raw note is yours and permanent. Area and Subject decide where the
    # session is filed, prefilled from the timetable when it knows, blank when
    # this is something the schedule has never heard of.
    if not mynotes.exists():
        mynotes.write_text(rawnote.render(
            stamp,
            start=f"{datetime.now():%Y-%m-%d %H:%M}",
            schedule=(f'[[{Path(entry["path"]).stem}]]' if entry else ""),
            area="", subject="",
            kind=kind,
            transcript_link=note_link,
            audio_link=audio_link), encoding="utf-8")

    env = dict(os.environ,
               LECTURE_STOP_FILE=str(STOP),
               LECTURE_READY_FILE=str(READY),
               LECTURE_CAPTURING_FILE=str(CAPTURING),
               LECTURE_MODEL=cfg.get("LECTURE_MODEL", "small.en"),
               LECTURE_LANGUAGE=cfg.get("LECTURE_LANGUAGE", "en"),
               LECTURE_BACKEND=cfg.get("LECTURE_BACKEND", "cpu"),
               LECTURE_CHUNK_SECS=cfg.get("LECTURE_CHUNK_SECS", "12"),
               LECTURE_WINDOW_SECS=cfg.get("LECTURE_WINDOW_SECS", "30"))

    py = ps.venv_python(HERE / "venv")
    worker = [py, str(HERE / "worker.py"),
              str(note), str(raw), str(ogg), str(VAULT)]
    worker = ps.inhibit_wrapper() + worker          # empty except on Linux

    ps.notify(f"Recording {label}", note.name)
    say(f"recording {label}\n  transcript {note}\n  your notes {mynotes}")

    # Linux gets the tray dot; Windows and macOS get a window, because trays
    # are hidden by default there and a recording you cannot see is a recording
    # you forget to stop. Neither failing may prevent a recording.
    indicator = "indicator.py" if ps.LINUX else "recording_window.py"
    tray = None
    try:
        tray = subprocess.Popen([ps.venv_pythonw(HERE / "venv"), str(HERE / indicator),
                                 label, str(STOP), str(READY), str(CAPTURING)],
                                stdout=open(STATE / "indicator.log", "a"),
                                stderr=subprocess.STDOUT,
                                **ps.quiet_popen_kwargs())
    except Exception:
        pass

    with ps.KeepAwake():                            # no-op on Linux, systemd-inhibit covers it
        # Launched from a shortcut there is no console, so a worker that dies on
        # its first line would vanish without a trace and the window would
        # simply close. Its output goes to a log instead, and the exit code is
        # reported when it ends early.
        STATE.mkdir(parents=True, exist_ok=True)
        wlog = open(STATE / "worker.log", "a", encoding="utf-8", errors="replace")
        wlog.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} {stamp} ===\n")
        wlog.flush()
        proc = subprocess.Popen(worker, env=env, stdout=wlog, stderr=subprocess.STDOUT,
                                **ps.quiet_popen_kwargs())
        try:
            while proc.poll() is None:
                time.sleep(0.5)
                if STOP.exists():
                    # The worker sees the same file and shuts down on its own:
                    # it transcribes the last window, converts the audio and
                    # fills in the End time. Killing it here would lose all of
                    # that, which is exactly what TerminateProcess did on
                    # Windows. Only if it fails to finish do we force it.
                    try:
                        proc.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                    break
        except KeyboardInterrupt:
            STOP.touch()
            try:
                proc.wait(timeout=180)
            except subprocess.TimeoutExpired:
                proc.terminate()

    wlog.close()
    if proc.returncode not in (0, None) and not STOP.exists():
        # It ended without being asked to. Say so where it can be seen.
        ps.notify("Recording failed",
                  f"The worker exited with code {proc.returncode}. "
                  f"See {STATE / 'worker.log'}")
        say(f"worker exited with code {proc.returncode}; see {STATE / 'worker.log'}")
    if tray:
        tray.terminate()
    STOP.unlink(missing_ok=True)
    READY.unlink(missing_ok=True)
    CAPTURING.unlink(missing_ok=True)
    lock.release()
    say("stopped")

    # On a machine doing both halves, the accurate pass runs here and now: the
    # live transcript saw twelve seconds at a time, this one sees the whole
    # file. The lock is released first so a new recording is never blocked by
    # it, and finish.py leaves everything in place if it is cancelled, so
    # resume.py can offer it again.
    if cfg.get("WANT_PROCESS") == "1" and cfg.get("WANT_CAPTURE") == "1":
        subprocess.Popen([ps.venv_pythonw(HERE / "venv"), str(HERE / "finish.py"), stamp],
                         **ps.quiet_popen_kwargs())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
