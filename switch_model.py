#!/usr/bin/env python3
"""Try a different live model, keeping it only if this machine can run it.

Pick a model; the benchmark measures it on this machine against the sample in
your configured language. If it keeps up it becomes the live model and the
config is updated. If it does not, it is disabled here so it is not offered
again, and you are asked to pick another.

    python switch_model.py            interactive
    python switch_model.py --model medium   scripted, no prompts
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "capture"))
import platform_support as ps
from config_read import read_config, set_config

CONF = ROOT / "config.sh"


def candidates(cfg):
    """Models worth offering for this language, minus those already disabled."""
    lang = cfg.get("LECTURE_LANGUAGE", "en")
    suffix = ".en" if lang == "en" else ""
    names = [f"large-v3", f"medium{suffix}", f"small{suffix}", f"base{suffix}"]
    if lang == "lt":
        lt = Path(cfg.get("AUDIO_SCRATCH", str(ps.scratch_dir()))) / "models" / "paprika-whisper-lt-ct2"
        if lt.exists():
            names.insert(0, str(lt))
    disabled = {d for d in cfg.get("LECTURE_DISABLED_MODELS", "").split(",") if d}
    return [n for n in names if n not in disabled], disabled


def label(m):
    return Path(m).name if os.path.isdir(m) else m


def probe_env():
    """The benchmark wants the GPU facts as environment variables."""
    r = subprocess.run([sys.executable, str(ROOT / "shared" / "gpu_probe.py")],
                       capture_output=True, text=True)
    parts = (r.stdout.strip().split("\t") + ["none", "", "0", "0"])[:4]
    vendor, _, vram, discrete = parts
    return {"HAS_CUDA": "1" if vendor == "nvidia" else "0",
            "GPU_DISCRETE": discrete, "VRAM_MIB": vram}


def benchmark(model, cfg):
    """Run the benchmark on one fixed model. Returns (backend, interval) or None."""
    env = dict(os.environ, **probe_env(),
               LECTURE_FIXED_MODEL=model,
               MIN_LIVE_FACTOR=os.environ.get("MIN_LIVE_FACTOR", "1.2"))
    py = ps.venv_python(ROOT / "capture" / "venv")
    result = None
    with subprocess.Popen([py, str(ROOT / "lib" / "benchmark.py"),
                           cfg.get("LECTURE_LANGUAGE", "en"), str(ROOT / "samples"),
                           str(ROOT / ".bench")],
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace") as p:
        for line in p.stdout:
            line = line.rstrip("\n")
            print("  " + line)
            if line.startswith("RESULT\t"):
                result = line.split("\t")
    if not result or len(result) < 5 or result[1] == "none":
        return None
    return result[1], result[4]          # backend, interval seconds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="skip the menu and try this model")
    args = ap.parse_args()

    cfg = read_config(CONF)
    names, disabled = candidates(cfg)
    current = cfg.get("LECTURE_MODEL", "")

    while True:
        if args.model:
            choice = args.model
        else:
            print(f"\nLive model now: {label(current) or 'none'} on {cfg.get('LECTURE_BACKEND', '?')}")
            if disabled:
                print("Disabled on this machine: " + ", ".join(label(d) for d in sorted(disabled)))
            print("\nTry:")
            for i, n in enumerate(names, 1):
                print(f"  {i}) {label(n)}")
            print("  q) keep the current one")
            pick = input("\nSelect: ").strip().lower()
            if pick in ("q", ""):
                return 0
            try:
                choice = names[int(pick) - 1]
            except (ValueError, IndexError):
                print("not a valid choice")
                continue

        print(f"\nMeasuring {label(choice)} on this machine...\n")
        outcome = benchmark(choice, cfg)

        if outcome:
            backend, interval = outcome
            set_config(CONF, "LECTURE_MODEL", choice)
            set_config(CONF, "LECTURE_BACKEND", backend)
            set_config(CONF, "LECTURE_CHUNK_SECS", interval)
            print(f"\nKept. Live model is now {label(choice)} on {backend}, "
                  f"updating every {interval}s. Takes effect on the next recording.")
            return 0

        print(f"\n{label(choice)} cannot keep up live on this machine, or its output "
              f"failed the quality check. Disabling it here.")
        disabled.add(choice)
        set_config(CONF, "LECTURE_DISABLED_MODELS", ",".join(sorted(disabled)))
        names = [n for n in names if n != choice]
        if args.model:
            return 1
        if not names:
            print("Nothing left to try. The current model is unchanged.")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
