#!/usr/bin/env bash
# Create an example module showing the layout and timetable format, unless one
# is already there. Dates are set to 2000 so it can never match a recording.
set -euo pipefail
UNI="$1"
DIR="$UNI/EXAMPLE001 Example Module"
[ -d "$DIR" ] && exit 0

mkdir -p "$DIR/Sessions"
cat > "$DIR/Timetable EXAMPLE001 Example Module.md" <<'TT'
This module folder shows the layout the pipeline expects. Copy the shape for
your real modules, then delete this one.

The folder name is `<CODE> <Module Name>`. Everything before the first space is
the code, and it appears in note frontmatter.

Only the second table is read. A date is written once per day and carries
forward to the rows beneath it. Columns after the fourth are ignored, so you can
add your own without breaking anything.

| Starting Date | Last Lecture | Exam Date  |
| ------------- | ------------ | ---------- |
| 01-01-2000    | 01-01-2000   | 01-01-2000 |

| Date       | Start time | End time | Type     |
| ---------- | ---------- | -------- | -------- |
| 01-01-2000 | 09:00      | 10:30    | Theory   |
|            | 10:45      | 12:15    | Practice |

![[Sessions/_index]]
TT

cat > "$DIR/Sessions/_index.md" <<'IX'
---
type: lecture-index
note: generated file, edits will be overwritten
---

*No lectures processed yet.*
IX
echo "created an example module at ${DIR#"$UNI/"}"
