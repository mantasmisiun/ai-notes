#!/usr/bin/env python3
"""Turn an accurate transcript into a study note, filed into its module.

Two passes over the transcript because a lecture is far longer than the model's
context window, then a short third call for a topic to name the file with.
Prints the path it wrote, which run.sh records as the completion marker.
"""
import json, os, re, sys, urllib.request, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "shared"))
import timetable
import prompts
import rawnote

transcript = sys.argv[1]
stamp      = sys.argv[2]                       # "YYYY-MM-DD HHMM"
VAULT      = os.path.expanduser(sys.argv[3])

UNI    = os.path.join(VAULT, os.environ.get("UNIVERSITY_DIR", "University"))
NOTES  = os.path.join(VAULT, os.environ.get("TRANSCRIPTIONS_DIR", "Transcriptions"))

HOST   = os.environ.get("LECTURE_OLLAMA_HOST", "127.0.0.1:11434").replace("http://", "")
MODEL  = os.environ.get("LECTURE_LLM", "llama3.1:8b")
NUMCTX = int(os.environ.get("LECTURE_NUMCTX", "8192"))
WORDS  = int(os.environ.get("LECTURE_CHUNK_WORDS", "2500"))
SRCLANG   = os.environ.get("LECTURE_LANGUAGE", "en")
NOTELANG  = os.environ.get("LECTURE_NOTE_LANGUAGE", SRCLANG)


