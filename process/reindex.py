#!/usr/bin/env python3
"""Rebuild every module's Lectures/_index.md from the notes present.

Owned entirely by the pipeline and regenerated from scratch each run, so it is
idempotent and never accumulates duplicates. Your timetable notes are only read,
never written; embed the index with  ![[Lectures/_index]]  once per module.
"""
import os, re, sys, glob

VAULT = os.path.expanduser(sys.argv[1])
UNI   = os.path.join(VAULT, "University")
NOTES = os.path.join(VAULT, "Transcriptions")

FM = re.compile(r"^---\n(.*?)\n---", re.S)


def front(path):
    m = FM.search(open(path, encoding="utf-8").read(4000))
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def first_existing(folder, stamp, exts):
    for e in exts:
        p = os.path.join(folder, stamp + e)
        if os.path.exists(p):
            return p
    return None


def link(path):
    return "[[" + os.path.relpath(path, VAULT)[:-3] + "]]" if path else ""


written = 0
for lect_dir in sorted(glob.glob(os.path.join(UNI, "*", "Lectures"))):
    rows = []
    for note in sorted(glob.glob(os.path.join(lect_dir, "*.md"))):
        if os.path.basename(note) == "_index.md":
            continue
        fm = front(note)
        stamp = fm.get("stamp")
        if not stamp:
            continue

        live = None
        for cand in glob.glob(os.path.join(NOTES, "live", stamp + "*.md")):
            live = cand
            break
        tr = first_existing(os.path.join(NOTES, "transcripts"), stamp, [".md"])
        au = first_existing(os.path.join(NOTES, "audio"), stamp,
                            [".ogg", ".mp3", ".m4a", ".wav"])

        rows.append((
            fm.get("date", stamp[:10]),
            fm.get("time", stamp[-4:-2] + ":" + stamp[-2:]),
            fm.get("session", ""),
            link(live),
            link(tr),
            "[[" + os.path.relpath(note, VAULT)[:-3] + "]]",
            "yes" if au else "",
        ))

    out = os.path.join(lect_dir, "_index.md")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("---\ntype: lecture-index\n"
                "note: generated file, edits will be overwritten\n---\n\n")
        if rows:
            f.write("| Date | Time | Type | Live | Transcript | Summary | Audio |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
            for r in sorted(rows):
                f.write("| " + " | ".join(r) + " |\n")
        else:
            f.write("*No lectures processed yet.*\n")
    os.replace(tmp, out)
    written += 1

print(f"reindex: {written} module index file(s)")
