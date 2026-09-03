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


SHARED    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared")
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
sys.path.insert(0, os.environ["LECTURE_SHARED"])
import cuda_libs; cuda_libs.enable()
from faster_whisper import WhisperModel
model, device, wav, lang, mode = sys.argv[1:6]
# float16 large-v3 peaks near 4.5 GB. On a card with less than about 6 GB
# free it will not fit, so quantise rather than fail: a quantised large-v3
# still beats dropping to medium.
if device != "cuda":
    compute = "int8"
elif int(os.environ.get("VRAM_MIB", "0") or 0) >= 6000:
    compute = "float16"
else:
    compute = "int8_float16"
m = WhisperModel(model, device=device, compute_type=compute,
                 cpu_threads=os.cpu_count() or 4)      # download happens here, untimed
if mode == "fetch":                                    # download only, untimed
    print(json.dumps({"elapsed": 0, "words": 0}))
    raise SystemExit
t0 = time.perf_counter()
# the same call the live worker makes: word timestamps cost real time and
# the interval promised to the user must be measured with them on
segs, _ = m.transcribe(wav, language=lang, vad_filter=True,
                       condition_on_previous_text=False, word_timestamps=True)
words = sum(len(s.text.split()) for s in segs)         # forces the generator
print(json.dumps({"elapsed": time.perf_counter() - t0, "words": words}))
"""


_fetched = set()          # a model is the same file whichever backend runs it


def time_faster_whisper(model, device):
    """Run in a child process: loading two 1.5 GB models in one process is
    enough to trigger the OOM killer on a 16 GB laptop."""
    if model not in _fetched:
        with Spinner(f"downloading {label(model)}"):
            subprocess.run([sys.executable, "-c", CHILD, model, "cpu", wav, lang, "fetch"],
                           capture_output=True, text=True, check=True,
                           env=dict(os.environ, VRAM_MIB=str(VRAM_MIB),
                                LECTURE_SHARED=str(SHARED)))
        _fetched.add(model)
    with Spinner(f"benchmarking {label(model)} on {device}"):
        r = subprocess.run([sys.executable, "-c", CHILD, model, device, wav, lang, "run"],
                           capture_output=True, text=True,
                           env=dict(os.environ, VRAM_MIB=str(VRAM_MIB),
                                LECTURE_SHARED=str(SHARED)))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr else "failed")
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return out["elapsed"], out["words"]


def ggml_file(model):
    """A stock model maps to whisper.cpp's download name; a converted
    directory such as paprika-whisper-lt-ct2 maps to the GGML the Lithuanian
    step produced beside it, ggml-paprika-whisper-lt.bin."""
    name = os.path.basename(model.rstrip("/")) if os.path.isdir(model) else model
    if name.endswith("-ct2"):
        name = name[:-4]
    return os.path.join(wcpp, "models", f"ggml-{name}.bin")


def time_whisper_cpp(model):
    ggml = ggml_file(model)
    if not os.path.exists(ggml) and not os.path.isdir(model):
        with Spinner(f"downloading {label(model)} for whisper.cpp"):
            subprocess.run(["sh", os.path.join(wcpp, "models", "download-ggml-model.sh"), model],
                           cwd=wcpp, check=True, capture_output=True)
    t0 = time.perf_counter()
    sp = Spinner(f"benchmarking {label(model)} on vulkan"); sp.__enter__()
    r = subprocess.run([os.path.join(wcpp, "build/bin/whisper-cli"),
                        "-m", ggml, "-l", lang, "-f", wav, "-t", str(os.cpu_count() or 4),
                        "-otxt", "-of", os.path.join(work, "bench")],
                       capture_output=True, text=True,
                       # its libraries sit beside the binary; the build's RPATH
                       # pointed into a build directory that no longer existed
                       env=dict(os.environ, LD_LIBRARY_PATH=os.path.join(wcpp, "build/bin")
                                + ":" + os.environ.get("LD_LIBRARY_PATH", "")))
    el = time.perf_counter() - t0
    sp.__exit__()
    txt = os.path.join(work, "bench.txt")
    words = len(open(txt).read().split()) if os.path.exists(txt) else 0
    if r.returncode != 0:
        return None, 0
    return el, words


def label(model):
    """A path is unreadable in a log line; show its directory name."""
    return os.path.basename(model.rstrip("/")) if os.path.isdir(model) else model


def candidates(model):
    out = []
    if os.path.isdir(model):
        # A converted CTranslate2 directory. whisper.cpp needs its own GGML
        # format, which the Lithuanian step produces when whisper.cpp is
        # built; Vulkan is offered when that file exists.
        if has_cuda:
            out.append(("cuda", lambda m=model: time_faster_whisper(m, "cuda")))
        if has_vulkan and os.path.exists(ggml_file(model)):
            out.append(("vulkan", lambda m=model: time_whisper_cpp(m)))
        out.append(("cpu", lambda m=model: time_faster_whisper(m, "cpu")))
        return out
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
FIXED = os.environ.get("LECTURE_FIXED_MODEL", "")
if FIXED:
    # Some languages have one obviously right model and no useful choice. It is
    # still measured, because whether it keeps up is a property of the machine.
    ladder = [FIXED]
    print(f"  using {os.path.basename(FIXED)}, the model for this language\n")
else:
    # The gate is free VRAM on a discrete card, not its total size. large-v3 at
    # int8_float16 peaks near 3 GB, so 4 GB free holds it. A laptop whose
    # display runs on an integrated GPU leaves the whole discrete card free,
    # and a total-size threshold would have excluded a card that fits.
    ladder = []
    if DISCRETE and VRAM_MIB >= 3800:
        ladder.append("large-v3")
    else:
        print(f"  large-v3 skipped: needs a discrete GPU with about 4 GB free, "
              f"this has {VRAM_MIB} MiB\n")
    ladder += [f"medium{suffix}", f"small{suffix}"]

disabled = {d for d in os.environ.get("LECTURE_DISABLED_MODELS", "").split(",") if d}
if disabled:
    skipped = [m for m in ladder if m in disabled]
    if skipped:
        print("  skipping, disabled on this machine: " + ", ".join(skipped) + "\n")
    ladder = [m for m in ladder if m not in disabled]

chosen = None
for model in ladder:
    for backend, fn in candidates(model):
        try:
            el, words = fn()
        except Exception as e:
            why = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
            print(f"  {label(model):<28} {backend:<8} unavailable: {why[:90]}")
            continue
        if el is None:
            print(f"  {label(model):<28} {backend:<8} failed")
            continue
        factor = dur / el
        results.append((model, backend, factor, words))
        note = "" if factor >= MIN_FACTOR else "   too slow"
        print(f"  {label(model):<28} {backend:<8} {factor:>5.1f}x real time, "
              f"{words} words{note}")

    best = max((r for r in results if r[0] == model), key=lambda r: r[2], default=None)
    if best and best[2] >= GOOD_ENOUGH:
        chosen = best
        if len(ladder) > 1:
            print(f"\n  {label(model)} clears {GOOD_ENOUGH}x, "
                  f"so nothing smaller is tested.")
        break
    if best and model != ladder[-1]:
        print(f"  {label(model)} only reached {best[2]:.1f}x, "
              f"trying the next size down\n")

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
    print("RESULT\tnone\t-\t0\t12\t30")
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
    why = ("the model for this language" if FIXED
               else "largest model that keeps up")

# How often the live caption can update.
#
# Whisper's encoder always processes exactly 30 seconds: a shorter buffer is
# padded, so it costs the same as a full one. Window size is therefore free up
# to 30s and only the update interval costs anything. Each update is one window,
# about 30/F seconds of compute, so updates must be spaced further apart than
# that. Doubling it leaves headroom for a lecture hall and a throttling laptop.
interval = max(5, int(round(2 * 30.0 / best[2])))
window = 30

print(f"Selected: {label(best[0])} on {best[1]}, {best[2]:.1f}x real time.")
print(f"Live caption: {window}s window, updating every {interval}s.")
print(why + " on this machine.")
# Tab-separated, because the model field can be a directory path and a
# path can contain spaces. A username with a space in it broke the
# space-split version on the first Windows machine to try it.
print("RESULT\t" + "\t".join([best[1], best[0], f"{best[2]:.2f}", str(interval), str(window)]))
