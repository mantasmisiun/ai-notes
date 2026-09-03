#!/usr/bin/env python3
"""Turn an accurate transcript into a study note, filed into its module.

Two passes over the transcript because a lecture is far longer than the model's
context window, then a short third call for a topic to name the file with.
Prints the path it wrote, which run.sh records as the completion marker.
"""
import json, os, re, sys, threading, time, urllib.request, datetime
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
# The combine pass now receives detailed notes rather than summaries, which
# are several times longer. Too small a window silently truncates the input
# and the note loses whole sections without saying so.
NUMCTX = int(os.environ.get("LECTURE_NUMCTX", "16384"))
REQUEST_DEADLINE = int(os.environ.get("LECTURE_REQUEST_DEADLINE", "900"))
# Detailed notes on a 2500 word chunk need perhaps 1500 tokens. This cap is
# generous for that and still stops a model that has started looping.
MAX_PREDICT      = int(os.environ.get("LECTURE_MAX_PREDICT", "4096"))
# Generous, because a reasoning model spends part of its budget thinking
# before it writes the title at all.
TOPIC_PREDICT    = int(os.environ.get("LECTURE_TOPIC_PREDICT", "300"))
WORDS  = int(os.environ.get("LECTURE_CHUNK_WORDS", "2500"))
SRCLANG   = os.environ.get("LECTURE_LANGUAGE", "en")
NOTELANG  = os.environ.get("LECTURE_NOTE_LANGUAGE", SRCLANG)


def ask(prompt, predict=None):
    """One request to the model, with a deadline that actually stops it.

    Two things matter here. Generation is streamed, because with stream=false
    abandoning the connection leaves Ollama generating on the GPU indefinitely:
    a timed-out chunk kept the card pinned and the next attempt queued behind
    it. Closing a streamed response makes the server stop.

    And every call is capped. Without num_predict a model that starts repeating
    itself will generate until the context is exhausted, which is what turned a
    twelve second chunk into a ten minute one.
    """
    opts = {"num_ctx": NUMCTX, "temperature": 0.2,
            "num_predict": predict or MAX_PREDICT,
            # A weak model on a rough transcript falls into repeating a
            # sentence with the number changed. This discourages it; the
            # num_predict cap stops it either way.
            "repeat_penalty": 1.15}
    body = json.dumps({"model": MODEL, "prompt": prompt,
                       "stream": True, "options": opts}).encode()
    req = urllib.request.Request(f"http://{HOST}/api/generate", body,
                                 {"Content-Type": "application/json"})

    deadline = time.time() + REQUEST_DEADLINE
    out = []
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for line in r:
                if time.time() > deadline:
                    r.close()               # the server stops when we go away
                    raise TimeoutError("deadline exceeded")
                if not line.strip():
                    continue
                chunk = json.loads(line)
                out.append(chunk.get("response", ""))
                if chunk.get("done"):
                    break
    except TimeoutError:
        raise SystemExit(
            f"gave up after {REQUEST_DEADLINE // 60} minutes on one chunk with {MODEL}.\n"
            f"The request was cancelled, so the GPU is released.\n"
            f"If this repeats, the model may not fit. Check with:\n"
            f"  OLLAMA_HOST={HOST} ollama ps\n"
            f"and pick a smaller one by re-running the installer with\n"
            f"'Change models only', or lower LECTURE_NUMCTX in config.sh.")
    text = "".join(out)
    # Hybrid reasoning models emit a <think> block before the answer. Strip it,
    # and handle the case where the budget ran out mid-thought and there is no
    # answer after it at all.
    if "</think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        text = re.sub(r"^.*?</think>", "", text, flags=re.S)
    elif "<think>" in text:
        # Budget ran out mid-thought: there is no answer, only reasoning. Better
        # nothing than a title made of the model talking to itself.
        text = ""
    return text.strip()


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


def chunks(text, size, overlap=200):
    """Split into passes with a little overlap. Without it, a definition that
    straddles a boundary is seen twice, each time with half its context."""
    w = text.split()
    out, i = [], 0
    while i < len(w):
        out.append(" ".join(w[i:i + size]))
        i += max(1, size - overlap)
    return out


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


# Where does it belong? Decided here, at summarise time, so a timetable you
# corrected after recording still routes the note correctly.
SESSIONS = "Sessions"


def resolve_schedule(link):
    """Where does a [[wikilink]] in the Schedule cell actually point?

    Obsidian resolves a bare name against the whole vault, so this does the
    same: try it as a path first, then search by filename. Returns the folder
    holding that note, which is the subject folder.
    """
    if not link:
        return None
    mm = re.match(r"\[\[([^\]|#]+)", link.strip())
    if not mm:
        return None
    target = mm.group(1).strip()

    direct = os.path.join(VAULT, target + ".md")
    if os.path.exists(direct):
        return os.path.dirname(direct)

    base = os.path.basename(target) + ".md"
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if base in files:
            return root
    return None

