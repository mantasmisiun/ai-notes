#!/usr/bin/env python3
"""A recording in progress, visible to every machine the vault syncs to.

The recorder keeps a small file beside its live note and rewrites it every
HEARTBEAT seconds while it runs; a normal stop deletes it. The processing
machine leaves the vault alone while any such file is still changing. It
used to see only a lock on its own disk, so while the laptop recorded, the
desktop migrated the live note and the user's note out from under the
worker, which crashed, and sync then delivered both copies.

Freshness is judged by whether the content changed, timed on the reader's
own clock. File times would do neither job: sync tools carry the writer's
mtime, and the two machines' clocks need not agree. A recorder that died
without deleting its file therefore releases the vault FRESH seconds later,
and the file itself is removed once it has been dead for a day.
"""
import json
import os
import socket
import time
from pathlib import Path

import layout

SUFFIX    = ".recording"
HEARTBEAT = 30          # seconds between rewrites
FRESH     = 600         # unchanged this long by the reader's clock: the recorder is gone
FORGET    = 86400       # and after this long the file is deleted
HOST      = socket.gethostname()


def lease_path(notes, stamp):
    return layout.auto_dir(notes, "live") / f"{stamp}{SUFFIX}"


class Lease:
    """Held by the recorder. Every failure is swallowed: a heartbeat that
    cannot be written must never cost a recording."""

    def __init__(self, notes, stamp):
        self.path = lease_path(notes, stamp)
        self.beats = 0
        self.last = 0.0

    def beat(self, force=False):
        now = time.monotonic()
        if not force and now - self.last < HEARTBEAT:
            return
        self.last = now
        self.beats += 1
        body = json.dumps({"host": HOST, "beat": self.beats,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(body, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def end(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def clear_own(notes):
    """Leases this machine left behind when a recorder died. Called with the
    recording lock held, so none of them can belong to a live recording."""
    d = layout.auto_dir(notes, "live")
    for p in (d.glob("*" + SUFFIX) if d.is_dir() else []):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("host") == HOST:
                p.unlink()
        except (OSError, ValueError, AttributeError):
            pass


def active(notes, state_dir, now=None):
    """Stamps whose recording is still running on some machine. What each
    lease said last, and when this machine first saw it say that, is kept in
    state_dir between runs."""
    seen_f = Path(state_dir) / "leases.json"
    try:
        seen = json.loads(seen_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    now = time.time() if now is None else now
    live, keep = set(), {}
    d = layout.auto_dir(notes, "live")
    for p in (d.glob("*" + SUFFIX) if d.is_dir() else []):
        stamp = p.name[:-len(SUFFIX)]
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            live.add(stamp)                # mid-write or mid-sync: assume alive
            continue
        prev = seen.get(stamp)
        if not prev or prev[0] != content:
            prev = [content, now]
        idle = now - prev[1]
        if idle < FRESH:
            live.add(stamp)
        if idle > FORGET:
            try:
                p.unlink()
            except OSError:
                pass
            continue
        keep[stamp] = prev
    if keep != seen:
        try:
            Path(state_dir).mkdir(parents=True, exist_ok=True)
            seen_f.write_text(json.dumps(keep), encoding="utf-8")
        except OSError:
            pass
    return live
