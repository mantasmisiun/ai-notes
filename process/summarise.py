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
import layout
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
# A model writes a few hundred words per call whatever it is given, so the
# detail in the note scales with the number of section calls, not with the
# prompt. 2500-word chunks turned a 3000-word transcript into 450 words of
# note; 1000-word chunks give three times the passes and three times the detail.
WORDS  = int(os.environ.get("LECTURE_CHUNK_WORDS", "1000"))
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


TIME_RE = re.compile(r"\*\*\[(\d{1,2}:\d\d:\d\d)\]\*\*")
# a time the model cites, allowing the bold or code it may wrap it in
CITED_RE = re.compile(r"`?\*{0,2}\[(\d{1,2}:\d\d:\d\d)\]\*{0,2}`?")


def block_id(label):
    """[0:03:08] -> t0-03-08, an Obsidian block id (letters, digits, dashes)."""
    return "t" + label.replace(":", "-")


def secs(label):
    h, m_, s_ = (int(x) for x in label.split(":"))
    return h * 3600 + m_ * 60 + s_


def ensure_block_ids(path):
    """Give every timestamped paragraph the block id transcribe.py now writes,
    so notes can link into transcripts made before that existed. Idempotent."""
    t = open(path, encoding="utf-8").read()
    fm = re.match(r"^---\n.*?\n---\n", t, re.S)
    head, body = (fm.group(0), t[fm.end():]) if fm else ("", t)
    paras, changed = [], False
    for para in re.split(r"\n\s*\n", body.strip()):
        m_ = TIME_RE.match(para.strip())
        if m_ and not re.search(r"\^t[\d-]+\s*$", para):
            para = para.rstrip() + f" ^{block_id(m_.group(1))}"
            changed = True
        paras.append(para)
    if changed:
        tmp_ = path + ".tmp"
        open(tmp_, "w", encoding="utf-8").write(head + "\n" + "\n\n".join(paras) + "\n")
        os.replace(tmp_, path)


def paragraphs(path):
    """[(time label or None, text)] per transcript paragraph, with the marker
    and the block id removed from the text."""
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S)
    out = []
    for para in re.split(r"\n\s*\n", t.strip()):
        m_ = TIME_RE.match(para.strip())
        body = re.sub(r"\s\^t[\d-]+\s*$", "", TIME_RE.sub("", para))
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            out.append((m_.group(1) if m_ else None, body))
    return out


def chunk_paragraphs(paras, size):
    """Chunks of about `size` words cut only at paragraph starts, so every
    chunk opens on a time marker the model can cite, and markers stay in the
    text as [0:03:08]. A short tail is folded into the chunk before it.
    Returns [(first label, last label, text)]."""
    groups, cur, n = [], [], 0
    for label, body in paras:
        w = len(body.split())
        if cur and n + w > size:
            groups.append(cur); cur, n = [], 0
        cur.append((label, body)); n += w
    if cur:
        if groups and n < size // 3:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    out = []
    for g in groups:
        labels = [l for l, _ in g if l]
        text = " ".join((f"[{l}] " if l else "") + b for l, b in g)
        out.append((labels[0] if labels else "", labels[-1] if labels else "", text))
    return out


def linker(labels, rel_transcript):
    """Turns a cited time into a link that opens the transcript at that
    paragraph. A time the model made up is snapped to the nearest marker
    before it, so every link lands somewhere real."""
    known = sorted(set(labels), key=secs)
    if not known:
        return lambda text: text

    def target(label):
        if label in known:
            return label
        t = secs(label)
        before = [k for k in known if secs(k) <= t]
        return before[-1] if before else known[0]

    def link(label):
        k = target(label)
        return f"[[{rel_transcript}#^{block_id(k)}|{k}]]"

    def convert(text):
        return CITED_RE.sub(lambda mm: link(mm.group(1)), text)
    convert.link = link
    return convert


def with_time_lines(notes, start):
    """The model writes topic blocks: a ### title, a line with the time marker
    where the topic starts, key points, an optional paragraph. Give a block
    that forgot its marker line the chunk's start, so every title has a link
    into the transcript, and drop any ## heading the model added on its own."""
    lines = [l for l in notes.splitlines() if not l.startswith("## ")]
    out, i = [], 0
    while i < len(lines):
        out.append(lines[i])
        if lines[i].startswith("### ") and start:
            nxt = [l for l in lines[i + 1:i + 3] if l.strip()]
            if not (nxt and CITED_RE.search(nxt[0])):
                out.append(f"[{start}]")
        i += 1
    return "\n".join(out)


