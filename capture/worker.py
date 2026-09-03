#!/usr/bin/env python3
"""Capture the microphone, transcribe it in near-real-time into a markdown note,
then compress the audio into the vault and embed it.

Audio is written as headerless raw PCM so that a power cut costs only the tail,
never the whole file.
"""
import os, sys, signal, subprocess, datetime, threading

from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
import cuda_libs; cuda_libs.enable()
from faster_whisper import WhisperModel

RATE       = 16000
# Whisper's encoder always processes exactly 30 seconds: a shorter buffer is
# padded to that length, so it costs the same. Window size is therefore free up
# to 30s and only the update interval costs anything, which is why the old
# 12-second tiling wasted most of its compute and saw less context than Whisper
# expects. The interval comes from the benchmark: roughly 2 x 30 / real-time
# factor, so a fast machine updates often and a slow one does not fall behind.
WINDOW_SECS   = int(os.environ.get("LECTURE_WINDOW_SECS", "30"))
INTERVAL_SECS = int(os.environ.get("LECTURE_CHUNK_SECS", "12"))
MODEL      = os.environ.get("LECTURE_MODEL", "small.en")
# The benchmark chose a backend and the installer recorded it; the worker has to
# actually use it. device was hardcoded to cpu, so a machine measured at 12x on
# CUDA ran its live pass on the CPU at 1.5x and fell hopelessly behind.
BACKEND    = os.environ.get("LECTURE_BACKEND", "cpu").lower()
DEVICE     = "cuda" if BACKEND == "cuda" else "cpu"
COMPUTE    = os.environ.get("LECTURE_COMPUTE",
                            "int8_float16" if DEVICE == "cuda" else "int8")
THREADS    = int(os.environ.get("LECTURE_THREADS", "6"))
BITRATE    = os.environ.get("LECTURE_BITRATE", "24k")
LANGUAGE   = os.environ.get("LECTURE_LANGUAGE", "en")

note_path = sys.argv[1]   # markdown note
raw_path  = sys.argv[2]   # scratch .pcm, outside the vault
ogg_path  = sys.argv[3]   # final .ogg, inside the vault
vault     = sys.argv[4]   # vault root, to build the embed link

_quiet = dict                 # replaced once the platform layer is imported
stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT,  lambda *_: stop.set())

# On Windows a parent cannot deliver SIGTERM: Popen.terminate() there is an
# instant kill that runs no handler, so the last window was never flushed and
# the audio never converted. The stop request therefore arrives as a file, which
# works identically everywhere, and the signal handlers stay for Linux.
STOP_FILE = os.environ.get("LECTURE_STOP_FILE", "")


def stop_requested():
    return stop.is_set() or (STOP_FILE and os.path.exists(STOP_FILE))


def append(text):
    with open(note_path, "a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


class Live:
    """Keeps the note in step with a rolling window.

    Each pass re-reads the last WINDOW seconds, so text near the end can change
    as more context arrives. Anything older than one interval is settled and
    kept; the tail is provisional and rewritten each time.
    """

    def __init__(self, header):
        self.header = header
        self.settled = ""          # text that will not change again
        self.settled_until = 0.0   # audio seconds covered by settled

    def write(self, provisional=""):
        body = (self.settled + provisional).strip()
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(self.header + body + "\n")
            f.flush()
            os.fsync(f.fileno())

    def update(self, model, buf_bytes, buf_start, now):
        audio = np.frombuffer(buf_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio, language=LANGUAGE, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False)

        # Only the last interval is still in flux; everything before it has had
        # the full window of context and will not improve.
        cutoff = max(0.0, (now - buf_start) - INTERVAL_SECS)
        keep, tail = [], []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            if buf_start + seg.start < self.settled_until:
                continue                      # already settled from a prior pass
            (keep if seg.end <= cutoff else tail).append(text)

        if keep:
            self.settled = (self.settled + " " + " ".join(keep)).strip() + " "
            self.settled_until = buf_start + cutoff
        self.write(" ".join(tail))


def finalise():
    """Compress raw PCM into the vault and embed it. Keep the raw file if
    anything goes wrong, so audio is never lost to a failed conversion."""
    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        append("\n\n---\n*Stopped. No audio was captured.*\n")
        return
    os.makedirs(os.path.dirname(ogg_path), exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", raw_path,
         "-c:a", "libopus", "-b:a", BITRATE, ogg_path],
        capture_output=True, **_quiet())
    # The recording length is known precisely here, so the End cell is filled
    # in rather than left for you to type and mistype.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
        import rawnote
        notes_root = Path(ogg_path).parent.parent
        stamp_ = Path(ogg_path).stem
        rn = notes_root / "raw notes" / f"{stamp_}.md"
        if rn.exists():
            rawnote.set_field(rn, "End", f"{datetime.datetime.now():%Y-%m-%d %H:%M}")
    except Exception:
        pass                       # never let bookkeeping lose a recording

    if r.returncode == 0 and os.path.exists(ogg_path):
        rel = os.path.relpath(ogg_path, vault)
        mb  = os.path.getsize(ogg_path) / 1e6
        os.remove(raw_path)
        append(f"\n\n---\n\n## Recording\n\n![[{rel}]]\n\n"
               f"*Stopped {datetime.datetime.now():%H:%M}, {mb:.1f} MB.*\n")
    else:
        append(f"\n\n---\n*Stopped {datetime.datetime.now():%H:%M}. "
               f"Conversion failed, raw audio kept at `{raw_path}` "
               f"(s16le, {RATE} Hz, mono).*\n")


