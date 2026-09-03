#!/usr/bin/env python3
"""Make the CUDA libraries that pip installed findable.

The nvidia-* wheels put their libraries inside the venv, where neither the
Linux dynamic loader nor the Windows DLL search path looks. glibc reads
LD_LIBRARY_PATH once at process start, so setting it from Python is too late;
Windows needs the directory registered explicitly.

Import this before faster_whisper in anything that may run on a GPU.
"""
import glob
import os
import sys
from pathlib import Path


def enable():
    try:
        import nvidia
    except ImportError:
        return False

    roots = [Path(r) for r in nvidia.__path__]
    libdirs = [d for r in roots for d in r.glob("*/lib")]
    if sys.platform.startswith("win"):
        libdirs += [d for r in roots for d in r.glob("*/bin")]   # DLLs live here

    if not libdirs:
        return False

    if sys.platform.startswith("win"):
        for d in libdirs:
            try:
                os.add_dll_directory(str(d))
            except (OSError, AttributeError):
                pass
        os.environ["PATH"] = os.pathsep.join(
            [str(d) for d in libdirs] + [os.environ.get("PATH", "")])
    else:
        import ctypes
        sos = [so for d in libdirs for so in glob.glob(str(d / "*.so*"))]
        for _ in range(2):                 # second pass resolves load order
            for so in sos:
                try:
                    ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass
    return True
