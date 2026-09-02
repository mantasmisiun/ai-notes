#!/usr/bin/env python3
"""Capture the microphone, transcribe it in near-real-time into a markdown note,
then compress the audio into the vault and embed it.

Audio is written as headerless raw PCM so that a power cut costs only the tail,
never the whole file.
"""
import os, sys, signal, subprocess, datetime, threading

import numpy as np
from faster_whisper import WhisperModel

RATE       = 16000
CHUNK_SECS = 12
MODEL      = os.environ.get("LECTURE_MODEL", "small.en")
COMPUTE    = os.environ.get("LECTURE_COMPUTE", "int8")
THREADS    = int(os.environ.get("LECTURE_THREADS", "6"))
BITRATE    = os.environ.get("LECTURE_BITRATE", "24k")

note_path = sys.argv[1]   # markdown note
raw_path  = sys.argv[2]   # scratch .pcm, outside the vault
ogg_path  = sys.argv[3]   # final .ogg, inside the vault
vault     = sys.argv[4]   # vault root, to build the embed link

stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT,  lambda *_: stop.set())


def append(text):
    with open(note_path, "a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def transcribe(model, raw):
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(
        audio, language="en", vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segments).strip()
    if text:
        append(text + " ")


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
        capture_output=True)
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
    append(f"*Model `{MODEL}`, loading...*\n")
    model = WhisperModel(MODEL, device="cpu", compute_type=COMPUTE,
                         cpu_threads=THREADS)
    append("*ready, recording*\n\n")

    src = os.environ.get("LECTURE_INPUT", "pulse:default").split(":", 1)
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-f", src[0], "-i", src[1],
         "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE)

    want = RATE * 2 * CHUNK_SECS
    buf = b""
    try:
        with open(raw_path, "wb") as raw:
            while not stop.is_set():
                data = ff.stdout.read(4096)
                if not data:
                    append("\n*Audio source ended unexpectedly.*\n")
                    break
                raw.write(data)
                raw.flush()
                os.fsync(raw.fileno())
                buf += data
                if len(buf) >= want:
                    transcribe(model, buf)
                    buf = b""
            if buf:
                transcribe(model, buf)
    finally:
        ff.terminate()
        try:
            ff.wait(timeout=5)
        except Exception:
            ff.kill()
        finalise()


if __name__ == "__main__":
    main()