def ask(prompt, predict=None):
    opts = {"num_ctx": NUMCTX, "temperature": 0.2}
    if predict:
        opts["num_predict"] = predict
    body = json.dumps({"model": MODEL, "prompt": prompt,
                       "stream": False, "options": opts}).encode()
    req = urllib.request.Request(f"http://{HOST}/api/generate", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["response"].strip()


def unfence(t):
    t = t.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


def body_of(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"^---.*?---\n", "", t, flags=re.S)
    t = re.sub(r"\*\*\[[0-9:]+\]\*\*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def chunks(text, size):
    w = text.split()
    return [" ".join(w[i:i + size]) for i in range(0, len(w), size)]


def own_notes_body(path):
    """Everything the student wrote, which the template places after a lone
    --- separator. Returns "" for an untouched template."""
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"^---.*?---\n", "", t, flags=re.S)          # frontmatter
    parts = re.split(r"^---\s*$", t, flags=re.M)
    return parts[-1].strip() if len(parts) > 1 else t.strip()


def collect_notes(stamp, lectures_dir):
    """The student's own notes, from the file created alongside the recording
    and from anything already filed for this lecture in the module folder."""
    found = []
    raw = os.path.join(NOTES, "raw notes", f"{stamp}.md")
    if os.path.exists(raw):
        body = rawnote.body(raw)
        if body:
            found.append(body)

    if lectures_dir and os.path.isdir(lectures_dir):
        for f in sorted(os.listdir(lectures_dir)):
            if not f.endswith(".md") or f == "_index.md":
                continue
            path = os.path.join(lectures_dir, f)
            head = open(path, encoding="utf-8").read(2000)
            if f'stamp: "{stamp}"' not in head:
                continue
            # never feed the pipeline its own output back to itself
            if re.search(r"^type: lecture-(note|index)\s*$", head, re.M):
                continue
            found.append(own_notes_body(path))

    return "\n\n".join(x for x in found if x).strip()


def safe(name):
    name = re.sub(r"[\\/:*?\"<>|#^\[\]]", "", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:70]


P = prompts.get(NOTELANG, SRCLANG)

when = timetable.parse_stamp(stamp)
m    = timetable.match(timetable.load(UNI), when)
lectures_dir = os.path.join(UNI, m["module_folder"], "Lectures") if m else None
own = collect_notes(stamp, lectures_dir)
if own:
    print(f"  found {len(own.split())} words of your own notes", flush=True)

text  = body_of(transcript)
parts = chunks(text, WORDS)
print(f"{len(text.split())} words in {len(parts)} chunk(s)", flush=True)

summaries = []
for i, c in enumerate(parts, 1):
    print(f"  section {i}/{len(parts)}", flush=True)
    summaries.append(ask(P["section"].format(chunk=c)))

print("  combining", flush=True)
combine = P["combine"]
if own:
    combine = P["notes_intro"].format(notes=own) + combine
note = unfence(ask(combine.format(sections="\n\n---\n\n".join(summaries))))

print("  titling", flush=True)
topic = safe(unfence(ask(P["topic"].format(note=note[:4000]), predict=30)).splitlines()[0])

# Where does it belong? Decided here, at summarise time, so a timetable you
# corrected after recording still routes the note correctly.
LECTURES = "Lectures"
raw_path = os.path.join(NOTES, "raw notes", f"{stamp}.md")
table = rawnote.parse(raw_path) if os.path.exists(raw_path) else {}
area, subject = table.get("Area", "").strip(), table.get("Subject", "").strip()
kind = table.get("Type", "").strip() or (m["kind"] if m else "")

if area and subject:
    dest_dir = os.path.join(VAULT, area, subject, LECTURES)
    fname    = f"{stamp} {kind} - {topic}.md" if kind and topic else \
               (f"{stamp} - {topic}.md" if topic else f"{stamp}.md")
else:
    dest_dir = os.path.join(NOTES, "unfiled")
    fname    = f"{stamp} - {topic}.md" if topic else f"{stamp}.md"

os.makedirs(dest_dir, exist_ok=True)
out = os.path.join(dest_dir, fname)
tmp = out + ".tmp"

rel_transcript = os.path.relpath(transcript, VAULT)[:-3]        # drop .md
audio = None
for ext in (".ogg", ".mp3", ".m4a", ".wav"):
    p = os.path.join(NOTES, "audio", stamp + ext)
    if os.path.exists(p):
        audio = os.path.relpath(p, VAULT)
        break

raw_link = f"{os.path.basename(NOTES)}/raw notes/{stamp}"

with open(tmp, "w", encoding="utf-8") as f:
    f.write("---\n")
    f.write(f'stamp: "{stamp}"\n')
    f.write(f"date: {when:%Y-%m-%d}\ntime: {when:%H:%M}\n")
    f.write("type: lecture-note\n")
    if area:
        f.write(f'area: "{area}"\n')
    if subject:
        f.write(f'subject: "{subject}"\n')
    if kind:
        f.write(f"session: {kind}\n")
    if m:
        f.write(f"module: {m['code']}\n")
    f.write(f"model: {MODEL}\nnote_language: {NOTELANG}\n---\n\n")
    f.write(note.rstrip() + "\n\n---\n\n")
    if own:
        f.write(f"## {P['notes_heading']}\n\n{own}\n\n---\n\n")
    f.write(f"Raw note: [[{raw_link}]]\n")
    f.write(f"Transcript: [[{rel_transcript}]]\n")
    if audio:
        f.write(f"\n![[{audio}]]\n")

os.replace(tmp, out)

# record the session in a timetable the pipeline owns. A hand-maintained
# schedule is left alone: ensure_generated returns None for one it did not write.
if area and subject:
    try:
        tt = timetable.ensure_generated(os.path.join(VAULT, area, subject), subject)
        if tt:
            start_s = table.get("Start", "").split()
            end_s   = table.get("End", "").split()
            timetable.append_row(
                tt,
                f"{when:%d-%m-%Y}",
                start_s[1] if len(start_s) > 1 else f"{when:%H:%M}",
                end_s[1] if len(end_s) > 1 else "",
                kind,
                os.path.relpath(out, VAULT)[:-3])
    except Exception as e:
        print(f"  could not update the timetable: {e}")

# link the raw note back to the session it produced
try:
    if os.path.exists(raw_path):
        rel_out = os.path.relpath(out, VAULT)[:-3]
        text = open(raw_path, encoding="utf-8").read()
        if rel_out not in text:
            marker = "\n---\n"
            i = text.index(marker)
            text = text[:i] + f"\nSummary: [[{rel_out}]]\n" + text[i:]
            open(raw_path, "w", encoding="utf-8").write(text)
except Exception:
    pass          # a missing backlink must not fail a completed summary

print(f"NOTE_PATH={out}")
