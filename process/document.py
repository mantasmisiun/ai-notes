#!/usr/bin/env python3
"""A document dropped into Files at the vault root, the one folder that is
watched, goes through the same funnel as a recording: a note of yours to
write in while you read, a "transcript" that is the document's text cleaned
of everything that is not content, then a summary written from both, filed
in a module's Documents folder once your note's table says which module.
A file kept anywhere else is yours alone and is not processed.

Everything is keyed by the file's name, not a time: my notes/<name>.md,
auto/transcripts/<name>.md, <module>/Documents/<name>.md. Rename the file
and it is a new document.

The transcript marks every paragraph, **[p3.2]** for page 3, paragraph 2,
with a block id ^p3-2, so the finished note links to the exact paragraph a
point came from, as it links to a moment of audio.

Runs on the laptop through a one-minute timer, so the note appears while
you read, and inside the pipeline on the processing machine, which waits two
minutes so the laptop gets first go. By hand:

    python3 process/document.py <vault> [file ...]

A file given from outside the vault is copied into Files first."""
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "shared"))
import layout
import materials
import rawnote

DOC_EXT = (".pdf", ".docx", ".pptx", ".xlsx")
FILES = "Files"
PAGE_WORDS = 450          # a pseudo-page for formats that have no pages


def key_for(path):
    """The note name for a file: its stem, minus what a file name cannot hold."""
    k = re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", Path(path).stem)
    return re.sub(r"\s+", " ", k).strip(" .")[:100]


def files_dirs(VAULT):
    """The one watched folder: Files at the vault root."""
    d = layout.files_dir(VAULT)
    return [d] if d.is_dir() else []


def pages_of(path):
    """[(page label, text)] per page. PDF pages are real; slides are pages;
    a DOCX or XLSX is cut into pseudo-pages of about PAGE_WORDS words."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        raw = None
        if shutil.which("pdftotext"):
            r = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"],
                               capture_output=True, text=True, timeout=300)
            raw = r.stdout if r.returncode == 0 else None
        if raw is None:
            try:
                from pypdf import PdfReader
                raw = "\f".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
            except Exception:
                raw = ""
        return [(i, t) for i, t in enumerate(raw.split("\f"), 1) if t.strip()]
    text = materials.extract(path)
    if ext == ".pptx":
        out = []
        for para in re.split(r"\n\s*\n", text):
            m = re.match(r"Slide (\d+): ?(.*)", para, re.S)
            if m:
                out.append((int(m.group(1)), m.group(2)))
        return out
    out, cur, n, i = [], [], 0, 1
    for para in re.split(r"\n\s*\n", text):
        if not para.strip():
            continue
        cur.append(para.strip())
        n += len(para.split())
        if n >= PAGE_WORDS:
            out.append((i, "\n\n".join(cur)))
            cur, n, i = [], 0, i + 1
    if cur:
        out.append((i, "\n\n".join(cur)))
    return out


def clean(pages):
    """Content only, as [(page number, [paragraphs])]. Running headers and
    footers are lines that recur on three or more pages; page numbers are
    lines that are only a number; hyphenated line breaks are joined; the
    lines of a paragraph are joined."""
    norm = lambda l: re.sub(r"\d+", "#", l.strip().lower())
    seen = {}
    for _, t in pages:
        for l in set(norm(l) for l in t.splitlines() if l.strip()):
            seen[l] = seen.get(l, 0) + 1
    running = {l for l, c in seen.items() if c >= 3 and len(l.split()) <= 12}
    out = []
    for num, t in pages:
        keep = []
        for l in t.splitlines():
            s = l.strip()
            if not s:
                keep.append("")
                continue
            if re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:/|of)\s*\d+)?|[ivxlc]+", s, re.I):
                continue
            if len(pages) >= 3 and norm(s) in running:
                continue
            keep.append(s)
        text = "\n".join(keep)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # hyphenated line break
        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
        paras = [p for p in paras if len(p) > 1]
        if paras:
            out.append((num, paras))
    return out


def ingest(path, VAULT, NOTES, UNI, tr_name, log=print):
    """Create the note and the transcript for one document. Returns the key,
    or None when the document had no text."""
    path = Path(path)
    key = key_for(path)
    transcript = layout.auto_dir(NOTES, "transcripts") / f"{key}.md"
    mynote = layout.find_my_note(VAULT, NOTES, key) or (layout.raw_dir(NOTES) / f"{key}.md")

    pages = clean(pages_of(path))
    if not pages:
        log(f"document: no text in {path.name} (a scanned PDF needs OCR)")
        return None

    if not transcript.exists():
        tmp = Path(str(transcript) + ".tmp")
        rel = os.path.relpath(path, VAULT).replace(os.sep, "/")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write("type: document-transcript\n")
            f.write(f'source: "{path.name}"\n')
            f.write(f'source_path: "{rel}"\n')
            f.write(f"source_bytes: {path.stat().st_size}\n")
            f.write(f"pages: {len(pages)}\n")
            f.write(f"generated: {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
            f.write("---\n")
            for num, paras in pages:
                for i, para in enumerate(paras, 1):
                    f.write(f"\n\n**[p{num}.{i}]** {para} ^p{num}-{i}")
            f.write("\n")
        os.replace(tmp, transcript)

    if not mynote.exists():
        mynote.write_text(rawnote.render(
            key, start=f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
            kind="Document",
            transcript_link=layout.link(tr_name, "transcripts", key),
            source_link=rawnote.vault_link(path, VAULT), source=path.name), encoding="utf-8")
    log(f"document: {path.name} -> {key} ({len(pages)} pages)")
    return key


def pending(NOTES, VAULT, min_age=0):
    """Documents in Files with no transcript yet, older than min_age seconds."""
    now = time.time()
    out = []
    for d in files_dirs(VAULT):
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.suffix.lower() not in DOC_EXT or p.name.startswith((".", "_", "~$")):
                continue
            if now - p.stat().st_mtime < min_age:
                continue
            if (layout.auto_dir(NOTES, "transcripts") / f"{key_for(p)}.md").exists():
                continue
            out.append(p)
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: document.py <vault> [file ...]")
    sys.path.insert(0, str(HERE.parent / "capture"))
    from config_read import read_config
    cfg = read_config(HERE.parent / "config.sh")
    VAULT = Path(sys.argv[1]).expanduser()
    tr_name = cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
    NOTES = VAULT / tr_name
    UNI = VAULT / cfg.get("UNIVERSITY_DIR", "University")
    layout.ensure(NOTES)
    inbox = layout.files_dir(VAULT)
    layout.ensure_files(VAULT)
    files = []
    for a in sys.argv[2:]:
        f = Path(a).expanduser().resolve()
        if f.parent != inbox:
            shutil.copy2(f, inbox / f.name)       # brought into the one watched folder
            f = inbox / f.name
        files.append(f)
    for f in files or pending(NOTES, VAULT):
        ingest(f, VAULT, NOTES, UNI, tr_name)


if __name__ == "__main__":
    main()
