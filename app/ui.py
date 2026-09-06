"""Minimal terminal output helpers.

No dependency, no animation, no ASCII art. Colour is used only to separate
labels from values and is disabled automatically when stdout is not a TTY or
when NO_COLOR is set, so piped logs stay clean.

Output is routed through a *sink*. The default :class:`ConsoleSink` writes to the
terminal exactly as before -- each of its methods is the original module-level
function, verbatim. The web server swaps in an alternate sink per request (via a
ContextVar) to capture the same progress as structured Server-Sent Events,
without touching a single ``ui.*`` call site or changing the CLI's byte-for-byte
output.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

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


class ConsoleSink:
    """Writes pipeline progress to the terminal (the default sink).

    Every method below is the original module-level function moved verbatim, so
    the CLI's output is unchanged. :meth:`event` is a no-op: structured
    milestones only matter to non-console sinks such as the web SSE stream.
    """

    def rule(self, char: str = "=") -> None:
        print(char * RULE_WIDTH)

    def banner(self, title: str) -> None:
        self.rule()
        print(_c(title, _BOLD))
        self.rule()

    def section(self, title: str) -> None:
        print()
        print(_c(title, _BOLD + _CYAN))

    def step(self, index: int, total: int, title: str) -> None:
        print()
        print(_c(f"[{index}/{total}]", _DIM) + " " + _c(title, _BOLD))

    def ok(self, message: str) -> None:
        print(f"  {_c('OK', _GREEN)}   {message}")

    def info(self, message: str) -> None:
        print(f"  {_c('..', _DIM)}   {message}")

    def warn(self, message: str) -> None:
        print(f"  {_c('WARN', _YELLOW)} {message}")

    def fail(self, message: str) -> None:
        print(f"  {_c('FAIL', _RED)} {message}")

    def kv(self, key: str, value: object, indent: int = 2) -> None:
        """Print an aligned ``key: value`` line."""
        pad = " " * indent
        label = f"{key + ':':<22}"
        print(f"{pad}{_c(label, _DIM)} {value}")

    def verdict(self, label: str, passed: bool) -> None:
        """Print the headline pass/fail line."""
        mark = "PASS" if passed else "FAIL"
        colour = _GREEN if passed else _RED
        print()
        self.rule()
        print(_c(f"{label}: {mark}", _BOLD + colour))
        self.rule()

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        """Structured milestone hook. No-op for console output."""
        return None


#: The default sink and the per-context active sink. A ContextVar (not a plain
#: global) is load-bearing: it isolates concurrent web jobs -- ``asyncio.to_thread``
#: copies the context per call, so a sink set inside one worker is invisible to
#: the event loop and to every other job.
_console = ConsoleSink()
_active_sink: ContextVar[ConsoleSink] = ContextVar("ui_active_sink", default=_console)


@contextmanager
def use_sink(sink: ConsoleSink) -> Iterator[ConsoleSink]:
    """Temporarily route ``ui.*`` through ``sink``, restoring the previous one."""
    token = _active_sink.set(sink)
    try:
        yield sink
    finally:
        _active_sink.reset(token)


# --- module-level delegators -------------------------------------------------
# Every existing ui.* call site is unchanged; each now forwards to the active
# sink, which defaults to the console.


def rule(char: str = "=") -> None:
    _active_sink.get().rule(char)


def banner(title: str) -> None:
    _active_sink.get().banner(title)


def section(title: str) -> None:
    _active_sink.get().section(title)


def step(index: int, total: int, title: str) -> None:
    _active_sink.get().step(index, total, title)


def ok(message: str) -> None:
    _active_sink.get().ok(message)


def info(message: str) -> None:
    _active_sink.get().info(message)


def warn(message: str) -> None:
    _active_sink.get().warn(message)


def fail(message: str) -> None:
    _active_sink.get().fail(message)


def kv(key: str, value: object, indent: int = 2) -> None:
    _active_sink.get().kv(key, value, indent)


def verdict(label: str, passed: bool) -> None:
    _active_sink.get().verdict(label, passed)


def event(kind: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a structured milestone to the active sink (no-op on the console)."""
    _active_sink.get().event(kind, payload or {})


def error_banner(kind: str, message: str, hint: str | None = None) -> None:
    print()
    rule()
    print(_c(kind, _BOLD + _RED))
    rule()
    print(message)
    if hint:
        print()
        print(_c("hint: ", _BOLD) + hint)
