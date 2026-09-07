"""Dedicated terminal audit renderer for live pipeline verification events.

Consumes the exact same structured audit events emitted by EventSink and formats
them as an authentic forensic evidence trail in the server terminal session,
while keeping Uvicorn HTTP server logs cleanly separated.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import sys
import threading
from typing import Any, TextIO

logger = logging.getLogger("app.terminal")

_WRITE_LOCK = threading.Lock()

# ANSI Color sequences
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_BRIGHT_CYAN = "\033[96m"
_GREEN = "\033[32m"
_BRIGHT_GREEN = "\033[92m"
_YELLOW = "\033[33m"
_BRIGHT_YELLOW = "\033[93m"
_RED = "\033[31m"
_BRIGHT_RED = "\033[91m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_WHITE = "\033[37m"


def _is_color_enabled(stream: TextIO | None = None) -> bool:
    """Return True if ANSI styling should be emitted on the target stream."""
    if os.environ.get("NO_COLOR"):
        return False
    target = stream or sys.stdout
    try:
        return target.isatty()
    except Exception:
        return False


def _c(text: str, code: str, enabled: bool) -> str:
    """Wrap text in ANSI code if color is enabled."""
    return f"{code}{text}{_RESET}" if enabled else text


def _supports_unicode(stream: TextIO | None = None) -> bool:
    """Check if stream encoding supports Unicode box-drawing characters."""
    target = stream or sys.stdout
    enc = getattr(target, "encoding", "") or ""
    return "utf" in enc.lower()


def _term_width(stream: TextIO | None = None, min_width: int = 68, max_width: int = 92, default: int = 80) -> int:
    """Determine a safe, bounded terminal line width."""
    try:
        cols = shutil.get_terminal_size(fallback=(default, 24)).columns
        return max(min_width, min(cols, max_width))
    except Exception:
        return default


def _short_id(job_id: str | None) -> str:
    """Return a short 8-character hex ID for clean tabular alignment."""
    if not job_id:
        return "--------"
    return str(job_id)[:8]


class TerminalAuditRenderer:
    """Forensic terminal renderer consuming structured verification audit events.

    This renderer is purely an observability layer. It never creates, alters, or
    fabricates events, and failures inside the renderer are strictly isolated.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        job_id: str | None = None,
        filename: str | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self._stream = stream or sys.stdout
        self._job_id = job_id
        self._filename = filename
        self._lock = lock or _WRITE_LOCK
        self._current_step = 0
        self._total_steps = 7
        self._step_title = ""

    def render(self, event: dict[str, Any]) -> None:
        """Render a single event dictionary safely with thread-locking and isolation."""
        try:
            with self._lock:
                self._render_locked(event)
        except Exception as exc:
            # Failure isolation: rendering failure must never affect pipeline or SSE delivery
            logger.warning("TerminalAuditRenderer failed to render event %s: %s", event.get("type"), exc)

    # -----------------------------------------------------------------------
    # Internal Render Dispatcher
    # -----------------------------------------------------------------------

    def _render_locked(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "hello":
            self._render_job_header(event)
        elif etype == "step":
            self._render_step(event)
        elif etype == "log":
            self._render_log(event)
        elif etype == "kv":
            self._render_kv(event)
        elif etype == "milestone":
            self._render_milestone(event)
        elif etype == "verdict":
            self._render_verdict(event)
        elif etype == "result":
            self._render_result(event)
        elif etype == "error":
            self._render_error(event)
        elif etype == "section":
            self._render_section(event)
        # banners or other event types are handled or pass silently

    # -----------------------------------------------------------------------
    # Event Presentation Components
    # -----------------------------------------------------------------------

    def _render_job_header(self, event: dict[str, Any]) -> None:
        """Render compact forensic audit session header."""
        color = _is_color_enabled(self._stream)
        unicode_box = _supports_unicode(self._stream)
        width = _term_width(self._stream)

        job_id = event.get("job_id") or self._job_id or "—"
        self._job_id = job_id
        filename = event.get("filename") or self._filename or "upload"
        self._filename = filename
        time_str = event.get("time") or datetime.datetime.now().strftime("%H:%M:%S")

        tl = "┌" if unicode_box else "+"
        tr = "┐" if unicode_box else "+"
        bl = "└" if unicode_box else "+"
        br = "┘" if unicode_box else "+"
        h = "─" if unicode_box else "-"
        v = "│" if unicode_box else "|"

        title = " FORENSIC AUDIT SESSION "
        pad_top = max(0, width - len(title) - 2)
        top_line = f"{tl}{h * 3}{title}{h * (pad_top - 3)}{tr}"

        def _row(label: str, val: str) -> str:
            content = f" {label:<10}: {val}"
            rem = max(0, width - len(content) - 2)
            return f"{v}{content}{' ' * rem}{v}"

        bot_line = f"{bl}{h * (width - 2)}{br}"

        print("", file=self._stream)
        print(_c(top_line, _BOLD + _CYAN, color), file=self._stream)
        print(_row("Job ID", str(job_id)), file=self._stream)
        print(_row("Target", str(filename)), file=self._stream)
        print(_row("Started", f"{time_str} UTC"), file=self._stream)
        print(_row("Pipeline", "YuNet (Face) -> SFace 128-D -> OSINT Search -> Ethereum Sepolia"), file=self._stream)
        print(_c(bot_line, _BOLD + _CYAN, color), file=self._stream)
        print("", file=self._stream)
        self._stream.flush()

    def _render_step(self, event: dict[str, Any]) -> None:
        """Render distinct stage divider (Option A visual richness)."""
        color = _is_color_enabled(self._stream)
        unicode_box = _supports_unicode(self._stream)
        width = _term_width(self._stream)

        self._current_step = event.get("index", self._current_step)
        self._total_steps = event.get("total", self._total_steps)
        self._step_title = str(event.get("title", ""))

        h = "─" if unicode_box else "-"
        title = f" [STAGE {self._current_step}/{self._total_steps}] {self._step_title.upper()} "
        rem = max(0, width - len(title) - 3)
        divider = f"{h * 2}{title}{h * rem}"

        print("", file=self._stream)
        print(_c(divider, _BOLD + _BRIGHT_CYAN, color), file=self._stream)
        self._stream.flush()

    def _render_log(self, event: dict[str, Any]) -> None:
        """Render structured event row (Option B discipline)."""
        color = _is_color_enabled(self._stream)
        time_str = event.get("time") or datetime.datetime.now().strftime("%H:%M:%S")
        job_id = _short_id(event.get("job_id") or self._job_id)
        cat = self._normalize_category(event.get("category", "SYSTEM"))
        level = (event.get("level") or "info").lower()
        msg = event.get("message") or ""

        prefix = self._format_prefix(time_str, job_id, cat, color)
        badge = self._format_badge(level, color)

        print(f"{prefix} {badge} {msg}", file=self._stream)
        self._stream.flush()

    def _render_kv(self, event: dict[str, Any]) -> None:
        """Render structured key-value line."""
        color = _is_color_enabled(self._stream)
        time_str = event.get("time") or datetime.datetime.now().strftime("%H:%M:%S")
        job_id = _short_id(event.get("job_id") or self._job_id)
        cat = self._normalize_category(event.get("category", "SYSTEM"))
        key = str(event.get("key", "")).strip()
        val = str(event.get("value", ""))

        prefix = self._format_prefix(time_str, job_id, cat, color)
        label = _c(f"{key}:", _DIM, color)
        print(f"{prefix}      {label} {val}", file=self._stream)
        self._stream.flush()

    def _render_milestone(self, event: dict[str, Any]) -> None:
        """Render real intermediate milestones without fabrication."""
        color = _is_color_enabled(self._stream)
        time_str = event.get("time") or datetime.datetime.now().strftime("%H:%M:%S")
        job_id = _short_id(event.get("job_id") or self._job_id)
        kind = event.get("kind", "")
        p = event.get("payload") or {}

        if kind == "faces_detected":
            count = p.get("count", 0)
            faces = p.get("faces") or []
            target_idx = p.get("target_index", 0)
            prefix = self._format_prefix(time_str, job_id, "FACE", color)
            badge = self._format_badge("ok", color)
            
            conf_str = ""
            bbox_str = ""
            if faces and 0 <= target_idx < len(faces):
                tf = faces[target_idx]
                conf = tf.get("confidence")
                if conf is not None:
                    conf_str = f" (target confidence: {conf * 100:.1f}%)"
                bbox_str = f"x={tf.get('x')}, y={tf.get('y')}, w={tf.get('width')}, h={tf.get('height')}"

            print(f"{prefix} {badge} {count} face(s) detected{conf_str}", file=self._stream)
            if bbox_str:
                label = _c("Target bbox:", _DIM, color)
                print(f"{prefix}      {label} [{bbox_str}]", file=self._stream)

        elif kind == "search_results":
            provider = p.get("provider", "search")
            count = p.get("result_count", 0)
            prefix = self._format_prefix(time_str, job_id, "SEARCH", color)
            badge = self._format_badge("ok", color)
            print(f"{prefix} {badge} {count} candidate(s) discovered via {provider}", file=self._stream)

        elif kind == "source_validated":
            rank = p.get("rank", "?")
            src = p.get("source") or "web"
            sim = p.get("similarity")
            sim_str = f"{sim:.4f}" if isinstance(sim, (int, float)) else str(sim)
            prefix = self._format_prefix(time_str, job_id, "SOURCE", color)
            badge = self._format_badge("ok", color)
            print(f"{prefix} {badge} Candidate #{rank} ({src}) verified: similarity {sim_str}", file=self._stream)

        elif kind == "candidate_matched":
            verdict = p.get("verdict") or "MATCH"
            sim = p.get("similarity")
            sim_str = f"{sim:.4f}" if isinstance(sim, (int, float)) else str(sim)
            thr = p.get("threshold", 0.363)
            src_url = p.get("page_url") or p.get("image_url_used") or ""
            prefix = self._format_prefix(time_str, job_id, "SOURCE", color)
            badge = self._format_badge("ok", color)
            print(f"{prefix} {badge} Primary Match: verdict={verdict} (sim: {sim_str}, threshold: {thr})", file=self._stream)
            if src_url:
                label = _c("Source URL:", _DIM, color)
                print(f"{prefix}      {label} {src_url}", file=self._stream)

        elif kind == "record_hashed":
            rec_hash = p.get("record_hash") or ""
            if rec_hash:
                prefix = self._format_prefix(time_str, job_id, "CHAIN", color)
                label = _c("Record SHA-256:", _DIM, color)
                print(f"{prefix}      {label} {rec_hash}", file=self._stream)

        elif kind == "chain_confirmed":
            tx_hash = p.get("tx_hash")
            block = p.get("block")
            gas = p.get("gas_used")
            explorer = p.get("explorer_url")
            idempotent = p.get("idempotent", False)
            network = p.get("network") or "Sepolia"

            prefix = self._format_prefix(time_str, job_id, "CHAIN", color)
            badge = self._format_badge("ok", color)

            if idempotent:
                ts = p.get("block_timestamp", "recorded")
                print(f"{prefix} {badge} Idempotent anchor: already committed at block timestamp {ts}", file=self._stream)
            else:
                print(f"{prefix} {badge} On-chain anchor confirmed on {network} (block #{block})", file=self._stream)
                if tx_hash:
                    label = _c("Tx Hash:", _DIM, color)
                    print(f"{prefix}      {label} {tx_hash}", file=self._stream)
                if gas:
                    label = _c("Gas Used:", _DIM, color)
                    print(f"{prefix}      {label} {gas:,}", file=self._stream)
                if explorer:
                    label = _c("Explorer:", _DIM, color)
                    print(f"{prefix}      {label} {explorer}", file=self._stream)

        elif kind == "integrity":
            match = p.get("match", False)
            local = p.get("local_hash") or ""
            on_chain = p.get("on_chain_hash") or ""
            prefix = self._format_prefix(time_str, job_id, "CHAIN", color)
            badge = self._format_badge("ok" if match else "fail", color)
            status_text = "VERIFIED (Local SHA-256 == On-chain SHA-256)" if match else "INTEGRITY MISMATCH"
            print(f"{prefix} {badge} State Check: {status_text}", file=self._stream)

        self._stream.flush()

    def _render_section(self, event: dict[str, Any]) -> None:
        """Render a secondary section header if non-empty."""
        title = event.get("title") or ""
        if title:
            color = _is_color_enabled(self._stream)
            print(f"  {_c(f':: {title}', _BOLD + _CYAN, color)}", file=self._stream)
            self._stream.flush()

    def _render_verdict(self, event: dict[str, Any]) -> None:
        """Render headline verdict banner (Option A visual richness)."""
        color = _is_color_enabled(self._stream)
        unicode_box = _supports_unicode(self._stream)
        width = _term_width(self._stream)

        label = str(event.get("label", "VERIFICATION VERDICT")).upper()
        passed = bool(event.get("passed", False))
        mark = "PASS" if passed else "FAIL"
        mark_color = _BOLD + (_BRIGHT_GREEN if passed else _BRIGHT_RED)

        d_h = "═" if unicode_box else "="
        rule_line = d_h * width
        content = f"  {label}: {_c(mark, mark_color, color)}"

        print("", file=self._stream)
        print(_c(rule_line, _BOLD, color), file=self._stream)
        print(content, file=self._stream)
        print(_c(rule_line, _BOLD, color), file=self._stream)
        print("", file=self._stream)
        self._stream.flush()

    def _render_result(self, event: dict[str, Any]) -> None:
        """Render final forensic verification summary evidence card."""
        color = _is_color_enabled(self._stream)
        unicode_box = _supports_unicode(self._stream)
        width = _term_width(self._stream)

        res = event.get("result") or {}
        art = res.get("artifact") or {}
        rec = art.get("record") or {}
        chain = art.get("blockchain") or {}

        job_id = event.get("job_id") or self._job_id or "N/A"
        filename = rec.get("input", {}).get("filename") or self._filename or "N/A"
        input_sha256 = rec.get("input", {}).get("sha256") or "N/A"
        cand = rec.get("candidate") or {}
        page_url = cand.get("page_url") or "N/A"
        sim = cand.get("similarity")
        thr = cand.get("threshold")
        verdict = cand.get("verdict") or "N/A"
        rec_hash = res.get("record_hash") or art.get("record_hash") or "N/A"
        integrity_match = res.get("integrity_match")
        sources_count = len(res.get("validated_sources") or [])

        # Chain details (real data only)
        network = chain.get("network") or "Sepolia Testnet"
        contract = chain.get("contract_address") or "N/A"
        tx_hash = chain.get("transaction_hash") or ("(Idempotent anchor)" if chain.get("idempotent") else "N/A")
        block_num = chain.get("block_number") or chain.get("block_timestamp")
        gas = chain.get("gas_used")
        art_path = res.get("artifact_path") or "N/A"

        tl = "┌" if unicode_box else "+"
        tr = "┐" if unicode_box else "+"
        bl = "└" if unicode_box else "+"
        br = "┘" if unicode_box else "+"
        h = "─" if unicode_box else "-"
        v = "│" if unicode_box else "|"

        title = " FORENSIC VERIFICATION EVIDENCE "
        pad_top = max(0, width - len(title) - 2)
        top_line = f"{tl}{h * 3}{title}{h * (pad_top - 3)}{tr}"

        def _row(label: str, val: str) -> str:
            # truncate overly long strings to fit within box
            max_val_len = width - len(label) - 6
            display_val = val if len(val) <= max_val_len else val[:max_val_len - 3] + "..."
            content = f" {label:<16}: {display_val}"
            rem = max(0, width - len(content) - 2)
            return f"{v}{content}{' ' * rem}{v}"

        bot_line = f"{bl}{h * (width - 2)}{br}"

        if isinstance(sim, (int, float)):
            sim_str = f"Cosine Sim {sim:.4f}" + (f" (Threshold: {thr})" if thr is not None else "")
        else:
            sim_str = "N/A"

        block_str = f"#{block_num}" + (f" (Gas: {gas:,})" if gas else "") if block_num else "N/A"

        print(_c(top_line, _BOLD + _GREEN, color), file=self._stream)
        print(_row("Job ID", str(job_id)), file=self._stream)
        print(_row("Target Image", str(filename)), file=self._stream)
        print(_row("Image SHA-256", str(input_sha256)), file=self._stream)
        print(_row("Primary Match", str(page_url)), file=self._stream)
        print(_row("Match Metric", sim_str), file=self._stream)
        print(_row("Verdict", str(verdict)), file=self._stream)
        if sources_count > 0:
            print(_row("Verified Sources", f"{sources_count} sources corroborated"), file=self._stream)
        print(_row("Record Hash", str(rec_hash)), file=self._stream)
        print(_row("Blockchain", f"{network}"), file=self._stream)
        print(_row("Contract", str(contract)), file=self._stream)
        print(_row("Tx Hash", str(tx_hash)), file=self._stream)
        print(_row("Block/Ref", block_str), file=self._stream)
        if integrity_match is not None:
            anchor_status = "CONFIRMED & IMMUTABLE" if integrity_match else "INTEGRITY CHECK FAILED"
            print(_row("On-Chain Anchor", anchor_status), file=self._stream)
        print(_row("Artifact Path", str(art_path)), file=self._stream)
        print(_c(bot_line, _BOLD + _GREEN, color), file=self._stream)
        print("", file=self._stream)
        self._stream.flush()

    def _render_error(self, event: dict[str, Any]) -> None:
        """Render visually distinct error card."""
        color = _is_color_enabled(self._stream)
        unicode_box = _supports_unicode(self._stream)
        width = _term_width(self._stream)

        job_id = event.get("job_id") or self._job_id or "—"
        kind = event.get("kind") or "PIPELINE ERROR"
        msg = event.get("message") or "Unknown error occurred"
        hint = event.get("hint")

        tl = "┌" if unicode_box else "+"
        tr = "┐" if unicode_box else "+"
        bl = "└" if unicode_box else "+"
        br = "┘" if unicode_box else "+"
        h = "─" if unicode_box else "-"
        v = "│" if unicode_box else "|"

        title = f" AUDIT FAILURE: {kind} "
        pad_top = max(0, width - len(title) - 2)
        top_line = f"{tl}{h * 3}{title}{h * (pad_top - 3)}{tr}"

        def _row(label: str, val: str) -> str:
            max_val_len = width - len(label) - 6
            display_val = val if len(val) <= max_val_len else val[:max_val_len - 3] + "..."
            content = f" {label:<10}: {display_val}"
            rem = max(0, width - len(content) - 2)
            return f"{v}{content}{' ' * rem}{v}"

        bot_line = f"{bl}{h * (width - 2)}{br}"

        stage_label = f"[STAGE {self._current_step}/{self._total_steps}] {self._step_title}" if self._current_step else "Initialization"

        print("", file=self._stream)
        print(_c(top_line, _BOLD + _RED, color), file=self._stream)
        print(_row("Job ID", str(job_id)), file=self._stream)
        print(_row("Stage", str(stage_label)), file=self._stream)
        print(_row("Error", str(msg)), file=self._stream)
        if hint:
            print(_row("Hint", str(hint)), file=self._stream)
        print(_c(bot_line, _BOLD + _RED, color), file=self._stream)
        print("", file=self._stream)
        self._stream.flush()

    # -----------------------------------------------------------------------
    # Formatting Helpers
    # -----------------------------------------------------------------------

    def _normalize_category(self, cat: str) -> str:
        """Map raw category to normalized tag."""
        cat_upper = (cat or "SYSTEM").upper()
        if "TRANSACTION" in cat_upper or "BLOCKCHAIN" in cat_upper or "CHAIN" in cat_upper:
            return "CHAIN"
        if "SEARCH" in cat_upper:
            return "SEARCH"
        if "SOURCE" in cat_upper:
            return "SOURCE"
        if "FACE" in cat_upper or "IMAGE" in cat_upper:
            return "IMAGE"
        if "FAIL" in cat_upper or "ERR" in cat_upper:
            return "ERROR"
        return "SYSTEM"

    def _format_prefix(self, time_str: str, job_id: str, cat: str, color: bool) -> str:
        """Format timestamp, job ID, and category with consistent column alignment."""
        t_col = _c(f"[{time_str}]", _DIM, color)
        j_col = _c(f"[job:{job_id:<8}]", _BOLD + _WHITE, color)

        cat_codes = {
            "IMAGE": _CYAN,
            "SEARCH": _MAGENTA,
            "SOURCE": _YELLOW,
            "CHAIN": _BRIGHT_CYAN,
            "SYSTEM": _DIM,
            "ERROR": _BRIGHT_RED,
        }
        code = cat_codes.get(cat, _DIM)
        c_col = _c(f"[{cat:<6}]", code, color)

        return f"{t_col} {j_col} {c_col}"

    def _format_badge(self, level: str, color: bool) -> str:
        """Format fixed-width status badge."""
        lvl = level.lower()
        if lvl in ("ok", "pass"):
            return _c(" OK ", _BOLD + _GREEN, color)
        if lvl in ("warn", "warning"):
            return _c("WARN", _BOLD + _YELLOW, color)
        if lvl in ("fail", "error"):
            return _c("FAIL", _BOLD + _RED, color)
        return _c(" .. ", _DIM, color)
