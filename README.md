# lecture-pipeline

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
  faster-whisper small.en (live)      stage 2  llama3.1:8b, chunked
  convert to Opus                     stage 3  retire the live note
  blinking tray icon                  stage 4  delete audio after 7 days
```

Files move between them through whatever already syncs the vault.

## Measured on the hardware it was built for

| | |
|---|---|
| Live transcription | `small.en` on a Ryzen 7 4700U, roughly real time |
| Accurate transcription | `large-v3` on an RTX 3080, **27x real time**, so 95 minutes of audio in 3m28s |
| Summarisation | 10,000 words in **31 seconds**, five chunks plus a combine pass |
| Storage | 90 minutes as Opus at 24 kbps is about 16 MB, against 170 MB as WAV |

A full day of four lectures is processed in under twenty minutes.

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
  live/         rough, written during the lecture, deleted once the note exists
  transcripts/  accurate, kept
  audio/        Opus, deleted after 7 days
  unfiled/      recordings that matched no timetable row

University/<MODULE>/
  Timetable <MODULE>.md      yours, read only
  Lectures/
    _index.md                generated, embed it with ![[Lectures/_index]]
    2026-10-09 1645 Theory - Discounted cash flow.md
```

## Requirements

Capture: Linux with PipeWire or PulseAudio, ffmpeg, Python 3.11+, systemd.
PyQt6 for the tray indicator.

Processing: an NVIDIA GPU with at least 8 GB, ffmpeg, Python 3.11+, Ollama.

## Install

```bash
git clone https://github.com/<you>/lecture-pipeline.git ~/lecture-pipeline
cd ~/lecture-pipeline
cp config.sh.example config.sh    # edit the paths
./capture/install.sh              # on the laptop
./process/install.sh              # on the machine with the GPU
```

Each machine needs its own `config.sh`, since the vault is rarely at the same
path on both. It is gitignored.

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