# Proper nouns and bold terms, in order of first appearance. Sentence-initial
# capitals are ignored unless the word recurs capitalised mid-sentence, so
# "The" and "Members" do not become names.
NAME_RUN = re.compile(r"\b([A-ZÀ-Ž][\w'-]+(?:\s+(?:(?:de|del|la|le|von|van|of|the|da|di)\s+)?[A-ZÀ-Ž][\w'-]+)+)")
MID_CAP  = re.compile(r"(?<=[a-zà-ž,;:]\s)([A-ZÀ-Ž][\w'-]{2,})")
BOLD     = re.compile(r"\*\*([^*\n]{2,60})\*\*")


def extract_names(text, seen=None):
    seen = seen if seen is not None else []
    counts = {}
    for m in MID_CAP.finditer(text):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    cands = [b.strip() for b in BOLD.findall(text)]
    cands += [m.group(1) for m in NAME_RUN.finditer(text)]
    cands += [w for w, n in counts.items() if n >= 2]
    for c in cands:
        c = re.sub(r"\s+", " ", c).strip(" .,:;")
        if c and c not in seen and len(seen) < 60:
            seen.append(c)
    return seen


def merge_blocks(detail):
    """Blocks with the same title are the same topic, returned to later, so
    they become one block: the first keeps the title and its time link, each
    later one adds its points under its own time link, which is where the
    reader clicks to hear that part."""
    parts = re.split(r"^(?=### )", detail, flags=re.M)
    head, blocks, index = parts[0], [], {}
    for p in parts[1:]:
        lines = p.rstrip("\n").splitlines()
        title, body = lines[0], "\n".join(lines[1:]).strip("\n")
        key = " ".join(re.sub(r"[^\w\s]", "", title[4:].lower()).split())
        if key in index:
            blocks[index[key]][1] += "\n\n" + body
        else:
            index[key] = len(blocks)
            blocks.append([title, body])
    # In the order the recording went, by each block's first time link. The
    # model wrote a 0:02:08 topic after a 0:04:10 one; a block with no time
    # of its own stays after the block before it.
    def first_time(body):
        m = re.search(r"\|(\d{1,2}):(\d\d):(\d\d)\]\]", body)
        return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m else None
    keyed, last = [], -1
    for t, b in blocks:
        ft = first_time(b)
        last = ft if ft is not None else last
        keyed.append((last, t, b))
    blocks = [(t, b) for _, t, b in sorted(keyed, key=lambda x: x[0])]
    return head + "\n\n".join(f"{t}\n{b}" for t, b in blocks) + "\n"


def split_off(note, heading):
    """Remove one ## section from the model's output and return (rest, section),
    so Open questions can sit after the detail rather than before it."""
    mm = re.search(rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)", note, re.S | re.M)
    if not mm:
        return note, ""
    section = mm.group(0).strip()
    return (note[:mm.start()] + note[mm.end():]).strip(), section


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
    raw = str(layout.raw_dir(NOTES) / f"{stamp}.md")
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
    name = re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", name).strip(" .")
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
raw_path = str(layout.raw_dir(NOTES) / f"{stamp}.md")
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

H = prompts.HEADINGS.get(NOTELANG, prompts.HEADINGS["en"])
rel_transcript = os.path.relpath(transcript, VAULT)[:-3].replace(os.sep, "/")        # drop .md

ensure_block_ids(transcript)
paras = paragraphs(transcript)
parts = chunk_paragraphs(paras, WORDS)
n_words = sum(len(b.split()) for _, b in paras)
print(f"{n_words} words in {len(parts)} chunk(s)", flush=True)

# The student's notes go to every call, not only the combine: the body of the
# note is now the section notes themselves, so a name the student corrected
# has to be corrected where the detail is written.
notes_intro = P["notes_intro"].format(notes=own) if own else ""
role_line = prompts.roles(kind, NOTELANG)

# Names travel forward. Each chunk sees only its own text and the transcript
# changed a name's spelling halfway through a recording, so blocks up to one
# point said Nasson and after it Nasona. The student's notes rank first: a name
# typed by someone who was there beats the speech recogniser.
names = extract_names(own) if own else []

