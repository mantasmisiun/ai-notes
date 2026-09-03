#!/usr/bin/env python3
"""Run the accurate transcription pass, with a window so it is not a mystery.

Called by record.py when a recording stops, and by resume.py for anything left
unfinished. Safe to run twice: an existing transcript is left alone.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE))

import platform_support as ps
from config_read import read_config, notes_dirs

from PyQt6.QtCore import Qt, QProcess, QTimer
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QProgressBar, QPushButton, QHBoxLayout)

AUDIO_EXT = (".ogg", ".mp3", ".m4a", ".wav")


def audio_for(NOTES, stamp):
    for ext in AUDIO_EXT:
        p = NOTES / "audio" / f"{stamp}{ext}"
        if p.exists():
            return p
    return None


class Finisher(QWidget):
    def __init__(self, stamp, audio, transcript, env):
        super().__init__()
        self.transcript = transcript
        self.setWindowTitle("Finishing transcription")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{stamp}</b>"))
        lay.addWidget(QLabel("Producing the accurate transcript. This takes a\n"
                             "few minutes and uses the GPU. You can leave it\n"
                             "running in the background."))
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)                      # indeterminate
        lay.addWidget(self.bar)
        self.status = QLabel("starting")
        self.status.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.hide_btn = QPushButton("Run in background")
        self.hide_btn.clicked.connect(self.hide)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancel)
        row.addWidget(self.hide_btn)
        row.addStretch()
        row.addWidget(cancel)
        lay.addLayout(row)

        self.proc = QProcess(self)
        pe = self.proc.processEnvironment()
        for k, v in env.items():
            pe.insert(k, str(v))
        self.proc.setProcessEnvironment(pe)
        self.proc.readyReadStandardError.connect(self.on_output)
        self.proc.readyReadStandardOutput.connect(self.on_output)
        self.proc.finished.connect(self.on_done)
        self.proc.start(ps.venv_python(HERE / "venv"),
                        [str(HERE.parent / "process" / "transcribe.py"),
                         str(audio), str(transcript)])

    def on_output(self):
        for stream in (self.proc.readAllStandardOutput(),
                       self.proc.readAllStandardError()):
            text = bytes(stream).decode(errors="ignore").strip()
            if text:
                self.status.setText(text.splitlines()[-1][:80])

    def on_done(self, code, _status):
        if code == 0 and Path(self.transcript).exists():
            ps.notify("Transcript ready", Path(self.transcript).stem)
        else:
            ps.notify("Transcription failed", "The recording is still there; "
                                              "it will be offered again.")
            Path(str(self.transcript) + ".tmp").unlink(missing_ok=True)
        QApplication.quit()

    def cancel(self):
        # Leave the audio and the live note in place: resume.py will offer it
        # again rather than losing the recording.
        self.proc.kill()
        Path(str(self.transcript) + ".tmp").unlink(missing_ok=True)
        QApplication.quit()


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: finish.py <stamp>")
    stamp = sys.argv[1]

    cfg = read_config(ROOT / "config.sh")
    VAULT, NOTES, _ = notes_dirs(cfg)
    transcript = NOTES / "transcripts" / f"{stamp}.md"
    if transcript.exists():
        return 0                                   # already done, nothing to do

    audio = audio_for(NOTES, stamp)
    if not audio:
        return 0

    env = dict(os.environ,
               LECTURE_ASR_MODEL=cfg.get("LECTURE_ASR_MODEL", "large-v3"),
               LECTURE_ASR_COMPUTE=cfg.get("LECTURE_ASR_COMPUTE", "float16"),
               LECTURE_ASR_DEVICE=("cpu" if cfg.get("LECTURE_BACKEND") == "cpu"
                                   else "cuda"),
               LECTURE_LANGUAGE=cfg.get("LECTURE_LANGUAGE", "en"))

    app = QApplication(sys.argv)
    w = Finisher(stamp, audio, transcript, env)
    w.show()
    QTimer.singleShot(0, lambda: None)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
