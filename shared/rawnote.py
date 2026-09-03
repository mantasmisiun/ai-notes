#!/usr/bin/env python3
"""The your note: your own writing, plus a small table that decides where the
session is filed.

Written by capture, read by processing, so the format lives in one place. A
mismatch between the two would show up as lectures quietly landing in unfiled.
"""
import re
from datetime import datetime
from pathlib import Path

def vault_link(path, vault):
    """A vault-relative path for a [[wikilink]] or ![[embed]]. Obsidian wants
    forward slashes on every platform; os.path.relpath gives backslashes on
    Windows, which produced ![[Transcriptions\\audio\\...]] and a broken embed
    on every Windows recording."""
    import os
    rel = os.path.relpath(str(path), str(vault))
    if rel.endswith(".md"):
        rel = rel[:-3]
    return rel.replace(os.sep, "/")


# fillable rows first, the two the pipeline fills last
FIELDS = ["Schedule", "Area", "Subject", "Type", "Start", "End"]
NOTES_HEADING = "## Your notes"
GENERATED_MARK = "generated: lecture-pipeline"


def render(stamp, start, area="", subject="", kind="", end="",
           schedule="", live_link="", transcript_link="", summary_link=""):
    """Three parts and nothing else: one line saying what to fill in, the
    table, the links the pipeline fills, then the heading you write under."""
    rows = {"Schedule": schedule, "Area": area, "Subject": subject,
            "Type": kind, "Start": start, "End": end}
    table = "| Field | Value |\n| --- | --- |\n" + "".join(
        f"| {f} | {rows[f]} |\n" for f in FIELDS)

    def link(target):
        return f"[[{target}]]" if target else ""

    return (
        "---\n"
        f'stamp: "{stamp}"\n'
        "type: raw-note\n"
        "---\n\n"
        f"# {stamp}\n\n"
        "**Link a Schedule, or fill in Area, Subject and Type. One or the other,**\n"
        "**or this session stays in unfiled.**\n\n"
        f"{table}\n"
        f"Live: {link(live_link)}\n"
        f"Transcript: {link(transcript_link)}\n"
        f"Summary: {link(summary_link)}\n\n"
        "---\n\n"
        f"{NOTES_HEADING}\n\n")


def parse(path):
    """Return the table as a dict. Missing or malformed table gives empty
    values rather than an error, so a half-filled note is still usable."""
    text = Path(path).read_text(encoding="utf-8")
    out = {f: "" for f in FIELDS}
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in out:
            out[cells[0]] = cells[1]
    return out


def body(path):
    """Everything written below the final separator, which is where the
    template invites you to write, without the heading. Empty for an
    untouched note."""
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"^---.*?---\n", "", text, flags=re.S)     # frontmatter
    parts = re.split(r"^---\s*$", text, flags=re.M)
    if len(parts) < 2:
        return ""
    own = parts[-1].strip()
    if own.startswith(NOTES_HEADING):
        own = own[len(NOTES_HEADING):].strip()
    return own


def set_link(path, label, target):
    """Fill one of the link lines, Live / Transcript / Summary, in place. A
    note from before the template had that line gets it inserted above the
    separator instead."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    line = f"{label}: [[{target}]]"
    if re.search(rf"^{label}:.*$", text, flags=re.M):
        text = re.sub(rf"^{label}:.*$", line, text, count=1, flags=re.M)
    else:
        i = text.find("\n---\n")
        text = text[:i] + f"\n{line}\n" + text[i:] if i >= 0 else text + f"\n{line}\n"
    p.write_text(text, encoding="utf-8")


def set_field(path, field, value):
    """Update one table cell in place, leaving everything else untouched."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) >= 2 and cells[0] == field:
            lines[i] = f"| {field} | {value} |\n"
            break
    p.write_text("".join(lines), encoding="utf-8")


def is_generated(path):
    """True for a timetable this pipeline created. It appends rows only to
    those; a hand-maintained schedule is read and never written."""
    p = Path(path)
    return p.exists() and GENERATED_MARK in p.read_text(encoding="utf-8")[:400]
