#!/usr/bin/env python3
"""Ask what to do about a transcript that will not summarise.

Launched as a separate process so that a machine without PyQt6 simply logs and
carries on rather than breaking the pipeline.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def open_installer():
    """Best effort: the installer is interactive, so it needs a terminal."""
    cmd = f'cd "{ROOT}" && ./install.sh; exec bash'
    for term, args in (("konsole", ["-e", "bash", "-lc", cmd]),
                       ("gnome-terminal", ["--", "bash", "-lc", cmd]),
                       ("xfce4-terminal", ["-e", f"bash -lc '{cmd}'"]),
                       ("xterm", ["-e", "bash", "-lc", cmd]),
                       ("x-terminal-emulator", ["-e", "bash", "-lc", cmd])):
        try:
            subprocess.Popen([term] + args)
            return True
        except FileNotFoundError:
            continue
    return False


def main():
    stamp  = sys.argv[1]
    reason = sys.argv[2] if len(sys.argv) > 2 else ""

    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv)

    box = QMessageBox()
    box.setWindowTitle("Summarising failed")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(f"Processing <b>{stamp}</b> has failed.")
    box.setInformativeText(
        (reason + "\n\n" if reason else "")
        + "It has been tried twice and will not be tried again until you choose.\n\n"
          "A model too large for the card is the usual cause: Ollama runs the\n"
          "part that does not fit on the CPU, so it never finishes.")
    ignore = box.addButton("Ignore this file", QMessageBox.ButtonRole.RejectRole)
    change = box.addButton("Change model",     QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(change)
    box.exec()

    if box.clickedButton() is ignore:
        print("IGNORE")
    else:
        print("CHANGE")
        if not open_installer():
            print("no terminal found; run ./install.sh yourself", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
