#!/usr/bin/env python3
"""Blinking tray icon while a lecture is being recorded.
Left click stops the recording by calling the same toggle script."""
import os, sys, time, subprocess
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction
from PyQt6.QtCore import QTimer, Qt

# Resolve a sibling rather than a hardcoded home path: the project can be
# cloned anywhere, and was in fact moved and renamed.
TOGGLE = str(Path(__file__).resolve().parent / "record.py")
started = time.time()


def dot(colour):
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(colour))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(8, 8, 48, 48)
    p.end()
    return QIcon(pm)


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

on, off = dot("#e01b24"), dot("#5c1b1f")
tray = QSystemTrayIcon(on)
tray.setToolTip("Lecture recording")

menu = QMenu()
stop = QAction("Stop recording")
stop.triggered.connect(lambda: subprocess.Popen([sys.executable, TOGGLE]))
menu.addAction(stop)
tray.setContextMenu(menu)
tray.activated.connect(
    lambda reason: subprocess.Popen([sys.executable, TOGGLE])
    if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
tray.show()

state = {"lit": True}


def blink():
    state["lit"] = not state["lit"]
    tray.setIcon(on if state["lit"] else off)
    mins, secs = divmod(int(time.time() - started), 60)
    hrs, mins = divmod(mins, 60)
    tray.setToolTip(f"Lecture recording  {hrs:02d}:{mins:02d}:{secs:02d}\n"
                    f"Click to stop")


t = QTimer(); t.timeout.connect(blink); t.start(900)
sys.exit(app.exec())
