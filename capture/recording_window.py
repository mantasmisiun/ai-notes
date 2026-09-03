#!/usr/bin/env python3
"""A window saying a recording is in progress, with a way to stop it.

The tray dot works on Linux but is easy to miss on Windows, where trays hide
icons by default. This is deliberately hard to overlook: always on top, a
flashing red light, the elapsed time, and one button.

Stopping writes the stop file that record.py watches, which is the same
mechanism the launcher uses, so the two can never disagree.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))
import platform_support as ps

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton)


def dot(colour, size=18):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return pm


class RecordingWindow(QWidget):
    def __init__(self, label, stop_path):
        super().__init__()
        self.stop_path = Path(stop_path)
        self.started = time.time()
        self.lit = True
        self.on, self.off = dot("#e01b24"), dot("#5c1b1f")

        self.setWindowTitle("Recording")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(320)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.light = QLabel()
        self.light.setPixmap(self.on)
        top.addWidget(self.light)
        self.title = QLabel(f"<b>Recording</b> {label}")
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)

        self.clock = QLabel("00:00:00")
        self.clock.setStyleSheet("font-size: 22pt;")
        lay.addWidget(self.clock)

        self.hint = QLabel("Type your notes in the 'my notes' file,\n"
                           "not in the transcript.")
        self.hint.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.hint)

        stop = QPushButton("Stop recording")
        stop.clicked.connect(self.stop)
        lay.addWidget(stop)

        t = QTimer(self)
        t.timeout.connect(self.tick)
        t.start(500)
        self.timer = t

    def tick(self):
        self.lit = not self.lit
        self.light.setPixmap(self.on if self.lit else self.off)
        secs = int(time.time() - self.started)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        self.clock.setText(f"{h:02d}:{m:02d}:{s:02d}")
        # record.py removes the stop file when it has finished shutting down
        if self.stop_path.exists() and secs > 2:
            self.title.setText("<b>Finishing…</b>")

    def stop(self):
        self.stop_path.parent.mkdir(parents=True, exist_ok=True)
        self.stop_path.touch()
        self.title.setText("<b>Finishing…</b>")
        self.timer.stop()
        self.light.setPixmap(self.off)
        QTimer.singleShot(1500, QApplication.quit)

    def closeEvent(self, e):
        # Closing the window must not silently leave a recording running.
        self.stop()
        e.ignore()


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else ""
    stop_path = sys.argv[2] if len(sys.argv) > 2 else str(ps.state_dir() / "stop")
    app = QApplication(sys.argv)
    w = RecordingWindow(label, stop_path)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
