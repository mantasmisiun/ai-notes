#!/usr/bin/env python3
"""Read config.sh without a shell, so it works on Windows too."""
import os
import re
import sys
from pathlib import Path


def read_config(path):
    cfg = {}
    path = Path(path)
    if not path.exists():
        sys.exit(f"no config found at {path}\nrun the installer first")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r'^\s*([A-Z_]+)="?(.*?)"?\s*$', line)
        if m:
            cfg[m.group(1)] = os.path.expandvars(m.group(2))
    return cfg


def notes_dirs(cfg):
    vault = Path(cfg["VAULT"])
    notes = vault / cfg.get("TRANSCRIPTIONS_DIR", "Transcriptions")
    uni   = vault / cfg.get("UNIVERSITY_DIR", "University")
    return vault, notes, uni


def set_config(path, key, value):
    """Update or append one key, leaving the rest of the file untouched."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(rf'^\s*{key}=', line):
            lines[i] = f'{key}="{value}"\n'
            break
    else:
        lines.append(f'{key}="{value}"\n')
    path.write_text("".join(lines), encoding="utf-8")
