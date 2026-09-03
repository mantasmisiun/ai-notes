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

# Room for whisper large-v3 in float16: about 3 GB of weights plus working
# memory. Only transcription is gated on this; see main().
MIN_FREE_MIB    = int(os.environ.get("LECTURE_MIN_FREE_MIB", "5000"))
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

        # Every LECTURE_* setting in config.sh reaches the children unchanged,
        # then the defaults fill whatever it left out. Built in two steps: one
        # dict() call given a key both as **mapping and as keyword raises
        # "multiple values for keyword argument", and that is what killed
        # every run right after the layout step, with the traceback in the
        # journal and nothing in run.log.
        env = dict(os.environ)
        env.update({k: v for k, v in cfg.items() if k.startswith("LECTURE_")})
        for k, v in (("LECTURE_LANGUAGE", "en"), ("LECTURE_NOTE_LANGUAGE", "en"),
                     ("LECTURE_ASR_MODEL", "large-v3"), ("LECTURE_ASR_COMPUTE", "float16"),
                     ("LECTURE_LLM", "gemma3:12b")):
            env.setdefault(k, v)
        env["LECTURE_OLLAMA_HOST"] = "127.0.0.1:11434"
        env["TRANSCRIPTIONS_DIR"] = cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
        env["UNIVERSITY_DIR"] = cfg.get("UNIVERSITY_DIR", "University")

        # Only transcription waits for free VRAM: faster-whisper needs its own
        # room beside whatever Ollama holds. Summarising must not wait, because
        # what fills the card after a summary is Ollama keeping the very model
        # the next summary needs; gating the whole run on free memory meant
        # that a deleted note was never rewritten while the model stayed
        # resident, and every minute logged "defer" instead.
        if 0 <= free < MIN_FREE_MIB:
            if needs_transcription(NOTES):
                log(f"defer transcription: only {free} MiB free")
        elif stage_transcribe(NOTES, env, free):
            return 0
        if stage_summarise(NOTES, VAULT, env):
            return 0
        stage_retire(NOTES)
        stage_retention(NOTES)
        log(f"idle: nothing to do ({free} MiB free)")
        return 0
    finally:
        lock.release()


def audio_files(NOTES):
    d = layout.auto_dir(NOTES, "audio")
    return [a for a in sorted(d.iterdir()) if a.suffix.lower() in AUDIO_EXT] if d.is_dir() else []


def needs_transcription(NOTES):
    return any(not (layout.auto_dir(NOTES, "transcripts") / f"{a.stem}.md").exists()
               and not (STATE / f"{a.stem}.tfailed").exists()
               for a in audio_files(NOTES))


def stage_transcribe(NOTES, env, free):
    for audio in audio_files(NOTES):
        stamp = audio.stem
        transcript = layout.auto_dir(NOTES, "transcripts") / f"{stamp}.md"
        if transcript.exists():
            continue
        # A recording whose transcription fails is tried twice, then set aside
        # with a marker. Retrying it every minute returned True each time and
        # nothing behind it in the queue, summaries included, ever ran.
        if (STATE / f"{stamp}.tfailed").exists():
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
            Path(str(transcript) + ".tmp").unlink(missing_ok=True)
            tf = STATE / f"{stamp}.tfails"
            n = int(tf.read_text().strip() or 0) + 1 if tf.exists() else 1
            tf.write_text(str(n))
            if n >= MAX_TRIES:
                (STATE / f"{stamp}.tfailed").touch()
                tf.unlink(missing_ok=True)
                log(f"transcribe: FAILED {stamp} twice; set aside. Delete "
                    f"{STATE / (stamp + '.tfailed')} to try again")
            else:
                log(f"transcribe: FAILED {stamp} (attempt {n})")
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
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        log("CRASH: " + traceback.format_exc().strip().replace("\n", "\n    "))
        raise
