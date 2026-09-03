#!/usr/bin/env python3
"""Where the pipeline's files live inside the vault, and the one rule about them.

    Transcriptions/
      raw notes/       yours: edit freely
      auto/            written by the pipeline; anything typed here is lost
        live/          rewritten while recording, deleted once the note exists
        transcripts/   generated once from the audio, kept
        audio/         deleted N days after the note is written
        unfiled/       notes waiting for an Area and Subject

One parent, one rule, visible in the file explorer without a legend. Each
generated folder also carries an _about.md written from the live config, so
the retention it states is never stale the way a number in a folder name is.

Earlier versions kept the four generated folders directly under
Transcriptions, beside raw notes, with nothing to say which were safe to edit.
migrate() moves such a vault to this layout and rewrites every link, so nobody
moves anything by hand. It runs on both machines and is idempotent, so
whichever side sees the old layout first does the work and the other finds
nothing left to do.
"""
import os
import re
from pathlib import Path

AUTO = "auto"
GENERATED = ("live", "transcripts", "audio", "unfiled")
RAW = "raw notes"
ABOUT = "_about.md"


def auto_dir(notes, kind):
    return Path(notes) / AUTO / kind


def raw_dir(notes):
    return Path(notes) / RAW


def ensure(notes):
    for k in GENERATED:
        auto_dir(notes, k).mkdir(parents=True, exist_ok=True)
    raw_dir(notes).mkdir(parents=True, exist_ok=True)


def link(tr_name, kind, name):
    """Vault-relative wikilink target, forward slashes whatever the OS."""
    if kind == RAW:
        return f"{tr_name}/{RAW}/{name}"
    return f"{tr_name}/{AUTO}/{kind}/{name}"


def _patterns(tr_name):
    return [(re.compile(re.escape(tr_name) + r"[/\\]" + re.escape(k) + r"[/\\]"),
             f"{tr_name}/{AUTO}/{k}/") for k in GENERATED]


def _rewrite(text, pats):
    for rx, rep in pats:
        text = rx.sub(rep, text)
    return text


def migrate(notes, vault, log=print):
    """Move an old-layout vault under auto/ and rewrite the links. Returns
    True when there was something to move."""
    notes, vault = Path(notes), Path(vault)
    old = [k for k in GENERATED if (notes / k).is_dir()]
    if not old:
        return False
    moved = 0
    for k in old:
        src, dst = notes / k, auto_dir(notes, k)
        dst.mkdir(parents=True, exist_ok=True)
        for f in list(src.iterdir()):
            if f.is_dir():
                continue
            target = dst / f.name
            if target.exists():
                # the other machine moved it already and sync delivered both;
                # the leftover is redundant only if it is the same file
                if f.stat().st_size == target.stat().st_size:
                    f.unlink()
                else:
                    log(f"layout: {target.name} already exists with a different size; "
                        f"leaving the old copy in {src}")
                continue
            os.replace(f, target)
            moved += 1
        try:
            src.rmdir()
        except OSError:
            log(f"layout: {src} is not empty and was left in place")

    pats = _patterns(notes.name)
    changed = 0
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = Path(root) / fn
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            new = _rewrite(text, pats)
            if new != text:
                tmp = p.with_name(p.name + ".tmp")
                tmp.write_text(new, encoding="utf-8")
                os.replace(tmp, p)
                changed += 1
    log(f"layout: moved {moved} files under {notes.name}/{AUTO} and "
        f"rewrote links in {changed} notes")
    return True


def fix_markers(notes, state_dir):
    """Completion markers hold a note's absolute path. After the other machine
    migrated, that path is stale while the note is fine; without this the
    pipeline would decide every note had been deleted and write them all
    again."""
    pats = _patterns(Path(notes).name)
    for m in Path(state_dir).glob("*.done"):
        try:
            old = m.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not old or Path(old).exists():
            continue
        new = _rewrite(old, pats)
        if new != old and Path(new).exists():
            m.write_text(new, encoding="utf-8")


def _about_texts(notes, keep_days):
    n = Path(notes).name
    return {
        Path(notes) / AUTO: f"""# Written by the pipeline

Everything in this folder and below it is written by the lecture pipeline.
Anything you type here is overwritten or deleted. Your own notes belong in
`{n}/{RAW}`.

| folder | what it is | what happens to it |
| --- | --- | --- |
| live | the rough transcript, rewritten every few seconds while recording | deleted once the finished note exists |
| transcripts | the accurate transcript, generated once from the audio | kept |
| audio | the recording | deleted {keep_days} days after its note is written |
| unfiled | finished notes that do not know their Area and Subject yet | filed once you fill the raw note's table |
""",
        auto_dir(notes, "live"): """# Live transcripts

Rewritten every few seconds while a recording runs, so anything you type
here is lost within seconds. Write in your raw note instead. Deleted once the
finished note exists.
""",
        auto_dir(notes, "transcripts"): """# Transcripts

Generated once from the audio, then kept. Every paragraph ends with an id
such as `^t0-03-08`; the finished notes link to those, so editing here can
break the links. To have a transcript redone, delete it while the audio still
exists.
""",
        auto_dir(notes, "audio"): f"""# Recordings

Kept for {keep_days} days after the finished note is written, then deleted.
The note and the transcript stay; only the embedded player in them stops
working. Copy a recording elsewhere if you want to keep it.
""",
        auto_dir(notes, "unfiled"): """# Unfiled notes

Finished notes that do not know where they belong. To file one, open its raw
note and fill in the table: link a Schedule, or give an Area and a Subject.
The pipeline moves the note on its next run. Do not drag notes out of here by
hand: the pipeline would not know where they went.
""",
        raw_dir(notes): """# Your notes

One note per recording, created when recording starts, yours from then on.
Write in it during the lecture. Fill in the table to say what the recording
is and where to file it; the summariser reads your notes and trusts them over
the transcript for names and terms. The pipeline only fills in the End time
and adds a link to the finished note.
""",
    }


SESSIONS_ABOUT = """# Session notes

Written by the pipeline once, yours after that. Annotate freely: nothing
rewrites a note that exists. Delete one to have it written again from the
transcript.
"""

_FRONT = "---\ntype: pipeline-about\ngenerated: lecture-pipeline\n---\n\n"


def _write_if_changed(path, body):
    content = _FRONT + body
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_about(notes, keep_days=7):
    for d, body in _about_texts(notes, keep_days).items():
        _write_if_changed(d / ABOUT, body)


def write_sessions_about(sessions_dir):
    """Only when missing: this folder sits among the user's own notes."""
    p = Path(sessions_dir) / ABOUT
    if not p.exists():
        _write_if_changed(p, SESSIONS_ABOUT)
