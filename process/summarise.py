#!/usr/bin/env python3
"""Turn an accurate transcript into a study note, filed into its module.

Two passes over the transcript because a lecture is far longer than the model's
context window, then a short third call for a topic to name the file with.
Prints the path it wrote, which run.sh records as the completion marker.
"""
import json, os, re, sys, urllib.request, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timetable
import prompts

transcript = sys.argv[1]
stamp      = sys.argv[2]                       # "YYYY-MM-DD HHMM"
VAULT      = os.path.expanduser(sys.argv[3])

UNI    = os.path.join(VAULT, "University")
NOTES  = os.path.join(VAULT, "Transcriptions")

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


def safe(name):
    name = re.sub(r"[\\/:*?\"<>|#^\[\]]", "", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:70]


P = prompts.get(NOTELANG, SRCLANG)

text  = body_of(transcript)
parts = chunks(text, WORDS)
print(f"{len(text.split())} words in {len(parts)} chunk(s)", flush=True)

summaries = []
for i, c in enumerate(parts, 1):
    print(f"  section {i}/{len(parts)}", flush=True)
    summaries.append(ask(P["section"].format(chunk=c)))

print("  combining", flush=True)
note = unfence(ask(P["combine"].format(sections="\n\n---\n\n".join(summaries))))

print("  titling", flush=True)
topic = safe(unfence(ask(P["topic"].format(note=note[:4000]), predict=30)).splitlines()[0])

# Where does it belong? Decided here, at summarise time, so a timetable you
# corrected after recording still routes the note correctly.
when = timetable.parse_stamp(stamp)
m    = timetable.match(timetable.load(UNI), when)

if m:
    dest_dir = os.path.join(UNI, m["module_folder"], "Lectures")
    fname    = f"{stamp} {m['kind']} - {topic}.md" if topic else f"{stamp} {m['kind']}.md"
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

with open(tmp, "w", encoding="utf-8") as f:
    f.write("---\n")
    f.write(f'stamp: "{stamp}"\n')
    f.write(f"date: {when:%Y-%m-%d}\ntime: {when:%H:%M}\n")
    f.write("type: lecture-note\n")
    if m:
        f.write(f"module: {m['code']}\n")
        f.write(f'module_name: "{m["name"]}"\n')
        f.write(f"session: {m['kind']}\n")
    f.write(f"model: {MODEL}\nnote_language: {NOTELANG}\n---\n\n")
    f.write(note.rstrip() + "\n\n---\n\n")
    f.write(f"Transcript: [[{rel_transcript}]]\n")
    if audio:
        f.write(f"\n![[{audio}]]\n")

os.replace(tmp, out)
print(f"NOTE_PATH={out}")
