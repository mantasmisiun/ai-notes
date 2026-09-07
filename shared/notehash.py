#!/usr/bin/env python3
"""Hashes that decide whether a finished note is regenerated.

notes_hash is the hash of the user's note when the summary was written; a
different hash later means they added something and the summary should be
written again. content_hash is the hash of the summary's own generated body;
a different hash later means the user edited the summary by hand, and it
must never be overwritten. Both live in the finished note's frontmatter, so
the check needs no state outside the vault."""
import hashlib
import re

FOOTER_RE = re.compile(r"\n---\n\n(?:My notes|Your notes|Raw note):", re.M)


def norm_hash(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text or "").strip().encode("utf-8")).hexdigest()[:16]


def generated_body(note_text):
    """The part of a finished note the pipeline wrote: after the frontmatter,
    before the footer with the links."""
    t = re.sub(r"^---\n.*?\n---\n", "", note_text, count=1, flags=re.S)
    m = FOOTER_RE.search(t)
    return t[:m.start()] if m else t


def frontmatter_field(note_text, name):
    m = re.search(rf"^{re.escape(name)}:\s*(.+?)\s*$", note_text[:2000], re.M)
    return m.group(1).strip().strip('"') if m else ""
