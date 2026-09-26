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
    if sys.platform == "win32":
        # install.bat in a console of its own; "start" gives it one even though
        # the pipeline runs without a window.
        bat = ROOT / "windows" / "install.bat"
        try:
            subprocess.Popen(["cmd", "/c", "start", "ai-notes installer", str(bat)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except OSError:
            return False
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
    # A refused connection is Ollama not running, not a model problem, and the
    # usual advice sent people looking at model sizes.
    refused = any(k in reason for k in ("10061", "Connection refused", "actively refused"))
    cause = ("Ollama is not running on this machine. Start it, or choose Change\n"
             "model: the installer installs and starts it, then fetches the model."
             if refused else
             "A model too large for the card is the usual cause: Ollama runs the\n"
             "part that does not fit on the CPU, so it never finishes.")
    box.setInformativeText(
        (reason + "\n\n" if reason else "")
        + "It has been tried twice and will not be tried again until you choose.\n\n"
        + cause)
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
