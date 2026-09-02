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

## Your own notes

Recording creates two files: the live transcript, which the pipeline writes,
and a notes file, which only you write. They cross-link, so both open side by
side in Obsidian.

They are separate files rather than two halves of one because the transcript is
appended to every twelve seconds. A single Obsidian buffer holding both your
typing and those appends loses one of them on save.

What you write is used twice. It goes into the summarising prompt with an
instruction to trust your notes over the transcript on terminology and
emphasis, which is exactly where speech recognition fails. And it is copied
verbatim into the final note, so your own thinking survives rather than being
paraphrased away.

Anything already filed for the same lecture in the module folder is picked up
too, so notes written before the lecture count. The pipeline skips its own
output, so it can never read its own summaries back in.

## Requirements

Capture: Linux with PipeWire or PulseAudio, ffmpeg, Python 3.11+, systemd.
PyQt6 for the tray indicator.

Processing: an NVIDIA GPU with at least 8 GB, ffmpeg, Python 3.11+, Ollama.

## Install

```bash
git clone https://github.com/<you>/lecture-pipeline.git ~/lecture-pipeline
cd ~/lecture-pipeline
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

Capture is Linux only. The transcription and summarising stages are portable
Python, but the wrapper around them uses systemd, flock, systemd-inhibit and
PulseAudio capture, none of which exist on Windows. Porting means moving that
wrapper into Python rather than translating it.
