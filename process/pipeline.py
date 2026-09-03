#!/usr/bin/env python3
"""Advance one recording through the pipeline. Replaces run.sh.

Level-triggered: works out what state each recording is in by looking at which
files exist, and advances exactly one of them. Correct after a reboot, after a
missed run, and after being killed mid-work.
"""
import os
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
import layout

MIN_FREE_MIB    = int(os.environ.get("LECTURE_MIN_FREE_MIB", "7000"))
KEEP_AUDIO_DAYS = int(os.environ.get("LECTURE_KEEP_AUDIO_DAYS", "7"))
MAX_TRIES       = 2      # then ask, rather than pinning the GPU forever
RETRY_BACKOFF   = 300
AUDIO_EXT       = (".ogg", ".mp3", ".m4a", ".wav")

STATE = ps.state_dir("lecture-notes")
LOG   = STATE / "run.log"


def log(msg):
    STATE.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def read_config():
    cfg, path = {}, ROOT / "config.sh"
    if not path.exists():
        sys.exit("no config.sh; run the installer first")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^\s*([A-Z_]+)="?(.*?)"?\s*$', line)
        if m and not line.lstrip().startswith("#"):
            cfg[m.group(1)] = os.path.expandvars(m.group(2))
    return cfg


def gpu_free_mib():
    """Free VRAM. Utilisation is deliberately not consulted: a browser playing
    video pins it near 100% while using almost no memory."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
        return int(r.stdout.strip().splitlines()[0].replace(",", ""))
    except Exception:
        return -1                       # unknown, do not block on it


def venv_py():
    return ps.venv_python(HERE / "venv")


def main():
    cfg     = read_config()
    VAULT   = Path(cfg["VAULT"])
    NOTES   = VAULT / cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
    lock = ps.Lock(STATE / "run.lock")
    if not lock.acquire():
        log("skip: another run holds the lock")
        return 0

    try:
        # Generated folders live under auto/. An old flat vault is moved and its
        # links rewritten once; markers that still name the old note paths are
        # repaired so nothing is summarised twice.
        layout.migrate(NOTES, VAULT, log=log)
        layout.ensure(NOTES)
        layout.fix_markers(NOTES, STATE)
        layout.write_about(NOTES, KEEP_AUDIO_DAYS)

        # Never process during a recording on this same machine: the live
        # transcript has a person waiting on it and wins the GPU.
        rec = ps.state_dir("lecture-pipeline") / "record.lock"
        if rec.exists():
            probe = ps.Lock(rec)
            if not probe.acquire():
                log("defer: a recording is in progress on this machine")
                return 0
            probe.release()

        free = gpu_free_mib()
        if 0 <= free < MIN_FREE_MIB:
            log(f"defer: only {free} MiB free")
            return 0

        # every LECTURE_* setting in config.sh reaches the children unchanged
        env = dict(os.environ, **{k: v for k, v in cfg.items() if k.startswith("LECTURE_")},
                   LECTURE_LANGUAGE=cfg.get("LECTURE_LANGUAGE", "en"),
                   LECTURE_NOTE_LANGUAGE=cfg.get("LECTURE_NOTE_LANGUAGE", "en"),
                   LECTURE_ASR_MODEL=cfg.get("LECTURE_ASR_MODEL", "large-v3"),
                   LECTURE_ASR_COMPUTE=cfg.get("LECTURE_ASR_COMPUTE", "float16"),
                   LECTURE_LLM=cfg.get("LECTURE_LLM", "gemma3:12b"),
                   LECTURE_OLLAMA_HOST="127.0.0.1:11434",
                   TRANSCRIPTIONS_DIR=cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions"),
                   UNIVERSITY_DIR=cfg.get("UNIVERSITY_DIR", "University"))

        if stage_transcribe(NOTES, env, free):
            return 0
        if stage_summarise(NOTES, VAULT, env):
            return 0
        stage_retire(NOTES)
        stage_retention(NOTES)
        log(f"idle: nothing to do ({free} MiB free)")
        return 0
    finally:
        lock.release()


def stage_transcribe(NOTES, env, free):
    for audio in sorted(layout.auto_dir(NOTES, "audio").iterdir() if layout.auto_dir(NOTES, "audio").is_dir() else []):
        if audio.suffix.lower() not in AUDIO_EXT:
            continue
        stamp = audio.stem
        transcript = layout.auto_dir(NOTES, "transcripts") / f"{stamp}.md"
        if transcript.exists():
            continue

        # A file can exist without having finished arriving, and nothing about
        # the file itself reveals that: sync tools preserve the source mtime,
        # and a truncated Opus stream is a valid Opus stream that decodes
        # cleanly. So watch it stop changing instead.
        size_file = STATE / f"{stamp}.size"
        size_now  = audio.stat().st_size
        if size_now == 0:
            stuck = STATE / f"{stamp}.stuck"
            if not stuck.exists():
                stuck.touch()
                log(f"STUCK: {stamp} is 0 bytes here; sync has not delivered the audio")
            continue
        (STATE / f"{stamp}.stuck").unlink(missing_ok=True)
        prev = size_file.read_text().strip() if size_file.exists() else ""
        if str(size_now) != prev:
            size_file.write_text(str(size_now))
            log(f"waiting: {stamp} is still arriving ({size_now} bytes)")
            continue

        log(f"transcribe: starting {stamp} ({free} MiB free)")
        r = subprocess.run([venv_py(), str(HERE / "transcribe.py"),
                            str(audio), str(transcript)], env=env)
        if r.returncode == 0:
            log(f"transcribe: done {stamp}")
            size_file.unlink(missing_ok=True)
        else:
            log(f"transcribe: FAILED {stamp}")
            Path(str(transcript) + ".tmp").unlink(missing_ok=True)
        return True
    return False


def stage_summarise(NOTES, VAULT, env):
    for transcript in sorted(layout.auto_dir(NOTES, "transcripts").glob("*.md")):
        if transcript.name.startswith("_"):
            continue                       # _about.md is not a transcript
        stamp  = transcript.stem
        marker = STATE / f"{stamp}.done"
        if marker.exists():
            # A marker claims a note was written. If that note has since been
            # deleted the claim is false, and the work should be redone rather
            # than skipped forever. Delete the transcript too if you want a
            # recording dropped for good.
            target = Path(marker.read_text().strip())
            if target.exists():
                continue
            log(f"note for {stamp} is gone, re-summarising")
            marker.unlink()

        if (STATE / f"{stamp}.ignored").exists():
            continue                       # given up on, by you, after two failures

        # Back off between attempts. Retrying a failing summary every minute
        # pins the GPU indefinitely, which is worse than waiting.
        ra = STATE / f"{stamp}.retry_after"
        if ra.exists() and time.time() < float(ra.read_text().strip() or 0):
            continue

        log(f"summarise: starting {stamp}")
        # Stream rather than capture: summarising a long lecture takes minutes
        # and per-chunk progress is the only sign it is alive.
        out, tail = "", []
        proc = subprocess.Popen([venv_py(), str(HERE / "summarise.py"),
                                 str(transcript), stamp, str(VAULT)],
                                env=env, text=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        with open(LOG, "a", encoding="utf-8") as lf:
            for line in proc.stdout:
                line = line.rstrip()
                print(line, flush=True)
                lf.write(line + "\n")
                lf.flush()
                tail = (tail + [line])[-5:]
                if line.startswith("NOTE_PATH="):
                    out = line[len("NOTE_PATH="):]
        proc.wait()
        if proc.returncode != 0 and tail:
            log(tail[-1])

        fails_f = STATE / f"{stamp}.fails"
        if out and Path(out).exists():
            marker.write_text(out, encoding="utf-8")
            log(f"summarise: done {stamp} -> {out}")
            fails_f.unlink(missing_ok=True)
            ra.unlink(missing_ok=True)
            subprocess.run([venv_py(), str(HERE / "reindex.py"), str(VAULT)], env=env)
        else:
            fails = int(fails_f.read_text().strip() or 0) if fails_f.exists() else 0
            fails += 1
            fails_f.write_text(str(fails))
            if fails < MAX_TRIES:
                ra.write_text(str(time.time() + RETRY_BACKOFF))
                log(f"summarise: FAILED {stamp} (attempt {fails}), "
                    f"retrying in {RETRY_BACKOFF // 60} min")
            else:
                log(f"summarise: FAILED {stamp} twice, asking what to do")
                try:
                    d = subprocess.run(
                        [venv_py(), str(HERE / "failed_dialog.py"), stamp,
                         tail[-1] if tail else ""],
                        capture_output=True, text=True, timeout=600)
                    if "IGNORE" in (d.stdout or ""):
                        (STATE / f"{stamp}.ignored").touch()
                        log(f"ignoring {stamp} from now on")
                except Exception as e:
                    log(f"could not ask: {type(e).__name__}; leaving it alone")
                    (STATE / f"{stamp}.ignored").touch()
                fails_f.unlink(missing_ok=True)
                ra.unlink(missing_ok=True)
        return True
    return False


def stage_retire(NOTES):
    """Once a real note exists, the rough live transcript has no value. Guarded
    on size so a truncated summary never triggers a deletion."""
    for marker in STATE.glob("*.done"):
        stamp = marker.stem
        note  = Path(marker.read_text().strip())
        if not note.exists():
            continue
        for live in layout.auto_dir(NOTES, "live").glob(f"{stamp}*.md"):
            if note.stat().st_size > 400:
                live.unlink(missing_ok=True)
                log(f"finalise: removed live note for {stamp}")
            else:
                log(f"finalise: SKIPPED {stamp}, note too small to trust")


def stage_retention(NOTES):
    """Audio is the only irreplaceable artefact, so it goes last and late."""
    now = time.time()
    for marker in STATE.glob("*.done"):
        stamp = marker.stem
        age = int((now - marker.stat().st_mtime) // 86400)
        if age < KEEP_AUDIO_DAYS:
            continue
        for ext in AUDIO_EXT:
            a = layout.auto_dir(NOTES, "audio") / f"{stamp}{ext}"
            if a.exists():
                a.unlink()
                log(f"retention: deleted {a.name} after {age}d")


if __name__ == "__main__":
    raise SystemExit(main())
