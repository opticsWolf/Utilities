# -*- coding: utf-8 -*-
"""Background worker that runs the scan off the GUI thread."""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .analysis import build_module_map
from .external_tools import run_external_analysis, run_ruff_fix
from .models import LintResult, ScanOptions


class ScanWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(list, dict)
    error    = Signal(str)

    def __init__(self, files: list, opts: ScanOptions):
        super().__init__()
        self.files = files
        self.opts  = opts

    def run(self):
        try:
            total = len(self.files)
            maps  = []
            stats = {"modules": 0, "classes": 0, "functions": 0,
                     "issues": 0, "errors": 0}

            # 1. External tools first (one subprocess round)
            self.progress.emit(0, total, "Running external analysis…")
            ext = run_external_analysis(self.files, self.opts)

            # 2. Per-file AST analysis
            for i, fp in enumerate(self.files):
                self.progress.emit(i + 1, total, Path(fp).name)
                try:
                    m = build_module_map(fp, self.opts)
                    abs_fp = str(Path(fp).resolve())
                    if abs_fp in ext:
                        m.ruff_issues = ext[abs_fp]["ruff"]
                        m.mypy_issues = ext[abs_fp]["mypy"]
                        m.mi_score    = ext[abs_fp]["mi_score"]
                        m.mi_rank     = ext[abs_fp]["mi_rank"]
                    maps.append(m)
                    stats["modules"]   += 1
                    stats["classes"]   += len(m.classes)
                    stats["functions"] += len(m.functions) + sum(len(c.methods) for c in m.classes)
                    stats["issues"]    += (
                        len(m.anti_patterns) + len(m.legacy_patterns)
                        + len(m.ruff_issues) + len(m.mypy_issues)
                    )
                except SyntaxError:
                    stats["errors"] += 1

            # Sort worst MI first (files with no MI score go last)
            maps.sort(key=lambda x: x.mi_score if x.mi_score is not None else 999)
            self.finished.emit(maps, stats)

        except Exception as e:
            self.error.emit(str(e))


class LintWorker(QObject):
    """
    Runs `run_ruff_fix()` off the GUI thread.

    Emits the same `progress` shape as ScanWorker so the existing progress
    bar and label can be reused.
    """
    progress = Signal(int, int, str)
    finished = Signal(LintResult)
    error    = Signal(str)

    def __init__(self, files: list, opts: ScanOptions):
        super().__init__()
        self.files = files
        self.opts  = opts

    def run(self):
        try:
            def _cb(cur, tot, label):
                self.progress.emit(cur, tot, label)
            self.progress.emit(0, 1, "Starting linter…")
            result = run_ruff_fix(self.files, self.opts, progress_cb=_cb)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
