# ai-notes

Record a university lecture on a laptop, get a structured study note in the right
folder of an Obsidian vault, without touching anything in between.

Two machines with different jobs. A laptop captures audio and shows a rough live
transcript so you can follow along. A desktop with a GPU re-transcribes the
recording accurately, summarises it, files the note into the module it belongs
to, and eventually deletes the audio.

## Why it is split

The two halves have opposite requirements. Capture must run on battery, in a
lecture hall, with whatever CPU is in the laptop, and must not fail. Processing
wants a large model and a fast GPU, and can wait until you get home.

Trying to do both on the laptop means a small model transcribing in real time,
which produces text too rough to summarise. Doing both on the desktop means no
live view during the lecture. Splitting gets both.

## What runs where

```
LAPTOP                              DESKTOP (RTX 3080)
  tap a dock button                   systemd timer, every minute
  ffmpeg -> raw PCM                   stage 1  whisper large-v3
  faster-whisper small.en (live)      stage 2  gemma3:12b, chunked
  convert to Opus                     stage 3  retire the live note
  blinking tray icon                  stage 4  delete audio after 7 days
```

Files move between them through whatever already syncs the vault.

## Measured, not assumed

The installer benchmarks the machine it is running on rather than guessing.
These are its numbers on the two machines this was built for, as multiples of
real time:

| | Ryzen 7 4700U, Vega iGPU | RTX 3080 |
|---|---|---|
| English, small | 8.7x CPU / 6.4x Vulkan | |
| English, medium | 2.7x CPU / 2.9x Vulkan | |
| Lithuanian, small | 3.6x CPU / 4.3x Vulkan | |
| Lithuanian, medium | 1.7x CPU / 1.6x Vulkan | |
| English, large-v3, batch | | 27x |
| Summarising 10,000 words | | 31 s |

A full day of four 90 minute lectures is processed in under twenty minutes.

Two things those numbers taught us that guessing had got wrong. Lithuanian
costs roughly 2.4x more compute than English at the same model size, so a
machine benchmarked in English can fail in Lithuanian. And Vulkan on an
integrated GPU did not beat the CPU on any combination measured here, despite
being the obvious candidate.

## Design decisions

**Level-triggered, not event-driven.** The pipeline does not react to files
appearing. It runs on a timer, works out what state each recording is in by
looking at which artefacts exist, and advances exactly one of them. That makes it
correct after a reboot, after a missed run, and after being killed mid-work.
There is no queue to get out of sync with reality.

**State is derived, not stored.** No audio transcript means transcribe. A
transcript with no completion marker means summarise. The filesystem is the
state, so there is nothing to repair when the two disagree.

**Raw PCM, not WAV.** A WAV file written by a process that loses power leaves a
header claiming zero length, and some tools then refuse the whole file. Headerless
PCM has nothing to corrupt: a power cut costs the last fraction of a second.
Conversion to Opus happens at the end, on a file that is complete.

**Every write is temp-then-rename.** `os.replace` is atomic, so a half-written
note never looks finished to the next pass.

**The GPU guard asks the right question.** Not "is the GPU busy", which is true
constantly on a desktop with a browser open, but "is there enough free VRAM for
my model". A game occupies VRAM, so that catches the case that matters, while
video playback does not falsely defer the work.

**Nothing writes to a file the user edits.** Module timetables are read, never
written. The index that links everything together is a separate generated file,
embedded into the timetable note with one manual line. This avoids sync conflicts
between machines and means a bug in the pipeline cannot damage the schedule.

**Destructive steps are last, late and guarded.** The rough live note is only
deleted once a real note exists and is large enough to be plausible. Audio is
deleted seven days after the note is written, not immediately, so a bad
summarisation run is recoverable.

**Configuration is not inherited.** The summariser sets its own Ollama host
explicitly rather than reading `OLLAMA_HOST`, because a variable set in a shell
profile years ago should not silently redirect a pipeline to another machine.

## Filing

