# Windows

Capture and processing both run on Windows. The setup is manual, because the
installer is still a bash script.

**None of this has been executed on Windows.** It is written from
documentation, not from a working machine. Expect to hit something. The most
likely candidate is microphone detection, which parses ffmpeg's device listing,
and that output is not a stable interface.

## What you need first

- Python 3.11 or newer, from python.org, with "Add to PATH" ticked
- ffmpeg on PATH, `winget install Gyan.FFmpeg`
- For the processing half: an NVIDIA GPU with current drivers, and Ollama
- Git, to clone this

Check the microphone is visible before anything else:

```
ffmpeg -list_devices true -f dshow -i dummy
```

That exits with an error by design and prints the devices to stderr. You want a
line marked `(audio)`. If there is none, nothing below will record.

## Setup

```
git clone https://github.com/mantasmisiun/ai-notes.git
cd ai-notes
copy config.sh.example config.sh
```

Edit `config.sh`. It is read as plain `KEY="value"` lines rather than executed,
so shell syntax is not required, but use forward slashes in paths:

```
VAULT="C:/Users/you/Documents/Obsidian/My Vault"
TRANSCRIPTIONS_DIR="Transcriptions"
UNIVERSITY_DIR="University"
AUDIO_SCRATCH="C:/Users/you/AppData/Local/lecture-pipeline"
LECTURE_LANGUAGE="en"
LECTURE_NOTE_LANGUAGE="en"
LECTURE_MODEL="small.en"
LECTURE_ASR_MODEL="large-v3"
LECTURE_ASR_COMPUTE="float16"
LECTURE_LLM="llama3.1:8b"
```

### Capture

```
python -m venv capture\venv
capture\venv\Scripts\pip install faster-whisper numpy PyQt6
capture\venv\Scripts\python -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"
```

Record with:

```
capture\venv\Scripts\python capture\record.py
```

Run it again to stop. Make a shortcut to that command and pin it to the
taskbar. Stopping goes through a file rather than a signal, so a second run
always reaches the first one.

### Processing

```
python -m venv process\venv
process\venv\Scripts\pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12
process\venv\Scripts\python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16')"
ollama pull llama3.1:8b
```

Set Ollama to release the GPU between runs, or transcription will never find
enough free VRAM. Add `OLLAMA_KEEP_ALIVE=30s` as a user environment variable
and restart it.

Then register the timer:

```
process\venv\Scripts\python -c "import sys; sys.path.insert(0,'shared'); import platform_support as p; print(p.register_periodic('lecture-notes', [r'%CD%\process\venv\Scripts\python.exe', r'%CD%\process\pipeline.py'], 1))"
```

Check it with `schtasks /Query /TN lecture-notes`, and read
`%LOCALAPPDATA%\lecture-notes\state\run.log` to see what it is doing.

## Known gaps

Sleep inhibition uses `SetThreadExecutionState`, which stops idle sleep but not
a lid close on every machine. A recording may end early if the laptop suspends.

Notifications fall back to a console line rather than a toast.

The installer, the hardware benchmark and the Vulkan backend are Linux only, so
the model choice is whatever you put in `config.sh` rather than something
measured.
