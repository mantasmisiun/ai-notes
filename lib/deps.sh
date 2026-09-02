#!/usr/bin/env bash
# Work out which build prerequisites are missing and print the exact command
# for this distribution. Never installs anything itself: a script people clone
# from the internet should not be reaching for sudo.

# vulkan_build_missing -> prints missing tool names, one per line, empty if none
vulkan_build_missing() {
  command -v cmake >/dev/null 2>&1 || echo cmake
  command -v git   >/dev/null 2>&1 || echo git
  command -v g++   >/dev/null 2>&1 || echo compiler
  command -v glslc >/dev/null 2>&1 || echo glslc
  [ -f /usr/include/vulkan/vulkan.h ] || echo vulkan-headers
}

# distro_id -> debian|arch|fedora|suse|unknown
distro_id() {
  [ -r /etc/os-release ] || { echo unknown; return; }
  . /etc/os-release
  case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*) echo debian ;;
    *" arch "*|*" archlinux "*) echo arch ;;
    *" fedora "*|*" rhel "*)    echo fedora ;;
    *" suse "*|*" opensuse "*)  echo suse ;;
    *) echo unknown ;;
  esac
}

# install_hint <tool>... -> one line the user can copy and run
install_hint() {
  local distro; distro="$(distro_id)"
  local pkgs=()
  for t in "$@"; do
    case "$distro:$t" in
      debian:cmake)          pkgs+=(cmake) ;;
      debian:git)            pkgs+=(git) ;;
      debian:compiler)       pkgs+=(build-essential) ;;
      debian:glslc)          pkgs+=(glslang-tools) ;;
      debian:vulkan-headers) pkgs+=(libvulkan-dev) ;;

      arch:cmake)            pkgs+=(cmake) ;;
      arch:git)              pkgs+=(git) ;;
      arch:compiler)         pkgs+=(base-devel) ;;
      arch:glslc)            pkgs+=(shaderc) ;;
      arch:vulkan-headers)   pkgs+=(vulkan-headers) ;;

      fedora:cmake)          pkgs+=(cmake) ;;
      fedora:git)            pkgs+=(git) ;;
      fedora:compiler)       pkgs+=(gcc-c++) ;;
      fedora:glslc)          pkgs+=(glslc) ;;
      fedora:vulkan-headers) pkgs+=(vulkan-headers) ;;

      suse:cmake)            pkgs+=(cmake) ;;
      suse:git)              pkgs+=(git) ;;
      suse:compiler)         pkgs+=(gcc-c++) ;;
      suse:glslc)            pkgs+=(shaderc) ;;
      suse:vulkan-headers)   pkgs+=(vulkan-devel) ;;

      *) pkgs+=("$t") ;;
    esac
  done
  case "$distro" in
    debian) printf 'sudo apt install %s\n' "${pkgs[*]}" ;;
    arch)   printf 'sudo pacman -S %s\n'   "${pkgs[*]}" ;;
    fedora) printf 'sudo dnf install %s\n' "${pkgs[*]}" ;;
    suse)   printf 'sudo zypper install %s\n' "${pkgs[*]}" ;;
    *)      printf 'install these with your package manager: %s\n' "${pkgs[*]}" ;;
  esac
}
