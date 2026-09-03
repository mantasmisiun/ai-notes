#!/usr/bin/env bash
# Hardware detection shared by the installer. Sets, and never prints:
#   OS_NAME  CPU_NAME  CPU_THREADS
#   GPU_NAME  GPU_VENDOR (nvidia|amd|intel|none)  VRAM_MIB  HAS_CUDA  HAS_VULKAN

OS_NAME="$(uname -s)"

# Scratch space for raw audio while recording. Per-platform, never asked about:
# it is temporary, machine-local, and must not sit inside a synced vault.
case "$OS_NAME" in
  Darwin)               DEFAULT_SCRATCH="$HOME/Library/Caches/lecture-pipeline" ;;
  MINGW*|MSYS*|CYGWIN*) DEFAULT_SCRATCH="${LOCALAPPDATA:-$HOME/AppData/Local}/lecture-pipeline" ;;
  *)                    DEFAULT_SCRATCH="${XDG_CACHE_HOME:-$HOME/.cache}/lecture-pipeline" ;;
esac
CPU_NAME="$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo 2>/dev/null | head -1)"
CPU_NAME="${CPU_NAME:-unknown}"
CPU_THREADS="$(nproc 2>/dev/null || echo 1)"

# One probe covers all three vendors. nvidia-smi is authoritative where it
# exists; otherwise vulkaninfo is parsed, which is the only way to learn the
# VRAM of an AMD or Intel card and whether it is discrete or integrated.
IFS=$'\t' read -r GPU_VENDOR GPU_NAME VRAM_MIB GPU_DISCRETE < <(
  python3 "$(dirname "${BASH_SOURCE[0]}")/../shared/gpu_probe.py" 2>/dev/null)
GPU_VENDOR="${GPU_VENDOR:-none}"; GPU_NAME="${GPU_NAME:-}"
VRAM_MIB="${VRAM_MIB:-0}"; GPU_DISCRETE="${GPU_DISCRETE:-0}"
HAS_CUDA=0; [ "$GPU_VENDOR" = "nvidia" ] && HAS_CUDA=1

if command -v vulkaninfo >/dev/null 2>&1 && vulkaninfo --summary >/dev/null 2>&1; then
  HAS_VULKAN=1
elif [ -d /usr/share/vulkan/icd.d ] && [ -n "$(ls -A /usr/share/vulkan/icd.d 2>/dev/null)" ]; then
  HAS_VULKAN=1
fi

# An NVIDIA card exposes Vulkan too, but CUDA is faster and better tested, so
# the installer does not offer Vulkan there.
#
# Written as an if rather than `[ ... ] && VAR=0`: that form returns 1 when the
# test is false, and as the last command of a sourced file it aborts the caller
# under `set -e`. It did, silently, on every non-NVIDIA machine.
if [ "$GPU_VENDOR" = "nvidia" ]; then
  HAS_VULKAN=0
fi
true
