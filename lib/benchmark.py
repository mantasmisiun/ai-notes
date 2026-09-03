#!/usr/bin/env python3
"""Measure this machine and choose a live transcription backend and model.

Models are always fetched before timing starts, because including a download in
the measurement produces a number that looks like slow hardware.

Prints a table, then one machine-readable line:
    RESULT <backend> <model> <factor>
or  RESULT none - 0
"""
import os, sys, time, json, shutil, subprocess, threading, itertools

class Spinner:
    """A dot spinner while a long step runs, so the installer never looks hung."""

    FRAMES = "|/-\\"

    def __init__(self, label):
        self.label = label
        self._stop = threading.Event()
        self._t = None

    def __enter__(self):
        if sys.stdout.isatty():
            self._t = threading.Thread(target=self._spin, daemon=True)
            self._t.start()
        else:
            print(f"  {self.label} ...", flush=True)
        return self

    def _spin(self):
        for f in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                break
            print(f"\r  {self.label} {f} ", end="", flush=True)
            time.sleep(0.12)

    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join()
            print("\r" + " " * (len(self.label) + 8) + "\r", end="", flush=True)


lang      = sys.argv[1]                     # en | lt
samples   = sys.argv[2]                     # directory holding sample-<lang>.ogg
work      = sys.argv[3]                     # scratch directory
wcpp      = sys.argv[4] if len(sys.argv) > 4 else ""   # whisper.cpp build root, "" if none
has_cuda  = os.environ.get("HAS_CUDA", "0") == "1"
has_vulkan = bool(wcpp) and os.path.isfile(os.path.join(wcpp, "build/bin/whisper-cli"))

# Two thresholds. GOOD_ENOUGH stops the search: the first model reaching it
# is chosen and nothing smaller is downloaded. MIN_FACTOR is the floor for
# accepting live transcription at all, used only if nothing reaches
# GOOD_ENOUGH.
MIN_FACTOR   = float(os.environ.get("MIN_LIVE_FACTOR", "1.2"))
GOOD_ENOUGH  = float(os.environ.get("LECTURE_GOOD_ENOUGH", "2.0"))
DISCRETE     = os.environ.get("GPU_DISCRETE", "0") == "1"
VRAM_MIB     = int(os.environ.get("VRAM_MIB", "0") or 0)

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
model, device, wav, lang, mode = sys.argv[1:6]
compute = "float16" if device == "cuda" else "int8"
m = WhisperModel(model, device=device, compute_type=compute,
                 cpu_threads=os.cpu_count() or 4)      # download happens here, untimed
if mode == "fetch":                                    # download only, untimed
    print(json.dumps({"elapsed": 0, "words": 0}))
    raise SystemExit
t0 = time.perf_counter()
segs, _ = m.transcribe(wav, language=lang, vad_filter=True)
words = sum(len(s.text.split()) for s in segs)         # forces the generator
print(json.dumps({"elapsed": time.perf_counter() - t0, "words": words}))
"""


def time_faster_whisper(model, device):
    """Run in a child process: loading two 1.5 GB models in one process is
    enough to trigger the OOM killer on a 16 GB laptop."""
    with Spinner(f"downloading {model}"):
        subprocess.run([sys.executable, "-c", CHILD, model, device, wav, lang, "fetch"],
                       capture_output=True, text=True, check=True)
    with Spinner(f"benchmarking {model} on {device}"):
        r = subprocess.run([sys.executable, "-c", CHILD, model, device, wav, lang, "run"],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr else "failed")
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return out["elapsed"], out["words"]


def time_whisper_cpp(model):
    ggml = os.path.join(wcpp, "models", f"ggml-{model}.bin")
    if not os.path.exists(ggml):
        with Spinner(f"downloading {model} for whisper.cpp"):
            subprocess.run(["sh", os.path.join(wcpp, "models", "download-ggml-model.sh"), model],
                           cwd=wcpp, check=True, capture_output=True)
    t0 = time.perf_counter()
    sp = Spinner(f"benchmarking {model} on vulkan"); sp.__enter__()
    r = subprocess.run([os.path.join(wcpp, "build/bin/whisper-cli"),
                        "-m", ggml, "-l", lang, "-f", wav, "-t", str(os.cpu_count() or 4),
                        "-otxt", "-of", os.path.join(work, "bench")],
                       capture_output=True, text=True)
    el = time.perf_counter() - t0
    sp.__exit__()
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


results = []      # (model, backend, factor, words)
print(f"Benchmark on {dur:.0f} s of {'English' if lang == 'en' else 'Lithuanian'} speech.")
print("Fetching models first, so downloads are not counted as compute time.\n")

# Largest first, stopping at the first that is comfortably real time. Nothing
# smaller is downloaded once one succeeds. large-v3 is offered only with a
# discrete card of 6 GB or more; it is 3 GB of weights and there is no point
# measuring it on hardware that cannot hold it.
ladder = []
if DISCRETE and VRAM_MIB >= 6000:
    ladder.append("large-v3")
else:
    print("  large-v3 skipped: needs a discrete GPU with 6 GB or more\n")
ladder += [f"medium{suffix}", f"small{suffix}"]

chosen = None
for model in ladder:
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
        results.append((model, backend, factor, words))
        note = "" if factor >= MIN_FACTOR else "   too slow"
        print(f"  {model:<10} {backend:<8} {factor:>5.1f}x real time, {words} words{note}")

    best = max((r for r in results if r[0] == model), key=lambda r: r[2], default=None)
    if best and best[2] >= GOOD_ENOUGH:
        chosen = best
        print(f"\n  {model} clears {GOOD_ENOUGH}x, so nothing smaller is tested.")
        break
    if best:
        print(f"  {model} only reached {best[2]:.1f}x, trying the next size down\n")

print()

# Speed alone is not enough. On this hardware small.en at int8 on CPU decoded
# only 36 s of a 43 s clip while every other candidate transcribed all of it,
# and it was the fastest of the lot. A candidate that drops a third of the
# audio must never be selected because it finished quickly.
best_words = max((r[3] for r in results), default=0)
kept = []
for model, backend, factor, words in results:
    if best_words and words < 0.6 * best_words:
        print(f"  rejecting {model} on {backend}: transcribed {words} words "
              f"where the best managed {best_words}")
        continue
    kept.append((model, backend, factor, words))
if len(kept) < len(results):
    print()
results = kept

viable = [r for r in results if r[2] >= MIN_FACTOR]
if not viable:
    print(f"Nothing reaches the {MIN_FACTOR}x minimum for live transcription.")
    print("RESULT none - 0")
    sys.exit(0)

# The ladder stops at the first model clearing GOOD_ENOUGH, so honour that
# unless the quality floor rejected it. Otherwise take the largest model that
# at least clears the minimum.
if chosen and chosen in results:
    best = chosen
    why = f"first model clearing {GOOD_ENOUGH}x"
else:
    order = {"large-v3": 3, f"medium{suffix}": 2, f"small{suffix}": 1}
    best = max(viable, key=lambda r: (order.get(r[0], 0), r[2]))
    why = "largest model that keeps up"

print(f"Selected: {best[0]} on {best[1]}, {best[2]:.1f}x real time.")
print(why + " on this machine.")
print(f"RESULT {best[1]} {best[0]} {best[2]:.2f}")
