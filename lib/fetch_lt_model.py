#!/usr/bin/env python3
"""Download the Lithuanian model, Ąžuolas (akisviete/azuolas-whisper-lt).

A whisper-large-v3 fine-tune on about 9,800 hours of Lithuanian, CC BY 4.0. On
FLEURS it scores 9.05% word error rate against paprika-whisper-lt-v3's 12.06%,
and on a quiet law lecture recorded from across the room it was the only model
that produced coherent legal sentences. Its author publishes ready builds, so
nothing is converted here: this replaced a throwaway torch environment that
turned paprika-whisper-lt into both formats on every new machine.

    fetch_lt_model.py <cache root> [--float16] [--wcpp <whisper.cpp root>]
    fetch_lt_model.py <cache root> --model paprika

The faster-whisper build comes in two precisions. int8_float16 (1.5 GB) is the
default: its author measured it 0.08 WER points behind float16 on FLEURS and
level on Common Voice, and it fits a 4 GB card. --float16 (2.9 GB) is for the
processing machine's accurate pass, where precision is the point and the card
has room; it replaces an int8 download already in place.

With --wcpp it also fetches the whisper.cpp build (q4_0, 0.85 GB, 0.1 WER
points behind q8_0 by its author's measure, and the fastest on an integrated
GPU) and the Silero VAD model. This model writes fluent Lithuanian over
silence, so whisper.cpp must never run it without VAD.

--model paprika fetches the live fallback instead: paprika-whisper-lt-v3, a
large-v3-turbo fine-tune with 4 decoder layers to Ąžuolas's 32, so about three
times faster (100x against 34x real time on an RTX 3080) and less accurate
(12.06% on FLEURS). A machine whose card cannot run Ąžuolas live gets live text
from it instead of audio only. Its author publishes transformers weights only;
this is RobertasTa's int8 CTranslate2 conversion of them (0.8 GB, CC BY 4.0).

Prints the model directory on success, as the last line.
"""
import os
import sys
import urllib.request
from pathlib import Path

REPO_CT2  = "akisviete/azuolas-whisper-lt-ct2"
REPO_GGML = "akisviete/azuolas-whisper-lt-gguf"
GGML_SRC  = "azuolas-lt-whisper-q4_0.bin"
GGML_NAME = "ggml-azuolas-whisper-lt.bin"      # worker.py maps the directory name to this
VAD_URL   = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin"
VAD_NAME  = "ggml-silero-v6.2.0.bin"           # worker.py and benchmark.py look for this
# what faster-whisper reads from a model directory
CT2_FILES = ("config.json", "preprocessor_config.json", "tokenizer.json",
             "vocabulary.json", "model.bin")
VARIANT_FILE = ".variant"


def hub(repo, path):
    return f"https://huggingface.co/{repo}/resolve/main/{path}"


REPO_FALLBACK = "RobertasTa/paprika-whisper-lt-v3-ct2-int8"


def model_dir(cache_root, name="azuolas"):
    d = "paprika-whisper-lt-v3-ct2" if name == "paprika" else "azuolas-whisper-lt-ct2"
    return Path(cache_root) / "models" / d


def variant(d):
    try:
        return (d / VARIANT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ready(d):
    return all((d / f).exists() for f in CT2_FILES) and variant(d) != ""


def download(url, dest):
    """To a .part beside the target, renamed when complete, so an interrupted
    download never looks like a model. Progress every tenth, as plain lines:
    the Windows installer relays output line by line and a carriage return
    progress bar reached it as one line per update."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "ai-notes"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, shown = 0, 0
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
            got += len(block)
            if total > 50_000_000 and got * 10 // total > shown:
                shown = got * 10 // total
                print(f"  {dest.name}: {shown * 10}% of {total / 1e9:.1f} GB", flush=True)
    if total and got != total:
        raise RuntimeError(f"{dest.name}: got {got} of {total} bytes")
    os.replace(part, dest)


def fetch_ct2(d, want, repo=REPO_CT2):
    prefix = "" if want == "float16" or repo != REPO_CT2 else "int8_float16/"
    for f in CT2_FILES:
        download(hub(repo, prefix + f), d / f)
    (d / VARIANT_FILE).write_text(want, encoding="utf-8")


def main():
    # The Windows installer reads this through a pipe, where Python writes
    # cp1252, which has no Ą: the first line, "Downloading Ąžuolas", raised
    # and was reported as a failed download. Messages are ASCII, and anything
    # else (an error quoting a Lithuanian path) is replaced, never fatal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wcpp = sys.argv[sys.argv.index("--wcpp") + 1] if "--wcpp" in sys.argv else ""
    if wcpp in args:
        args.remove(wcpp)
    name = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "azuolas"
    if name in args:
        args.remove(name)
    cache = Path(args[0]) if args else Path.home() / ".cache" / "lecture-pipeline"
    want = "float16" if "--float16" in sys.argv else "int8_float16"
    out = model_dir(cache, name)

    if name == "paprika":                      # int8 is the only build there is
        try:
            if not ready(out):
                print("Downloading paprika-whisper-lt-v3, the fast live fallback (0.8 GB).",
                      flush=True)
                fetch_ct2(out, "int8_float16", REPO_FALLBACK)
        except Exception as e:
            print(f"could not download the fallback model: {e}", flush=True)
            return 1
        print(out)
        return 0

    # print, not stderr: PowerShell treats a native program's stderr as an
    # error when its preference is Stop, and aborted the installer on it
    try:
        if not ready(out) or (want == "float16" and variant(out) != "float16"):
            size = "2.9" if want == "float16" else "1.5"
            print(f"Downloading Azuolas, the Lithuanian model ({want}, {size} GB). Once only.",
                  flush=True)
            fetch_ct2(out, want)
        if wcpp:
            models = Path(wcpp) / "models"
            if not (models / GGML_NAME).exists():
                print("Downloading its whisper.cpp build (0.85 GB) for Vulkan.", flush=True)
                download(hub(REPO_GGML, GGML_SRC), models / GGML_NAME)
            if not (models / VAD_NAME).exists():
                download(VAD_URL, models / VAD_NAME)
    except Exception as e:
        print(f"could not download the Lithuanian model: {e}", flush=True)
        return 1

    if not ready(out):
        print("the download did not produce a usable model", flush=True)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
