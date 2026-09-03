#!/usr/bin/env python3
"""Prepare the Lithuanian model, converting it if nobody has published a
CTranslate2 build.

kristijonas/paprika-whisper-lt is a Whisper fine-tune that recognises Lithuanian
markedly better than the stock multilingual models, but it ships only in
transformers format. Converting needs torch and transformers, which are far too
heavy to keep around, so this builds a throwaway environment, converts once, and
deletes it. The result is cached and reused.

Prints the model directory on success.
"""
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO = "kristijonas/paprika-whisper-lt"

# large-v3-turbo uses 128 mel bins. The repo ships processor_config.json but not
# preprocessor_config.json, so faster-whisper falls back to 80 and fails with a
# shape error. Neither omission is documented on the model page.
PREPROCESSOR = {
    "chunk_length": 30,
    "feature_extractor_type": "WhisperFeatureExtractor",
    "feature_size": 128,
    "hop_length": 160,
    "n_fft": 400,
    "n_samples": 480000,
    "nb_max_frames": 3000,
    "padding_side": "right",
    "padding_value": 0.0,
    "processor_class": "WhisperProcessor",
    "return_attention_mask": False,
    "sampling_rate": 16000,
}


def model_dir(cache_root):
    return Path(cache_root) / "models" / "paprika-whisper-lt-ct2"


def ready(d):
    return (d / "model.bin").exists() and (d / "preprocessor_config.json").exists()


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".cache" / "lecture-pipeline"
    out = model_dir(cache)
    if ready(out):
        print(out)
        return 0

    # stdout, not stderr: PowerShell treats a native program's stderr as an
    # error when its preference is Stop, and aborted the installer on this very
    # line. The model path is still the last line printed, which is what callers
    # read.
    print("Preparing the Lithuanian model. This happens once and takes a few minutes.",
          flush=True)
    tmp_env = out.parent / ".convert-venv"
    shutil.rmtree(tmp_env, ignore_errors=True)
    out.parent.mkdir(parents=True, exist_ok=True)

    venv.create(tmp_env, with_pip=True)
    pip = tmp_env / "bin" / "pip"
    if not pip.exists():
        pip = tmp_env / "Scripts" / "pip.exe"
    run = lambda *a: subprocess.run(list(a), check=True)
    run(str(pip), "install", "-q", "--upgrade", "pip")
    run(str(pip), "install", "-q", "torch", "--index-url",
        "https://download.pytorch.org/whl/cpu")
    run(str(pip), "install", "-q", "transformers", "ctranslate2")

    conv = tmp_env / "bin" / "ct2-transformers-converter"
    if not conv.exists():
        conv = tmp_env / "Scripts" / "ct2-transformers-converter.exe"
    shutil.rmtree(out, ignore_errors=True)
    run(str(conv), "--model", REPO, "--output_dir", str(out),
        "--copy_files", "tokenizer.json", "tokenizer_config.json",
        "--quantization", "float16")

    (out / "preprocessor_config.json").write_text(
        json.dumps(PREPROCESSOR, indent=2), encoding="utf-8")

    # The toolchain is several gigabytes and is never needed again.
    shutil.rmtree(tmp_env, ignore_errors=True)

    if not ready(out):
        print("conversion did not produce a usable model", flush=True)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
