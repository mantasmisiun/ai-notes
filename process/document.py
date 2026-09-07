#!/usr/bin/env python3
"""A document dropped into Transcriptions/auto/documents goes through the same
funnel as a recording: a note of yours to write in while you read, a
"transcript" that is the document's text cleaned of everything that is not
content, then a summary written from both.

The transcript carries page markers, **[p3]**, and block ids, ^p3, where a
recording's carries time markers, so the finished note links to the page a
point came from exactly as it links to a moment of audio.

Runs inside the pipeline on the processing machine, and by hand anywhere:

    python3 process/document.py <vault> [file ...]

With no files it ingests everything in auto/documents that has no note yet."""
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "shared"))
import layout
import materials
import rawnote

DOC_EXT = (".pdf", ".docx", ".pptx", ".xlsx", ".md")
PAGE_WORDS = 450          # a pseudo-page for formats that have no pages


def pages_of(path):
    """[(label, text)] per page. PDF pages are real; slides are pages; a
    DOCX or XLSX is cut into pseudo-pages of about PAGE_WORDS words."""
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
        pages = [p for p in raw.split("\f")]
        return [(f"p{i}", t) for i, t in enumerate(pages, 1) if t.strip()]
    text = materials.extract(path)
    if ext == ".pptx":
        out = []
        for para in re.split(r"\n\s*\n", text):
            m = re.match(r"Slide (\d+): ?(.*)", para, re.S)
            if m:
                out.append((f"p{m.group(1)}", m.group(2)))
        return out
    out, cur, n, i = [], [], 0, 1
    for para in re.split(r"\n\s*\n", text):
        if not para.strip():
            continue
        cur.append(para.strip())
        n += len(para.split())
        if n >= PAGE_WORDS:
            out.append((f"p{i}", "\n\n".join(cur)))
            cur, n, i = [], 0, i + 1
    if cur:
        out.append((f"p{i}", "\n\n".join(cur)))
    return out


def clean(pages):
    """Content only. Running headers and footers are lines that recur on
    three or more pages; page numbers are lines that are only a number;
    hyphenated line breaks are joined; lines within a paragraph are joined."""
    norm = lambda l: re.sub(r"\d+", "#", l.strip().lower())
    seen = {}
    for _, t in pages:
        for l in set(norm(l) for l in t.splitlines() if l.strip()):
            seen[l] = seen.get(l, 0) + 1
    running = {l for l, c in seen.items() if c >= 3 and len(l.split()) <= 12}
    out = []
    for label, t in pages:
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
            out.append((label, "\n\n".join(paras)))
    return out


def stamp_for(path, NOTES):
    """A stamp from the file's modification time, nudged by a minute while it
    collides with a recording or another document."""
    t = datetime.datetime.fromtimestamp(Path(path).stat().st_mtime)
    while True:
        stamp = f"{t:%Y-%m-%d %H%M}"
        taken = ((layout.auto_dir(NOTES, "transcripts") / f"{stamp}.md").exists()
                 or (layout.raw_dir(NOTES) / f"{stamp}.md").exists())
        if not taken:
            return stamp
        t += datetime.timedelta(minutes=1)


def existing_stamp(NOTES, name):
    """The stamp already given to this document, from its note's frontmatter."""
    for p in layout.raw_dir(NOTES).glob("*.md"):
        try:
            head = p.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        if re.search(rf'^source: "{re.escape(name)}"\s*$', head, re.M):
            return p.stem
    return None


def ingest(path, VAULT, NOTES, tr_name, log=print):
    """Create the note and the transcript for one document. Returns the stamp,
    or None when the document had no text."""
    path = Path(path)
    stamp = existing_stamp(NOTES, path.name) or stamp_for(path, NOTES)
    transcript = layout.auto_dir(NOTES, "transcripts") / f"{stamp}.md"
    mynote = layout.raw_dir(NOTES) / f"{stamp}.md"

    pages = clean(pages_of(path))
    if not pages:
        log(f"document: no text in {path.name} (a scanned PDF needs OCR)")
        return None

    if not transcript.exists():
        tmp = Path(str(transcript) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write("type: document-transcript\n")
            f.write(f'source: "{path.name}"\n')
            f.write(f"source_bytes: {path.stat().st_size}\n")
            f.write(f"pages: {len(pages)}\n")
            f.write(f"generated: {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
            f.write("---\n")
            for label, text in pages:
                f.write(f"\n\n**[{label}]** {text} ^{label}")
            f.write("\n")
        os.replace(tmp, transcript)

    if not mynote.exists():
        rel_src = layout.link(tr_name, "documents", path.name)
        mynote.write_text(rawnote.render(
            stamp, start=f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
            kind="Document",
            transcript_link=layout.link(tr_name, "transcripts", stamp),
            source_link=rel_src, source=path.name), encoding="utf-8")
    log(f"document: {path.name} -> {stamp} ({len(pages)} pages)")
    return stamp


def pending(NOTES):
    d = layout.auto_dir(NOTES, "documents")
    if not d.is_dir():
        return []
    return [p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in DOC_EXT and not p.name.startswith(("_", "."))
            and existing_stamp(NOTES, p.name) is None]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: document.py <vault> [file ...]")
    sys.path.insert(0, str(HERE.parent / "capture"))
    from config_read import read_config
    cfg = read_config(HERE.parent / "config.sh")
    VAULT = Path(sys.argv[1]).expanduser()
    tr_name = cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
    NOTES = VAULT / tr_name
    layout.ensure(NOTES)
    files = [Path(a) for a in sys.argv[2:]] or pending(NOTES)
    for f in files:
        f = f.expanduser().resolve()
        dest = layout.auto_dir(NOTES, "documents") / f.name
        if f.parent != dest.parent:
            shutil.copy2(f, dest)         # a file from elsewhere is brought in
            f = dest
        ingest(f, VAULT, NOTES, tr_name)


if __name__ == "__main__":
    main()
