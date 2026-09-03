#!/usr/bin/env python3
"""Prepare the Lithuanian model, converting it if nobody has published a
CTranslate2 build.

kristijonas/paprika-whisper-lt is a Whisper fine-tune that recognises Lithuanian
markedly better than the stock multilingual models, but it ships only in
transformers format. Converting needs torch and transformers, which are far too
heavy to keep around, so this builds a throwaway environment, converts once, and
deletes it. The result is cached and reused.

With --wcpp <whisper.cpp root> it also produces the GGML file whisper.cpp needs
to run the same model on Vulkan, which is the only way onto an AMD or Intel GPU.
Without it the benchmark could only ever measure Lithuanian on the CPU.

Prints the model directory on success, as the last line.
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path

REPO = "kristijonas/paprika-whisper-lt"
GGML_NAME = "ggml-paprika-whisper-lt.bin"
MEL_URL = "https://raw.githubusercontent.com/openai/whisper/main/whisper/assets/mel_filters.npz"

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


def ggml_path(wcpp):
    return Path(wcpp) / "models" / GGML_NAME if wcpp else None


def convert_ggml(py, wcpp, tmp_env, env):
    """HF weights -> GGML f16, with whisper.cpp's own converter. It wants the
    model as a directory and one asset from the openai/whisper repo, the mel
    filter bank, fetched on its own rather than by cloning the repo."""
    # The Hub rate-limits unauthenticated requests and the first call can fail
    # for that alone. Try online, then from the local cache, which the
    # CTranslate2 conversion has already filled.
    snap = None
    for extra in ({}, {"HF_HUB_OFFLINE": "1"}):
        r = subprocess.run(
            [str(py), "-c", "from huggingface_hub import snapshot_download; "
                            f"print(snapshot_download('{REPO}'))"],
            capture_output=True, text=True, env=dict(env, **extra))
        if r.returncode == 0 and r.stdout.strip():
            snap = r.stdout.strip().splitlines()[-1]
            break
        print("  model download: " + r.stderr.strip().splitlines()[-1][:160], flush=True)
    if not snap:
        raise RuntimeError("could not obtain the model files from the Hub or the cache")
    assets = tmp_env / "whisper-repo" / "whisper" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MEL_URL, assets / "mel_filters.npz")
    # The converter wants the older vocab.json and added_tokens.json pair; the
    # repo ships only tokenizer.json, which holds both: the base vocabulary
    # and the added special tokens. Stage a directory that has everything.
    staged = tmp_env / "hf-model"
    staged.mkdir(exist_ok=True)
    for f in Path(snap).iterdir():
        if f.is_file() and not (staged / f.name).exists():
            os.symlink(f.resolve(), staged / f.name)
    tok = json.loads((Path(snap) / "tokenizer.json").read_text(encoding="utf-8"))
    (staged / "vocab.json").write_text(json.dumps(tok["model"]["vocab"], ensure_ascii=False),
                                       encoding="utf-8")
    (staged / "added_tokens.json").write_text(
        json.dumps({a["content"]: a["id"] for a in tok.get("added_tokens", [])},
                   ensure_ascii=False), encoding="utf-8")
    # The weights are stored in bfloat16 and the converter hands tensors
    # straight to NumPy, which has no bfloat16. A copy of the converter loads
    # the model upcast to float32 instead; the whisper.cpp checkout is not
    # touched, so a rebuild cannot lose the change.
    src = (Path(wcpp) / "models" / "convert-h5-to-ggml.py").read_text(encoding="utf-8")
    call = "WhisperForConditionalGeneration.from_pretrained(dir_model)"
    if call in src:
        src = src.replace(call, "WhisperForConditionalGeneration.from_pretrained("
                                "dir_model, torch_dtype=torch.float32)")
    conv_py = tmp_env / "convert-h5-to-ggml.py"
    conv_py.write_text(src, encoding="utf-8")
    outdir = tmp_env / "ggml-out"
    outdir.mkdir(exist_ok=True)
    subprocess.run([str(py), str(conv_py),
                    str(staged), str(tmp_env / "whisper-repo"), str(outdir)], check=True, env=env)
    produced = outdir / "ggml-model.bin"
    if not produced.exists():
        raise RuntimeError("whisper.cpp converter produced no file")
    target = ggml_path(wcpp)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), str(target))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wcpp = sys.argv[sys.argv.index("--wcpp") + 1] if "--wcpp" in sys.argv else ""
    cache = Path(args[0]) if args else Path.home() / ".cache" / "lecture-pipeline"
    out = model_dir(cache)
    need_ggml = bool(wcpp) and not ggml_path(wcpp).exists()
    if ready(out) and not need_ggml:
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
    py = tmp_env / "bin" / "python"
    if not py.exists():
        py = tmp_env / "Scripts" / "python.exe"

    # Always `python -m pip`, never pip.exe. On Windows pip refuses to upgrade
    # itself when invoked through its own executable, because it cannot replace
    # a file that is running. The version-check notice is silenced because it
    # is noise in an installer and it also goes to stderr.
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1")
    run = lambda *a: subprocess.run([str(py), "-m", "pip"] + list(a), check=True, env=env)
    run("install", "-q", "--upgrade", "pip")
    run("install", "-q", "torch", "--index-url", "https://download.pytorch.org/whl/cpu")
    run("install", "-q", "transformers", "ctranslate2", "huggingface_hub", "numpy")

    if not ready(out):
        conv = tmp_env / "bin" / "ct2-transformers-converter"
        if not conv.exists():
            conv = tmp_env / "Scripts" / "ct2-transformers-converter.exe"
        shutil.rmtree(out, ignore_errors=True)
        subprocess.run([str(conv), "--model", REPO, "--output_dir", str(out),
                        "--copy_files", "tokenizer.json", "tokenizer_config.json",
                        "--quantization", "float16"], check=True, env=env)

        (out / "preprocessor_config.json").write_text(
            json.dumps(PREPROCESSOR, indent=2), encoding="utf-8")

    if need_ggml:
        print("Converting it for whisper.cpp as well, so Vulkan can be measured.", flush=True)
        convert_ggml(py, wcpp, tmp_env, env)

    # The toolchain is several gigabytes and is never needed again.
    shutil.rmtree(tmp_env, ignore_errors=True)

    if not ready(out):
        print("conversion did not produce a usable model", flush=True)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
