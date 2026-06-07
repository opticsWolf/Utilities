# -*- coding: utf-8 -*-
"""External tool integration: Ruff, Radon (MI), and Mypy."""

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .constants import HAS_RUFF, HAS_RADON, HAS_MYPY
from .models import LintResult, MypyIssue, RuffIssue, ScanOptions


# Maps ScanOptions attr → mypy CLI flag (used when not in --strict mode).
MYPY_FLAG_MAP: List[tuple] = [
    ("mypy_disallow_untyped_defs",       "--disallow-untyped-defs"),
    ("mypy_disallow_incomplete_defs",    "--disallow-incomplete-defs"),
    ("mypy_check_untyped_defs",          "--check-untyped-defs"),
    ("mypy_disallow_any_generics",       "--disallow-any-generics"),
    ("mypy_warn_return_any",             "--warn-return-any"),
    ("mypy_warn_unused_ignores",         "--warn-unused-ignores"),
    ("mypy_no_implicit_optional",        "--no-implicit-optional"),
    ("mypy_strict_equality",             "--strict-equality"),
    ("mypy_disallow_untyped_decorators", "--disallow-untyped-decorators"),
]


def build_mypy_cmd(opts: ScanOptions) -> List[str]:
    """Assemble the mypy CLI command from ScanOptions."""
    cmd = ["mypy", "--no-error-summary", "--hide-error-context", "--show-error-codes"]
    if opts.mypy_strict:
        cmd.append("--strict")
    else:
        for attr, flag in MYPY_FLAG_MAP:
            if getattr(opts, attr):
                cmd.append(flag)
    if opts.mypy_ignore_missing_imports:
        cmd.append("--ignore-missing-imports")
    for code in (c.strip() for c in opts.mypy_disable_error_codes.split(",") if c.strip()):
        cmd += ["--disable-error-code", code]
    return cmd


def run_external_analysis(files: List[str], opts: ScanOptions) -> Dict[str, dict]:
    """Run Ruff, Radon, and Mypy on the selected files in 50-file chunks."""
    results    = defaultdict(lambda: {"ruff": [], "mi_score": None, "mi_rank": None, "mypy": []})
    mypy_re    = re.compile(r'^(.*?):(\d+):(?:\d+:)?\s*(error|warning|note):\s*(.*)$')
    chunk_size = 50
    chunks     = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]

    for chunk in chunks:
        # ── Ruff ──────────────────────────────────────────────────────────────
        if opts.run_ruff_analysis and HAS_RUFF:
            cmd = ["ruff", "check", "--output-format=json",
                   "--select=E,F,B,UP,C90,PLR,PLC,RUF"] + chunk
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.stdout.strip():
                    for item in json.loads(res.stdout):
                        fp = str(Path(item.get("filename", "")).resolve())
                        results[fp]["ruff"].append(RuffIssue(
                            code=item.get("code", ""),
                            message=item.get("message", ""),
                            row=item.get("location", {}).get("row", 0),
                        ))
            except Exception as e:
                print(f"[PyCodeRadar] Ruff failed: {e}")

        # ── Radon MI ──────────────────────────────────────────────────────────
        if opts.run_radon_analysis and HAS_RADON:
            try:
                res = subprocess.run(
                    ["radon", "mi", "-s", "-j"] + chunk,
                    capture_output=True, text=True, check=False,
                )
                if res.stdout.strip():
                    for fp, data in json.loads(res.stdout).items():
                        abs_fp = str(Path(fp).resolve())
                        results[abs_fp]["mi_score"] = data.get("mi")
                        results[abs_fp]["mi_rank"]  = data.get("rank")
            except Exception as e:
                print(f"[PyCodeRadar] Radon failed: {e}")

        # ── Mypy ──────────────────────────────────────────────────────────────
        if opts.run_mypy_analysis and HAS_MYPY:
            allowed_sevs: set = set()
            if opts.mypy_show_errors:   allowed_sevs.add("ERROR")
            if opts.mypy_show_warnings: allowed_sevs.add("WARNING")
            if opts.mypy_show_notes:    allowed_sevs.add("NOTE")
            try:
                res = subprocess.run(
                    build_mypy_cmd(opts) + chunk,
                    capture_output=True, text=True, check=False,
                )
                for line in res.stdout.splitlines():
                    if m := mypy_re.match(line):
                        sev = m.group(3).upper()
                        if sev not in allowed_sevs:
                            continue
                        abs_fp = str(Path(m.group(1)).resolve())
                        results[abs_fp]["mypy"].append(MypyIssue(
                            line=int(m.group(2)),
                            severity=sev,
                            message=m.group(4),
                        ))
            except Exception as e:
                print(f"[PyCodeRadar] Mypy failed: {e}")

    return results


# ==========================================
# Active linting / fixing
# ==========================================

# Ruff prints summaries like:
#   "Found 6 errors (6 fixed, 0 remaining)."   (apply mode)
#   "Would fix 6 errors."                       (preview / --diff mode)
#   "Fixed 6 errors."                           (older versions / some cases)
_RUFF_FIXED_RE = re.compile(
    r"(?:\((\d+)\s+fixed,\s*\d+\s+remaining\)"   # "(6 fixed, 0 remaining)"
    r"|(?:Would fix|Fixed)\s+(\d+)\s+error)",     # "Would fix 6 errors." / "Fixed 6 errors."
    re.IGNORECASE,
)
# Parses ruff format's "N file(s) reformatted" / "Would reformat N file(s)" lines.
_RUFF_FORMAT_RE = re.compile(r"(\d+)\s+file[s]?\s+(?:reformatted|would be reformatted)",
                             re.IGNORECASE)