try:
    when = timetable.parse_stamp(stamp)
except ValueError:
    # A file dropped into the audio folder by hand does not have a timestamp
    # for a name. Fall back to when it was last written, so it still dates and
    # files correctly instead of crashing after transcription has already run.
    when = datetime.datetime.fromtimestamp(os.path.getmtime(transcript))
    print(f"  '{stamp}' is not a timestamp; dating it from the file: {when:%Y-%m-%d %H:%M}",
          flush=True)
m    = timetable.match(timetable.load(UNI), when)
lectures_dir = os.path.join(UNI, m["module_folder"], "Sessions") if m else None
own = collect_notes(stamp, lectures_dir)
if own:
    print(f"  found {len(own.split())} words of your own notes", flush=True)

# What this recording is has to be known before the prompts are built, so a
# review or an interview is not summarised as though it were a lecture.
raw_path = os.path.join(NOTES, "raw notes", f"{stamp}.md")
table = rawnote.parse(raw_path) if os.path.exists(raw_path) else {}
area, subject = table.get("Area", "").strip(), table.get("Subject", "").strip()
kind = table.get("Type", "").strip() or (m["kind"] if m else "")

subject_dir = resolve_schedule(table.get("Schedule", ""))
if subject_dir:
    rel = os.path.relpath(subject_dir, VAULT).split(os.sep)
    area    = area or (rel[0] if len(rel) > 1 else "")
    subject = subject or rel[-1]

context = prompts.describe(area, subject, kind, NOTELANG)
print(f"  treating this as {context}", flush=True)
P = prompts.get(NOTELANG, SRCLANG, context)

text  = body_of(transcript)
parts = chunks(text, WORDS)
print(f"{len(text.split())} words in {len(parts)} chunk(s)", flush=True)

summaries = []
t_start = time.time()
for i, c in enumerate(parts, 1):
    t0 = time.time()
    summaries.append(ask(P["section"].format(chunk=c)))
    el = time.time() - t0
    done = time.time() - t_start
    eta = done / i * (len(parts) - i)
    print(f"  section {i}/{len(parts)}  {el:.0f}s"
          + (f", about {eta/60:.0f} min left" if i < len(parts) else ""), flush=True)

print("  combining", flush=True)
combine = P["combine"]
if own:
    combine = P["notes_intro"].format(notes=own) + combine
note = unfence(ask(combine.format(sections="\n\n---\n\n".join(summaries))))

print("  titling", flush=True)
raw_topic = unfence(ask(P["topic"].format(note=note[:4000]), predict=TOPIC_PREDICT))
lines = [l for l in raw_topic.splitlines() if l.strip()]
# A note without a title is filed under its timestamp. Losing a completed
# summary because the model returned nothing would be absurd.
topic = safe(lines[0]) if lines else ""
if not topic:
    print("  no title returned; filing under the timestamp", flush=True)

if subject_dir:
    dest_dir = os.path.join(subject_dir, SESSIONS)
elif area and subject:
    dest_dir = os.path.join(VAULT, area, subject, SESSIONS)
else:
    dest_dir = os.path.join(NOTES, "unfiled")

if kind and topic:
    fname = f"{stamp} {kind} - {topic}.md"
elif topic:
    fname = f"{stamp} - {topic}.md"
else:
    fname = f"{stamp}.md"

os.makedirs(dest_dir, exist_ok=True)
out = os.path.join(dest_dir, fname)
tmp = out + ".tmp"

rel_transcript = os.path.relpath(transcript, VAULT)[:-3].replace(os.sep, "/")        # drop .md
audio = None
for ext in (".ogg", ".mp3", ".m4a", ".wav"):
    p = os.path.join(NOTES, "audio", stamp + ext)
    if os.path.exists(p):
        audio = os.path.relpath(p, VAULT).replace(os.sep, "/")
        break

raw_link = f"{os.path.basename(NOTES)}/raw notes/{stamp}"   # already forward slashes

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
                os.path.relpath(out, VAULT)[:-3].replace(os.sep, "/"))
    except Exception as e:
        print(f"  could not update the timetable: {e}")

# link the raw note back to the session it produced
try:
    if os.path.exists(raw_path):
        rel_out = os.path.relpath(out, VAULT)[:-3].replace(os.sep, "/")
        text = open(raw_path, encoding="utf-8").read()
        if rel_out not in text:
            marker = "\n---\n"
            i = text.index(marker)
            text = text[:i] + f"\nSummary: [[{rel_out}]]\n" + text[i:]
            open(raw_path, "w", encoding="utf-8").write(text)
except Exception:
    pass          # a missing backlink must not fail a completed summary

print(f"NOTE_PATH={out}")
