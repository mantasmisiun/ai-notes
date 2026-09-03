#!/usr/bin/env python3
"""Transcribe one lecture recording accurately.

Writes to a .tmp and renames, so an interrupted run never leaves a file that
looks finished to the next pass.
"""
import os, sys, datetime

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "shared"))
import cuda_libs; cuda_libs.enable()

from faster_whisper import WhisperModel

audio = sys.argv[1]
out   = sys.argv[2]
tmp   = out + ".tmp"

MODEL   = os.environ.get("LECTURE_ASR_MODEL", "large-v3")
COMPUTE = os.environ.get("LECTURE_ASR_COMPUTE", "float16")
DEVICE  = os.environ.get("LECTURE_ASR_DEVICE", "cuda")
LANGUAGE = os.environ.get("LECTURE_LANGUAGE", "en")

model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
# condition_on_previous_text is off: with it on, a repetition loop that starts
# in a noisy passage feeds itself into the next segment and the next, and a
# five-minute news broadcast came back with "suvelnių" forty times in a row.
# The live worker already runs without it.
segments, info = model.transcribe(
    audio, language=LANGUAGE, vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
    beam_size=5, condition_on_previous_text=False)

# The same guards as the live worker: Whisper's own rule for narrated silence,
# compression ratio for repetition, and a word-level check for a stretched
# word, plus a back-to-back repeat collapsed to one.
STUTTER = re.compile(r"(..+?)\1{2,}")


def clean(text):
    out = []
    for w in text.split():
        if STUTTER.search(w):
            continue
        if out and out[-1].lower() == w.lower():
            continue
        out.append(w)
    return " ".join(out)


def stamp(sec):
    return str(datetime.timedelta(seconds=int(sec)))


with open(tmp, "w", encoding="utf-8") as f:
    f.write("---\n")
    f.write("type: lecture-transcript-accurate\n")
    f.write(f"model: {MODEL}\n")
    f.write(f"duration: {stamp(info.duration)}\n")
    f.write(f"generated: {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
    f.write("---\n\n")
    # Every paragraph ends with an Obsidian block id derived from its time
    # marker, ^t0-03-08 for [0:03:08], so a note can link to the exact passage
    # it was written from: [[transcript#^t0-03-08|0:03:08]].
    last = -999
    open_id = None
    for s in segments:
        if (getattr(s, "compression_ratio", 0) > 2.4
                or (getattr(s, "no_speech_prob", 0) > 0.6
                    and getattr(s, "avg_logprob", 0) < -1.0)):
            continue
        text = clean(s.text.strip())
        if not text:
            continue
        if s.start - last > 45:            # a time marker roughly every 45s
            if open_id:
                f.write(f"^{open_id}")
            label = stamp(s.start)
            open_id = "t" + label.replace(":", "-")
            f.write(f"\n\n**[{label}]** ")
            last = s.start
        f.write(text + " ")
        f.flush()
    if open_id:
        f.write(f"^{open_id}")
    f.write("\n")

os.replace(tmp, out)
print(f"wrote {out}")
