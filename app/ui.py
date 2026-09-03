"""Minimal terminal output helpers.

No dependency, no animation, no ASCII art. Colour is used only to separate
labels from values and is disabled automatically when stdout is not a TTY or
when NO_COLOR is set, so piped logs stay clean.
"""

from __future__ import annotations

import os
import sys

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"

RULE_WIDTH = 64


def _c(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _ENABLED else text


def rule(char: str = "=") -> None:
    print(char * RULE_WIDTH)


def banner(title: str) -> None:
    rule()
    print(_c(title, _BOLD))
    rule()


def section(title: str) -> None:
    print()
    print(_c(title, _BOLD + _CYAN))


def step(index: int, total: int, title: str) -> None:
    print()
    print(_c(f"[{index}/{total}]", _DIM) + " " + _c(title, _BOLD))


def ok(message: str) -> None:
    print(f"  {_c('OK', _GREEN)}   {message}")


def info(message: str) -> None:
    print(f"  {_c('..', _DIM)}   {message}")


def warn(message: str) -> None:
    print(f"  {_c('WARN', _YELLOW)} {message}")


def fail(message: str) -> None:
    print(f"  {_c('FAIL', _RED)} {message}")


def kv(key: str, value: object, indent: int = 2) -> None:
    """Print an aligned ``key: value`` line."""
    pad = " " * indent
    label = f"{key + ':':<22}"
    print(f"{pad}{_c(label, _DIM)} {value}")


def verdict(label: str, passed: bool) -> None:
    """Print the headline pass/fail line."""
    mark = "PASS" if passed else "FAIL"
    colour = _GREEN if passed else _RED
    print()
    rule()
    print(_c(f"{label}: {mark}", _BOLD + colour))
    rule()


def error_banner(kind: str, message: str, hint: str | None = None) -> None:
    print()
    rule()
    print(_c(kind, _BOLD + _RED))
    rule()
    print(message)
    if hint:
        print()
        print(_c("hint: ", _BOLD) + hint)