Module timetables already exist in the vault as markdown tables. They are parsed
rather than duplicated into config, so there is one source of truth and no drift.

```
| Date       | Start time | End time | Type     |
| 09-10-2026 | 16:45      | 18:15    | Theory   |
|            | 18:30      | 20:00    | Practice |
```

Dates appear only on the first row of a day and carry forward. A recording is
matched to a row by its timestamp, with 20 minutes of slack at each end.

Matched, the note is filed into that module. Unmatched, it goes to `unfiled/` and
waits for a human. It never guesses, because a note in the wrong module is harder
to find than one in a holding pen.

## Layout in the vault

```
Transcriptions/
  my notes/    yours: one per recording, edit freely, fill the table to file it
  auto/         written by the pipeline; anything typed here is lost
    live/         rough, rewritten during the lecture, deleted once the note exists
    transcripts/  accurate, kept; every paragraph has a block id the notes link to
    audio/        Opus, deleted 7 days after the note is written
    unfiled/      finished notes that do not know their Area and Subject yet

University/<MODULE>/
  Timetable <MODULE>.md      yours, read only
  Sessions/
    _index.md                generated, embed it with ![[Sessions/_index]]
    2026-10-09 1645 Theory - Discounted cash flow.md
```

## Your own notes

Recording creates two files: the live transcript, which the pipeline writes,
and a notes file, which only you write. They cross-link, so both open side by
side in Obsidian.

They are separate files rather than two halves of one because the transcript is
rewritten every few seconds. A single Obsidian buffer holding both your
typing and those appends loses one of them on save.

What you write is used twice. It goes into the summarising prompt with an
instruction to trust my notes over the transcript on terminology and
emphasis, which is exactly where speech recognition fails. And it is copied
verbatim into the final note, so your own thinking survives rather than being
paraphrased away.

Anything already filed for the same lecture in the module folder is picked up
too, so notes written before the lecture count. The pipeline skips its own
output, so it can never read its own summaries back in.

## Requirements

Capture: Linux with PipeWire or PulseAudio, ffmpeg, Python 3.11+, systemd.
PyQt6 for the recording indicator: a tray dot on Linux, a window elsewhere.

Processing: an NVIDIA GPU with at least 8 GB, ffmpeg, Python 3.11+, Ollama.

## Install

### Linux

```bash
git clone https://github.com/mantasmisiun/ai-notes.git
cd ai-notes
./install.sh
```

It detects what the machine can do and offers only that. With a GPU of 6 GB or
more you get a choice of the capture half, the processing half, or both. Without
one, only capture is offered, since accurate transcription on CPU is slow enough
that nobody would use it.

It then asks for your vault root, writes `config.sh`, creates the folder tree,
and leaves an `EXAMPLE001 Example Module` showing the timetable format to copy
and then delete.

Run it once per machine. Each keeps its own `config.sh`, which is gitignored,
because the vault is rarely at the same path on both.

### Windows, the quick way

Download the repository, either with `git clone` or **Code → Download ZIP** on
GitHub, then open the `windows` folder and **double-click `install.bat`**.

It checks prerequisites and installs any that are missing, asks three questions,
builds the environment, measures the machine, and puts a **Transcribe**
shortcut on your Desktop. Double-click that to start, double-click again to
stop; a window with a flashing red light stays on top while it records,
with a Stop button that waits for the last words to be transcribed.

If it installs prerequisites it will ask you to close PowerShell and run it
once more, because a running shell does not see a newly installed program.

**None of the Windows support has been run end to end.** Two real bugs were
found the first time anyone tried it, so expect a third. Every command below is
what the installer does, in case you would rather see it or something fails
partway.

### Windows, by hand

All commands run from the repository root.

In PowerShell:

```powershell
winget install Git.Git
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install Microsoft.VCRedist.2015+.x64
```

The Visual C++ redistributable is not optional. CTranslate2's Windows wheels
are built with MSVC, and without it importing faster-whisper fails with
`Could not find module ctranslate2.dll (or one of its dependencies)`, which
reads like a missing file when the file is present.

