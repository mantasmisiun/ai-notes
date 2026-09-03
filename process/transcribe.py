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
segments, info = model.transcribe(
    audio, language=LANGUAGE, vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
    beam_size=5)


def stamp(sec):
    return str(datetime.timedelta(seconds=int(sec)))


with open(tmp, "w", encoding="utf-8") as f:
    f.write("---\n")
    f.write("type: lecture-transcript-accurate\n")
    f.write(f"model: {MODEL}\n")
    f.write(f"duration: {stamp(info.duration)}\n")
    f.write(f"generated: {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
    f.write("---\n\n")
    last = -999
    for s in segments:
        if s.start - last > 45:            # a time marker roughly every 45s
            f.write(f"\n\n**[{stamp(s.start)}]** ")
            last = s.start
        f.write(s.text.strip() + " ")
        f.flush()
    f.write("\n")

os.replace(tmp, out)
print(f"wrote {out}")
