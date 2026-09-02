#!/usr/bin/env python3
"""Answer 'which lecture is happening at this moment' from the module
timetables that already exist in the vault.

Dates are only written on the first row of a day and carry forward. Rows need
at least four cells whose 2nd and 3rd parse as times; the three-column summary
table at the top of each file is ignored, and trailing columns are tolerated.
"""
import os, re, sys, glob, datetime

TIME = re.compile(r"^\d{1,2}:\d{2}$")
DATE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
SLACK_MIN = 20          # allow starting the recording a little early or late


def load(university_dir):
    entries = []
    pattern = os.path.join(university_dir, "*", "Timetable *.md")
    for path in sorted(glob.glob(pattern)):
        folder = os.path.basename(os.path.dirname(path))
        code, _, name = folder.partition(" ")
        current = None
        for line in open(path, encoding="utf-8"):
            if not line.lstrip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 4:
                continue
            date_s, start_s, end_s, kind = cells[:4]
            if not (TIME.match(start_s) and TIME.match(end_s)):
                continue
            if DATE.match(date_s):
                current = datetime.datetime.strptime(date_s, "%d-%m-%Y").date()
            if current is None:
                continue
            entries.append({
                "module_folder": folder, "code": code, "name": name,
                "path": path,
                "date": current, "kind": kind,
                "start": datetime.datetime.strptime(start_s, "%H:%M").time(),
                "end":   datetime.datetime.strptime(end_s, "%H:%M").time(),
            })
    return entries


def match(entries, when):
    slack = datetime.timedelta(minutes=SLACK_MIN)
    for e in entries:
        s = datetime.datetime.combine(e["date"], e["start"]) - slack
        t = datetime.datetime.combine(e["date"], e["end"]) + slack
        if s <= when <= t:
            return e
    return None


def parse_stamp(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d %H%M")


if __name__ == "__main__":
    # --lookup <university dir> <"YYYY-MM-DD HHMM">
    #   prints "FOLDER<TAB>CODE<TAB>TYPE", or nothing when unmatched
    if sys.argv[1] == "--lookup":
        m = match(load(sys.argv[2]), parse_stamp(sys.argv[3]))
        if m:
            print(f"{m['module_folder']}\t{m['code']}\t{m['kind']}")
        sys.exit(0)

    es = load(sys.argv[1])
    print(f"{len(es)} rows across {len({e['module_folder'] for e in es})} modules")
    for probe in sys.argv[2:]:
        m = match(es, parse_stamp(probe))
        print(f"{probe} -> " + (f"{m['code']} {m['name']} [{m['kind']}]"
                                if m else "NO MATCH (unfiled)"))


# --- writing -----------------------------------------------------------------
# The pipeline only ever writes timetables it created itself. A hand-maintained
# schedule is read and never touched, so a bug in row insertion cannot damage
# the file you rely on to find everything.

GENERATED_MARK = "generated: lecture-pipeline"


def is_generated(path):
    p = os.path.join(path)
    if not os.path.exists(p):
        return False
    with open(p, encoding="utf-8") as f:
        return GENERATED_MARK in f.read(400)


def ensure_generated(module_dir, subject):
    """Create a timetable for a tree the pipeline made. Returns its path, or
    None when a hand-written one is already there."""
    existing = glob.glob(os.path.join(module_dir, "Timetable *.md"))
    if existing:
        return existing[0] if is_generated(existing[0]) else None

    path = os.path.join(module_dir, f"Timetable {subject}.md")
    os.makedirs(module_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + GENERATED_MARK + "\n---\n\n")
        f.write(f"# {subject}\n\nSessions are appended here as they are recorded.\n\n")
        f.write("| Date | Start time | End time | Type | Session |\n")
        f.write("| ---------- | ---------- | -------- | ---- | ------- |\n")
        f.write("\n![[Sessions/_index]]\n")
    return path


def append_row(path, date_str, start, end, kind, session_link=""):
    """Add one session. Idempotent: a row for the same date and start time is
    left alone rather than duplicated."""
    if not is_generated(path):
        return False
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == date_str and cells[1] == start:
            return False

    link = f"[[{session_link}]]" if session_link else ""
    row = f"| {date_str} | {start} | {end} | {kind} | {link} |\n"
    last = max((i for i, l in enumerate(lines) if l.lstrip().startswith("|")),
               default=len(lines) - 1)
    lines.insert(last + 1, row)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True
