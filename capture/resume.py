#!/usr/bin/env python3
"""Offer to finish transcriptions interrupted by a closed lid or a shutdown.

Run at login. A recording that has audio but no transcript was cut short, so
ask whether to finish it. The answer can be remembered, in which case this
never asks again and acts on the stored choice.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE))

from config_read import read_config, notes_dirs, set_config

AUDIO_EXT = (".ogg", ".mp3", ".m4a", ".wav")
CONF = ROOT / "config.sh"


def pending(NOTES):
    """Recordings with audio but no transcript, oldest first."""
    out = []
    audio_dir = NOTES / "auto" / "audio"
    if not audio_dir.is_dir():
        return out
    for a in sorted(audio_dir.iterdir()):
        if a.suffix.lower() not in AUDIO_EXT or a.stat().st_size == 0:
            continue
        if (NOTES / "auto" / "transcripts" / f"{a.stem}.md").exists():
            continue
        out.append(a.stem)
    return out


def finish(stamps):
    for s in stamps:
        subprocess.run([sys.executable, str(HERE / "finish.py"), s])


def main():
    cfg = read_config(CONF)
    _, NOTES, _ = notes_dirs(cfg)
    stamps = pending(NOTES)
    if not stamps:
        return 0

    choice = cfg.get("LECTURE_RESUME", "ask")
    if choice == "never":
        return 0
    if choice == "always":
        finish(stamps)
        return 0

    from PyQt6.QtWidgets import QApplication, QMessageBox, QCheckBox
    app = QApplication(sys.argv)

    box = QMessageBox()
    box.setWindowTitle("Unfinished transcription")
    box.setIcon(QMessageBox.Icon.Question)
    listed = "\n".join(f"  {s}" for s in stamps[:5])
    more = f"\n  and {len(stamps) - 5} more" if len(stamps) > 5 else ""
    box.setText("Do you want to finish live transcription processing?")
    box.setInformativeText(
        f"{len(stamps)} recording(s) have audio but no transcript:\n\n"
        f"{listed}{more}\n\nThis uses the GPU for a few minutes each.")
    box.setStandardButtons(QMessageBox.StandardButton.Yes |
                           QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.Yes)

    remember = QCheckBox("Do not ask me again")
    box.setCheckBox(remember)

    answer = box.exec()
    yes = answer == QMessageBox.StandardButton.Yes.value

    if remember.isChecked():
        # Whichever way they answered becomes the standing decision.
        set_config(CONF, "LECTURE_RESUME", "always" if yes else "never")

    if yes:
        finish(stamps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
