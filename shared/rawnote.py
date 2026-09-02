#!/usr/bin/env python3
"""The raw note: your own writing, plus a small table that decides where the
session is filed.

Written by capture, read by processing, so the format lives in one place. A
mismatch between the two would show up as lectures quietly landing in unfiled.
"""
import re
from datetime import datetime
from pathlib import Path

FIELDS = ["Schedule", "Area", "Subject", "Start", "End", "Type"]
GENERATED_MARK = "generated: lecture-pipeline"


def render(stamp, start, area="", subject="", kind="", end="",
           schedule="", transcript_link="", audio_link=""):
    rows = {"Schedule": schedule, "Area": area, "Subject": subject,
            "Start": start, "End": end, "Type": kind}
    table = "| Field | Value |\n| --- | --- |\n" + "".join(
        f"| {f} | {rows[f]} |\n" for f in FIELDS)

    links = ""
    if transcript_link:
        links += f"Transcript: [[{transcript_link}]]\n"
    if audio_link:
        links += f"\n![[{audio_link}]]\n"

    return (
        "---\n"
        f'stamp: "{stamp}"\n'
        "type: raw-note\n"
        "---\n\n"
        f"# {stamp}\n\n"
        "**Do one of these two things, or this stays in unfiled.**\n\n"
        "1. Link an existing schedule: start typing `[[` in the Schedule cell\n"
        "   and pick it from the list. Where that schedule lives decides\n"
        "   where this session is filed.\n"
        "2. Or fill in Area, Subject and Type yourself, and the folders are\n"
        "   created for you, with a schedule to link next time.\n\n"
        "Those three also tell the summariser what this recording is, so an\n"
        "interview or a review is not written up as though it were a lecture.\n\n"
        f"{table}\n"
        f"{links}\n"
        "---\n\n")


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
    template invites you to write. Empty for an untouched note."""
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"^---.*?---\n", "", text, flags=re.S)     # frontmatter
    parts = re.split(r"^---\s*$", text, flags=re.M)
    return parts[-1].strip() if len(parts) > 1 else ""


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