Reopen PowerShell so PATH updates, then check a microphone is visible. Nothing
below works without this. It exits with an error by design and prints the
devices to stderr; you want a line marked `(audio)`.

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

Then clone and configure:

```powershell
cd $HOME\Documents
git clone https://github.com/mantasmisiun/ai-notes.git
cd ai-notes
Copy-Item config.sh.example config.sh
notepad config.sh
```

`config.sh` is read as plain `KEY="value"` lines rather than executed, so shell
syntax is not needed. Use forward slashes:

```
VAULT="C:/Users/you/Documents/Obsidian/My Vault"
TRANSCRIPTIONS_DIR="Transcriptions"
UNIVERSITY_DIR="University"
AUDIO_SCRATCH="C:/Users/you/AppData/Local/lecture-pipeline"
WANT_CAPTURE=1
WANT_PROCESS=0
LECTURE_BACKEND="cpu"
LECTURE_LANGUAGE="en"
LECTURE_NOTE_LANGUAGE="en"
LECTURE_MODEL="small.en"
LECTURE_ASR_MODEL="large-v3"
LECTURE_ASR_COMPUTE="float16"
LECTURE_LLM="qwen3:8b"
```

**Capture:**

```powershell
python -m venv capture\venv
capture\venv\Scripts\pip install faster-whisper numpy PyQt6
capture\venv\Scripts\python -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"
capture\venv\Scripts\python capture\record.py
```

Run `record.py` again to stop. Stopping goes through a file rather than a
signal, because Windows has no SIGTERM, so a second run always reaches the
first. Make a shortcut to that command and pin it to the taskbar.

**Processing**, only on a machine with an NVIDIA card and Ollama:

```powershell
python -m venv process\venv
process\venv\Scripts\pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 PyQt6
process\venv\Scripts\python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cuda', compute_type='float16')"
ollama pull qwen3:8b
```

Set `OLLAMA_KEEP_ALIVE=30s` as a user environment variable and restart Ollama,
or the model holds VRAM and transcription never finds enough free.

Register the timer, from the repository root:

```powershell
process\venv\Scripts\python -c "import sys; sys.path.insert(0,'shared'); import platform_support as p; import os; print(p.register_periodic('lecture-notes', [os.path.abspath(r'process\venv\Scripts\python.exe'), os.path.abspath(r'process\pipeline.py')], 1))"
```

Check it with `schtasks /Query /TN lecture-notes`, and read
`%LOCALAPPDATA%\lecture-notes\state\run.log` to see what it is doing.

**Known gaps on Windows.** Sleep inhibition uses `SetThreadExecutionState`,
which stops idle sleep but not a lid close on every machine, so a recording can
end early. Notifications fall back to a console line rather than a toast. And
the Vulkan backend is Linux only. The benchmark runs on Windows too, so the
model is measured rather than assumed, and Lithuanian gets the dedicated
model there as well.

**If you install both halves on one machine**, processing refuses to start while
a recording is in progress. The live transcript has a person waiting on it, so it
wins the GPU; batch work resumes on the next tick.

## Limitations

Audio quality dominates everything. A laptop microphone ten metres from a
lecturer will hurt the transcript more than any model choice can fix.

Whisper hallucinates on silence, inventing fluent text where there is none. Voice
activity detection is enabled everywhere for this reason and is not optional.

The processing machine has to be switched on. This is batch work by design, so
that is a feature rather than a constraint, but a note does not exist until the
desktop has seen the recording.

Summarisation is not deterministic unless temperature is zero. It is set to zero
here so that a prompt change can be evaluated against the previous output rather
than against a different sample.

The main installer is bash, so Windows uses `windows\install.bat` instead.
Everything else runs there: capture, the benchmark, transcription and
summarising. Two gaps remain on Windows. Sleep inhibition uses
`SetThreadExecutionState`, which stops idle sleep but not a lid close on every
machine, so a recording can end early. And notifications fall back to a console
line rather than a toast.
