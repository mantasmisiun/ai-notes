#!/usr/bin/env python3
"""Report the best GPU on this machine, whatever made it.

nvidia-smi is authoritative when present. Otherwise vulkaninfo is parsed, which
covers AMD and Intel including discrete cards. Its --summary gives device type
but not memory, and the full output's largest device-local heap can belong to
the CPU rasteriser, so device sections have to be walked properly.

Prints one line:  VENDOR<TAB>NAME<TAB>VRAM_MIB<TAB>DISCRETE(1|0)
"""
import re
import subprocess
import sys

HEAP_SIZE = re.compile(r"size\s+=\s+(\d+)")


def from_nvidia_smi():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        best = None
        for line in r.stdout.strip().splitlines():
            name, total, free = [x.strip() for x in line.split(",")]
            # Free matters more than total. On a laptop where an integrated GPU
            # drives the display, the whole discrete card is available, and a
            # threshold on total size would rule out a card that fits the model.
            cand = ("nvidia", name, int(free), 1)
            if best is None or cand[2] > best[2]:
                best = cand
        return best
    except Exception:
        return None


def from_vulkaninfo():
    try:
        out = subprocess.run(["vulkaninfo"], capture_output=True,
                             text=True, timeout=40).stdout
    except Exception:
        return None
    if not out:
        return None

    blocks = re.split(r"^GPU\d+:\s*$", out, flags=re.M)[1:]
    best = None
    for b in blocks:
        m = re.search(r"deviceType\s+=\s+PHYSICAL_DEVICE_TYPE_(\w+)", b)
        if not m:
            continue
        kind = m.group(1)
        if kind == "CPU":
            continue                                 # the software rasteriser
        name = (re.search(r"deviceName\s+=\s+(.+)", b) or [None, "unknown"])[1].strip()

        # the largest heap flagged device-local, within this device only
        vram = 0
        for heap in re.split(r"memoryHeaps\[\d+\]:", b)[1:]:
            if "MEMORY_HEAP_DEVICE_LOCAL_BIT" not in heap.split("memoryTypes")[0]:
                continue
            s = HEAP_SIZE.search(heap)
            if s:
                vram = max(vram, int(s.group(1)) // (1024 * 1024))

        vendor = ("amd" if re.search(r"amd|radeon|radv", name, re.I) else
                  "intel" if re.search(r"intel|arc", name, re.I) else "other")
        discrete = 1 if kind == "DISCRETE_GPU" else 0
        cand = (vendor, name, vram, discrete)
        if best is None or (discrete, vram) > (best[3], best[2]):
            best = cand
    return best


def main():
    g = from_nvidia_smi() or from_vulkaninfo() or ("none", "", 0, 0)
    print("\t".join(str(x) for x in g))


if __name__ == "__main__":
    main()
