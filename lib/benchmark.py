#!/usr/bin/env python3
"""Measure this machine and choose a live transcription backend and model.

Models are always fetched before timing starts, because including a download in
the measurement produces a number that looks like slow hardware.

Prints a table, then one machine-readable line:
    RESULT <backend> <model> <factor>
or  RESULT none - 0
"""
import os, sys, time, json, shutil, subprocess

lang      = sys.argv[1]                     # en | lt
samples   = sys.argv[2]                     # directory holding sample-<lang>.ogg
work      = sys.argv[3]                     # scratch directory
wcpp      = sys.argv[4] if len(sys.argv) > 4 else ""   # whisper.cpp build root, "" if none
has_cuda  = os.environ.get("HAS_CUDA", "0") == "1"
has_vulkan = bool(wcpp) and os.path.isfile(os.path.join(wcpp, "build/bin/whisper-cli"))

MIN_FACTOR   = float(os.environ.get("MIN_LIVE_FACTOR", "1.2"))
TRY_MEDIUM_AT = 2.5      # only fetch the 1.5 GB model if small suggests it may fit

suffix = ".en" if lang == "en" else ""
os.makedirs(work, exist_ok=True)

src = os.path.join(samples, f"sample-{lang}.ogg")
wav = os.path.join(work, f"sample-{lang}.wav")
if not os.path.exists(wav):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src,
                    "-ar", "16000", "-ac", "1", wav], check=True)
dur = float(subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "csv=p=0", wav], capture_output=True, text=True).stdout.strip())


CHILD = r"""
import json, os, sys, time
from faster_whisper import WhisperModel
model, device, wav, lang = sys.argv[1:5]
compute = "float16" if device == "cuda" else "int8"
m = WhisperModel(model, device=device, compute_type=compute,
                 cpu_threads=os.cpu_count() or 4)      # download happens here, untimed
t0 = time.perf_counter()
segs, _ = m.transcribe(wav, language=lang, vad_filter=True)
words = sum(len(s.text.split()) for s in segs)         # forces the generator
print(json.dumps({"elapsed": time.perf_counter() - t0, "words": words}))
"""


def time_faster_whisper(model, device):
    """Run in a child process: loading two 1.5 GB models in one process is
    enough to trigger the OOM killer on a 16 GB laptop."""
    r = subprocess.run([sys.executable, "-c", CHILD, model, device, wav, lang],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr else "failed")
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return out["elapsed"], out["words"]


def time_whisper_cpp(model):
    ggml = os.path.join(wcpp, "models", f"ggml-{model}.bin")
    if not os.path.exists(ggml):
        subprocess.run(["sh", os.path.join(wcpp, "models", "download-ggml-model.sh"), model],
                       cwd=wcpp, check=True, capture_output=True)
    t0 = time.perf_counter()
    r = subprocess.run([os.path.join(wcpp, "build/bin/whisper-cli"),
                        "-m", ggml, "-l", lang, "-f", wav, "-t", str(os.cpu_count() or 4),
                        "-otxt", "-of", os.path.join(work, "bench")],
                       capture_output=True, text=True)
    el = time.perf_counter() - t0
    txt = os.path.join(work, "bench.txt")
    words = len(open(txt).read().split()) if os.path.exists(txt) else 0
    if r.returncode != 0:
        return None, 0
    return el, words


def candidates(model):
    out = []
    if has_cuda:
        out.append(("cuda", lambda m=model: time_faster_whisper(m, "cuda")))
    if has_vulkan:
        out.append(("vulkan", lambda m=model: time_whisper_cpp(m)))
    out.append(("cpu", lambda m=model: time_faster_whisper(m, "cpu")))
    return out


results = []      # (model, backend, factor)
print(f"Benchmark on {dur:.0f} s of {'English' if lang == 'en' else 'Lithuanian'} speech.")
print("Fetching models first, so downloads are not counted as compute time.\n")

for model in [f"small{suffix}", f"medium{suffix}"]:
    if model.startswith("medium"):
        best_small = max((f for m, b, f in results), default=0)
        if best_small < TRY_MEDIUM_AT:
            print(f"  skipping medium: small only reached {best_small:.1f}x, "
                  f"medium would not keep up")
            break
    for backend, fn in candidates(model):
        try:
            el, words = fn()
        except Exception as e:
            print(f"  {model:<10} {backend:<8} unavailable ({type(e).__name__})")
            continue
        if el is None:
            print(f"  {model:<10} {backend:<8} failed")
            continue
        factor = dur / el
        results.append((model, backend, factor))
        flag = "" if factor >= MIN_FACTOR else "   too slow"
        print(f"  {model:<10} {backend:<8} {factor:>5.1f}x real time, "
              f"{words} words{flag}")

print()
viable = [r for r in results if r[2] >= MIN_FACTOR]
if not viable:
    print(f"Nothing reaches the {MIN_FACTOR}x minimum for live transcription.")
    print("RESULT none - 0")
    sys.exit(0)

# largest model that clears the bar, on its fastest backend
order = {f"medium{suffix}": 2, f"small{suffix}": 1}
best = max(viable, key=lambda r: (order.get(r[0], 0), r[2]))
print(f"Selected: {best[0]} on {best[1]}, {best[2]:.1f}x real time.")
print("Largest model that keeps up on this machine.")
print(f"RESULT {best[1]} {best[0]} {best[2]:.2f}")