def _hash_files(files: list) -> dict:
    """Map filepath → mtime (used to detect which files were rewritten)."""
    out: dict = {}
    for fp in files:
        try:
            out[fp] = Path(fp).stat().st_mtime_ns
        except OSError:
            pass
    return out


def run_ruff_fix(files: List[str], opts: ScanOptions,
                 progress_cb=None) -> LintResult:
    """
    Apply (or preview) Ruff auto-fixes and/or formatting on the selected files.

    Modes:
        opts.lint_preview_only=True   →  --diff: collect diff, do not write
        opts.lint_preview_only=False  →  write files in-place

    What it runs (depending on toggles):
        opts.lint_apply_fixes  →  ruff check --fix [--unsafe-fixes]
        opts.lint_format_code  →  ruff format

    `progress_cb`, if given, is called as progress_cb(current, total, label).

    Returns a LintResult with diff / summary / counts populated.
    """
    result = LintResult(applied=not opts.lint_preview_only,
                        files_processed=len(files))

    if not HAS_RUFF:
        result.errors.append("Ruff is not installed — cannot lint.")
        result.summary = "Ruff not found."
        return result

    if not opts.lint_apply_fixes and not opts.lint_format_code:
        result.errors.append(
            "Neither 'apply fixes' nor 'format code' is enabled — nothing to do."
        )
        result.summary = "No lint actions selected."
        return result

    if not files:
        result.summary = "No files to process."
        return result

    preview = opts.lint_preview_only
    chunk_size = 50
    chunks = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]

    diff_parts: list = []
    pre_state  = _hash_files(files) if not preview else {}
    total_steps = len(chunks) * (
        (1 if opts.lint_apply_fixes else 0) + (1 if opts.lint_format_code else 0)
    )
    step = 0

    for ci, chunk in enumerate(chunks):
        # ── Ruff check --fix ──────────────────────────────────────────────────
        if opts.lint_apply_fixes:
            step += 1
            if progress_cb:
                progress_cb(step, total_steps,
                            f"ruff check --fix  (chunk {ci + 1}/{len(chunks)})")
            cmd = ["ruff", "check"]
            if preview:
                cmd += ["--diff"]
            else:
                cmd += ["--fix"]
            if opts.lint_unsafe_fixes:
                cmd += ["--unsafe-fixes"]
            cmd += chunk
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if preview:
                    if res.stdout.strip():
                        diff_parts.append(res.stdout)
                    output = (res.stderr or "") + (res.stdout or "")
                    for m in _RUFF_FIXED_RE.finditer(output):
                        result.fixes_applied += int(m.group(1) or m.group(2) or 0)
                else:
                    output = (res.stderr or "") + (res.stdout or "")
                    for m in _RUFF_FIXED_RE.finditer(output):
                        result.fixes_applied += int(m.group(1) or m.group(2) or 0)
            except Exception as e:
                result.errors.append(f"ruff check failed: {e}")

        # ── Ruff format ───────────────────────────────────────────────────────
        if opts.lint_format_code:
            step += 1
            if progress_cb:
                progress_cb(step, total_steps,
                            f"ruff format  (chunk {ci + 1}/{len(chunks)})")
            cmd = ["ruff", "format"]
            if preview:
                cmd += ["--diff"]
            cmd += chunk
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if preview:
                    if res.stdout.strip():
                        diff_parts.append(res.stdout)
                    # In --diff mode ruff writes the count summary to stderr.
                    output = res.stderr or ""
                    for m in _RUFF_FORMAT_RE.finditer(output):
                        result.format_changed += int(m.group(1))
                else:
                    output = (res.stderr or "") + (res.stdout or "")
                    for m in _RUFF_FORMAT_RE.finditer(output):
                        result.format_changed += int(m.group(1))
            except Exception as e:
                result.errors.append(f"ruff format failed: {e}")

    # Tally files actually written (apply mode only) by mtime delta.
    if not preview:
        post_state = _hash_files(files)
        for fp, before in pre_state.items():
            if post_state.get(fp) != before:
                result.files_changed += 1

    result.diff = "\n".join(diff_parts).rstrip()

    # ── Build human summary ───────────────────────────────────────────────────
    bits = []
    if preview:
        bits.append("Preview only — no files were modified.")
        if result.fixes_applied:
            bits.append(f"would fix {result.fixes_applied} issue(s)")
        if result.format_changed:
            bits.append(f"would reformat {result.format_changed} file(s)")
        if not result.diff:
            bits.append("nothing to change")
    else:
        if result.fixes_applied:
            bits.append(f"fixed {result.fixes_applied} issue(s)")
        if result.format_changed:
            bits.append(f"reformatted {result.format_changed} file(s)")
        if result.files_changed:
            bits.append(f"{result.files_changed} file(s) rewritten")
        if not bits:
            bits.append("nothing changed")
    result.summary = "; ".join(bits)
    return result