def main():
    # "none" means the benchmark found nothing on this machine that keeps up
    # live, and the user chose to record anyway. Audio is still captured and
    # converted; the accurate transcript comes later from a machine that can.
    record_only = MODEL.strip().lower() in ("", "none")
    if record_only:
        append("*Recording audio only: no live transcript on this machine. "
               "The transcript and notes are produced afterwards.*\n\n")
        model = None
    else:
        append(f"*Model `{os.path.basename(MODEL.rstrip('/'))}` on {DEVICE}, "
               f"{WINDOW_SECS}s window every {INTERVAL_SECS}s. Loading...*\n")
        model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE,
                             cpu_threads=THREADS)
        append("*ready, recording*\n\n")

    # LECTURE_INPUT lets a test run use a synthetic source instead of the mic.
    # Otherwise the spec comes from the platform layer: PulseAudio on Linux,
    # avfoundation on macOS, a named DirectShow device on Windows.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    import platform_support as ps
    global _quiet
    _quiet = ps.quiet_popen_kwargs
    if os.environ.get("LECTURE_INPUT"):
        src = os.environ["LECTURE_INPUT"].split(":", 1)
        # -re makes a synthetic source play at real time. Without it lavfi
        # generates as fast as it can, so a "25 second" test consumes the whole
        # source in seconds and never exercises the stop path at all.
        source = (["-re"] if src[0] == "lavfi" else []) + ["-f", src[0], "-i", src[1]]
    else:
        source = ps.default_input_device()

    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error"] + source +
        ["-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, **_quiet())

    # Everything record.py wrote stays as the header; the body below it is
    # rewritten each pass, because the tail of a rolling window can change.
    header = open(note_path, encoding="utf-8").read()
    live = Live(header)

    win_bytes  = RATE * 2 * WINDOW_SECS
    step_bytes = RATE * 2 * INTERVAL_SECS

    # Reading ffmpeg and transcribing must not share a thread. A pass blocks
    # for seconds, and on a machine near its limit passes run back to back, so
    # nothing drained ffmpeg and its capture buffer overflowed: the log filled
    # with "real-time buffer too full, frame dropped" and audio was lost. The
    # reader thread owns the pipe and the raw file; the main thread only
    # transcribes from a snapshot of the rolling window.
    import queue
    chunks_q = queue.Queue()

    def reader():
        with open(raw_path, "wb") as raw:
            while True:
                data = ff.stdout.read(4096)
                if not data:
                    chunks_q.put(None)
                    return
                raw.write(data)
                raw.flush()
                chunks_q.put(data)

    threading.Thread(target=reader, daemon=True).start()

    buf = b""                 # the rolling window, at most win_bytes
    since_pass = 0            # bytes accumulated since the last transcription
    total = 0                 # bytes of audio seen, for absolute timing
    ended = False

    try:
        while not stop_requested() and not ended:
            # take everything that has arrived; block briefly only when idle
            try:
                data = chunks_q.get(timeout=0.25)
            except queue.Empty:
                continue
            while data is not None:
                buf += data
                total += len(data)
                since_pass += len(data)
                try:
                    data = chunks_q.get_nowait()
                except queue.Empty:
                    break
            if data is None:
                ended = True
                live.write("\n\n*Audio source ended unexpectedly.*")
            if len(buf) > win_bytes:
                buf = buf[-win_bytes:]

            if model is not None and since_pass >= step_bytes:
                now = total / (RATE * 2)
                live.update(model, buf, now - len(buf) / (RATE * 2), now)
                since_pass = 0

        if model is not None and buf and since_pass:
            now = total / (RATE * 2)
            live.update(model, buf, now - len(buf) / (RATE * 2), now)
    finally:
        ff.terminate()
        try:
            ff.wait(timeout=5)
        except Exception:
            ff.kill()
        finalise()


if __name__ == "__main__":
    main()
