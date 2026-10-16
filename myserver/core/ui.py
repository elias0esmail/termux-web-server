"""Colored terminal helpers and fzf-based chooser."""
from __future__ import annotations

import subprocess
import sys

from .helpers import command_exists

C_RESET   = "\033[0m"
C_RED     = "\033[1;31m"
C_GREEN   = "\033[1;32m"
C_YELLOW  = "\033[1;33m"
C_BLUE    = "\033[1;34m"
C_MAGENTA = "\033[1;35m"
C_CYAN    = "\033[1;36m"
C_BOLD    = "\033[1m"


def ok(msg: str):    print(f"{C_GREEN} [✓] {msg} {C_RESET}")
def info(msg: str):  print(f"{C_CYAN} [i] {msg} {C_RESET}")
def warn(msg: str):  print(f"{C_YELLOW} [!] {msg} {C_RESET}")
def err(msg: str):   print(f"{C_RED} [!] {msg} {C_RESET}")
def step(msg: str):  print(f"{C_BLUE} [*] {msg} {C_RESET}")


def ensure_fzf() -> bool:
    if command_exists("fzf"):
        return True
    print(f"{C_YELLOW}[*] Installing fzf (one-time)...{C_RESET}")
    r = subprocess.run("pkg install -y fzf", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and command_exists("fzf")


def choose_option(title: str, options: list[str], default: int = 0) -> int:
    if not options:
        return 0
    if len(options) == 1:
        return 0
    if not ensure_fzf():
        print(f"{C_CYAN}{title}{C_RESET}")
        for i, opt in enumerate(options, 1):
            print(f"  {i}) {opt}")
        try:
            raw = input(f"{C_YELLOW}Select [1-{len(options)}] (default {default+1}): {C_RESET}").strip()
            if not raw:
                return default
            return max(0, min(len(options) - 1, int(raw) - 1))
        except Exception:
            return default

    sys.stdout.write("\033[0m\n")
    sys.stdout.flush()

    lines = [f"{i}\t{opt}" for i, opt in enumerate(options)]
    reordered = [lines[default]] + [l for i, l in enumerate(lines) if i != default]
    try:
        result = subprocess.run(
            ["fzf", "--height=8", "--min-height=5", "--layout=reverse",
             "--no-multi", "--no-mouse", "--no-info", "--no-separator",
             "--no-scrollbar", "--with-nth=2..", "--delimiter=\t",
             f"--header={title}", "--header-first", "--pointer=>",
             "--marker= ", "--prompt=  ",
             "--color=pointer:cyan,fg+:cyan,header:yellow,prompt:cyan"],
            input="\n".join(reordered) + "\n", capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            idx_str = result.stdout.strip().split("\t", 1)[0]
            try:
                idx = int(idx_str)
                if 0 <= idx < len(options):
                    return idx
            except ValueError:
                pass
    except Exception:
        pass
    return default


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"{C_YELLOW}{prompt} {suffix}: {C_RESET}").strip().lower()
    except Exception:
        return default
    if not raw:
        return default
    return raw in ("y", "yes")