summaries = []
t_start = time.time()
prev_text = ""
for i, (start, end, c) in enumerate(parts, 1):
    t0 = time.time()
    # the last hundred words of the previous chunk, for continuity across the
    # cut without writing the same point twice
    prior = P["prior"].format(prior=" ".join(prev_text.split()[-120:])) if prev_text else ""
    names_block = P["names"].format(names="; ".join(names)) if names else ""
    summaries.append(ask(notes_intro + P["section"].format(
        chunk=c, prior=prior, names=names_block, roles=role_line)))
    extract_names(summaries[-1], names)
    prev_text = c
    el = time.time() - t0
    done = time.time() - t_start
    eta = done / i * (len(parts) - i)
    print(f"  section {i}/{len(parts)}  {el:.0f}s"
          + (f", about {eta/60:.0f} min left" if i < len(parts) else ""), flush=True)

# The model writes only the top of the note. The detail is the section notes
# themselves, one subheading per chunk, with every cited time linked to the
# transcript paragraph it came from. A second pass through the model used to
# rewrite the body and, with an 8B model, halved it every time.
print("  combining", flush=True)
ask_followups = prompts.wants_followups(" ".join(b for _, b in paras) + " " + own, NOTELANG)
followups = P["followups"] if ask_followups else ""
top = unfence(ask(notes_intro + P["combine"].format(
    sections="\n\n---\n\n".join(summaries), followups=followups)))
# whatever the model calls it, the section is kept only when it was asked for
top, open_q = split_off(top, H["open"])
top, legacy = split_off(top, H["legacy_open"])
if not ask_followups:
    open_q = ""
elif not open_q and legacy:
    open_q = legacy.replace(f"## {H['legacy_open']}", f"## {H['open']}", 1)

# Topic blocks carry their own titles, so no per-chunk heading: the reader sees
# one continuous run of topics, each with the time it starts linked into the
# transcript.
detail = [f"## {H['detail']}"]
for (start, end, c), notes in zip(parts, summaries):
    # snap only to markers inside this chunk: a time the model invents then
    # lands somewhere in the passage it was writing about, not at the far end
    # of the recording
    convert = linker(re.findall(r"\[(\d{1,2}:\d\d:\d\d)\]", c), rel_transcript)
    detail.append(convert(with_time_lines(notes.strip(), start)))
note = top.rstrip() + "\n\n" + merge_blocks("\n\n".join(detail)).rstrip()
if open_q:
    note += "\n\n" + open_q

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
    dest_dir = str(layout.auto_dir(NOTES, "unfiled"))

# The Type is typed by hand and goes into the file name, so it gets the same
# cleaning as the title: "LRT Panorama/Paprika" made a directory that did not
# exist and the note could not be written.
kind_fs = safe(kind)
if kind_fs and topic:
    fname = f"{stamp} {kind_fs} - {topic}.md"
elif topic:
    fname = f"{stamp} - {topic}.md"
elif kind_fs:
    fname = f"{stamp} {kind_fs}.md"
else:
    fname = f"{stamp}.md"

os.makedirs(dest_dir, exist_ok=True)
if os.path.basename(dest_dir) == SESSIONS:
    layout.write_sessions_about(dest_dir)
out = os.path.join(dest_dir, fname)
tmp = out + ".tmp"

audio = None
for ext in (".ogg", ".mp3", ".m4a", ".wav"):
    p = str(layout.auto_dir(NOTES, "audio") / (stamp + ext))
    if os.path.exists(p):
        audio = os.path.relpath(p, VAULT).replace(os.sep, "/")
        break

raw_link = layout.link(os.path.basename(NOTES), layout.RAW, stamp)

with open(tmp, "w", encoding="utf-8") as f:
    f.write("---\n")
    f.write(f'stamp: "{stamp}"\n')
    f.write(f"date: {when:%Y-%m-%d}\ntime: {when:%H:%M}\n")
    f.write("type: lecture-note\n")
    # written once by the pipeline, yours afterwards: nothing rewrites it
    f.write("generated: once\n")
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
    f.write(f"My notes: [[{raw_link}]]\n")
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

# link the your note back to the session it produced
try:
    if os.path.exists(raw_path):
        rel_out = os.path.relpath(out, VAULT)[:-3].replace(os.sep, "/")
        rawnote.set_link(raw_path, "Summary", rel_out)
except Exception:
    pass          # a missing backlink must not fail a completed summary

print(f"NOTE_PATH={out}")
