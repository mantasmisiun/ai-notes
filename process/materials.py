#!/usr/bin/env python3
"""Course material linked from the student's note: slides, a handout, a
syllabus, a spreadsheet. Extracted to text and handed to the summariser as
the authority on names, terms and formulas, above the transcript.

A link is anything Obsidian would treat as one, [[Week 3 slides.pdf]],
![[handout.docx]] or [text](file.pptx), resolved the way Obsidian resolves it:
as a vault path first, then by file name anywhere in the vault, so a file in
the module's Files folder is found by name alone.

Extraction needs no model. PDF goes through pdftotext when present, else the
pypdf library; DOCX and PPTX are XML inside a zip and are read directly,
speaker notes included; XLSX through openpyxl; a linked markdown note is read
as it is. A scanned PDF with no text layer yields nothing and is reported.

The summariser's context is finite, so each chunk gets the passages that
share the most words with it, within a budget, rather than everything."""
import math
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

EXTS = (".pdf", ".docx", ".pptx", ".xlsx", ".md")
LINK_RE = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]|\[[^\]]*\]\(([^)\s]+)\)")
WORD_RE = re.compile(r"\w+")


def links(text):
    """Link targets in order of first appearance, one each."""
    out = []
    for m in LINK_RE.finditer(text or ""):
        t = unquote((m.group(1) or m.group(2) or "").strip())
        if t.startswith(("http://", "https://")) or not t:
            continue
        if not Path(t).suffix:
            t += ".md"
        if Path(t).suffix.lower() in EXTS and t not in out:
            out.append(t)
    return out


def resolve(target, vault, near=None):
    vault = Path(vault)
    for base in ([Path(near)] if near else []) + [vault]:
        p = base / target
        if p.is_file():
            return p
    name = Path(target).name.lower()
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.lower() == name:
                return Path(root) / f
    return None


def _xml_texts(data, tag):
    """All text under elements named `tag` (local name), in document order."""
    out = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return out
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == tag and el.text:
            out.append(el.text)
    return out


def _paragraphs_docx(data):
    paras = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return paras
    for p in root.iter():
        if p.tag.rsplit("}", 1)[-1] != "p":
            continue
        t = "".join(el.text for el in p.iter()
                    if el.tag.rsplit("}", 1)[-1] == "t" and el.text)
        if t.strip():
            paras.append(t.strip())
    return paras


def extract(path):
    """Text of one document, paragraphs separated by blank lines. Empty when
    there is none to be had; raises nothing."""
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext == ".md":
            t = path.read_text(encoding="utf-8", errors="replace")
            return re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S).strip()
        if ext == ".pdf":
            if shutil.which("pdftotext"):
                r = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"],
                                   capture_output=True, text=True, timeout=120)
                return r.stdout.strip() if r.returncode == 0 else ""
            from pypdf import PdfReader
            return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages).strip()
        if ext == ".docx":
            with zipfile.ZipFile(path) as z:
                return "\n\n".join(_paragraphs_docx(z.read("word/document.xml")))
        if ext == ".pptx":
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                                key=lambda n: int(re.search(r"(\d+)", n).group(1)))
                out = []
                for n in slides:
                    num = re.search(r"(\d+)", n).group(1)
                    body = " ".join(_xml_texts(z.read(n), "t")).strip()
                    notes_name = f"ppt/notesSlides/notesSlide{num}.xml"
                    notes = " ".join(_xml_texts(z.read(notes_name), "t")).strip() if notes_name in names else ""
                    if body or notes:
                        out.append(f"Slide {num}: {body}" + (f"\nNotes: {notes}" if notes else ""))
                return "\n\n".join(out)
        if ext == ".xlsx":
            try:
                import openpyxl
            except ImportError:
                return ""
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 400:
                        break
                    cells = [str(c) for c in row if c is not None and str(c).strip()]
                    if cells:
                        rows.append("\t".join(cells))
                if rows:
                    out.append(f"Sheet {ws.title}:\n" + "\n".join(rows))
            return "\n\n".join(out)
    except Exception:
        return ""
    return ""


def passages(text, target=120):
    """Paragraph-sized pieces of about `target` words: short lines, as slides
    and bullet lists produce, are merged; long paragraphs are kept whole."""
    out, cur, n = [], [], 0
    for para in re.split(r"\n\s*\n", text.strip()):
        para = re.sub(r"[ \t]+", " ", para).strip()
        if not para:
            continue
        w = len(para.split())
        cur.append(para)
        n += w
        if n >= target:
            out.append("\n".join(cur))
            cur, n = [], 0
    if cur:
        out.append("\n".join(cur))
    return out


def collect(note_text, vault, near=None, max_words_per_doc=6000):
    """(documents, messages). Each document: name, path, words, passages."""
    docs, msgs = [], []
    for target in links(note_text):
        path = resolve(target, vault, near)
        if not path:
            msgs.append(f"material not found: {target}")
            continue
        text = extract(path)
        if not text.strip():
            msgs.append(f"no text in {path.name} (a scanned PDF needs OCR)")
            continue
        words = text.split()
        if len(words) > max_words_per_doc:
            text = " ".join(words[:max_words_per_doc])
            msgs.append(f"{path.name} cut to the first {max_words_per_doc} words")
        docs.append({"name": path.name, "path": str(path), "words": len(words),
                     "passages": passages(text)})
        msgs.append(f"material: {path.name}, {len(words)} words")
    return docs, msgs


def _content_words(text):
    return {w.lower() for w in WORD_RE.findall(text or "") if len(w) > 3}


def select(docs, query, budget_words=1500):
    """The passages that share the most words with `query`, within the
    budget, in document order. With little material, all of it."""
    if not docs:
        return ""
    total = sum(len(p.split()) for d in docs for p in d["passages"])
    q = _content_words(query)
    scored = []
    for di, d in enumerate(docs):
        for pi, p in enumerate(d["passages"]):
            pw = _content_words(p)
            score = len(q & pw) / math.sqrt(len(pw) + 1) if q else 0
            scored.append((score, di, pi, p))
    if total <= budget_words:
        chosen = [(di, pi, p) for _, di, pi, p in scored]
    else:
        chosen, used = [], 0
        for score, di, pi, p in sorted(scored, key=lambda x: -x[0]):
            n = len(p.split())
            if used + n > budget_words:
                continue
            chosen.append((di, pi, p))
            used += n
    chosen.sort()
    out, last = [], None
    for di, pi, p in chosen:
        if di != last:
            out.append(f"From {docs[di]['name']}:")
            last = di
        out.append(p)
    return "\n\n".join(out)


def all_text(docs, budget_words=3000):
    out, used = [], 0
    for d in docs:
        for p in d["passages"]:
            n = len(p.split())
            if used + n > budget_words:
                return "\n\n".join(out)
            out.append(p)
            used += n
    return "\n\n".join(out)
