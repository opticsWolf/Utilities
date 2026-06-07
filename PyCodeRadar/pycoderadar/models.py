# -*- coding: utf-8 -*-
"""Plain data classes for AST findings, external-tool issues, and scan options."""

from dataclasses import dataclass, field
from typing import Optional

from .constants import HAS_RUFF, HAS_RADON, HAS_MYPY


# ── AST findings ──────────────────────────────────────────────────────────────

@dataclass
class ImportInfo:
    raw: str
    local_name: str
    lineno: int
    from_module: Optional[str] = None
    is_wildcard: bool = False


@dataclass
class FunctionInfo:
    name: str
    lineno: int
    args: list
    decorators: list
    docstring: Optional[str]
    calls: list                = field(default_factory=list)
    is_async: bool             = False
    line_end: Optional[int]    = None
    num_lines: int             = 0
    complexity: int            = 1
    annotations: dict          = field(default_factory=dict)
    return_type: Optional[str] = None
    exceptions_raised: list    = field(default_factory=list)
    num_args: int              = 0
    # Wrapper detection
    is_wrapper: bool              = False
    wrapper_target: Optional[str] = None


@dataclass
class ClassInfo:
    name: str
    lineno: int
    bases: list
    docstring: Optional[str]
    methods: list           = field(default_factory=list)
    line_end: Optional[int] = None
    num_lines: int          = 0


@dataclass
class AntiPattern:
    category: str
    message: str
    lineno: int


# ── External-tool findings ────────────────────────────────────────────────────

@dataclass
class RuffIssue:
    code: str
    message: str
    row: int


@dataclass
class MypyIssue:
    line: int
    severity: str
    message: str


# ── Linter / fixer result ─────────────────────────────────────────────────────

@dataclass
class LintResult:
    """Outcome of an active lint/fix run."""
    applied: bool                          # False for preview-only runs
    files_processed: int = 0
    files_changed:   int = 0               # files actually rewritten (apply mode)
    fixes_applied:   int = 0               # count parsed from ruff output
    format_changed:  int = 0               # files reformatted
    diff: str          = ""                # full diff text (preview mode)
    summary: str       = ""                # one-line human summary
    errors: list       = field(default_factory=list)


# ── Aggregate per-module result ───────────────────────────────────────────────

@dataclass
class ModuleMap:
    path: str
    docstring: Optional[str]
    imports: list
    functions: list
    classes: list
    globals: list
    anti_patterns: list     = field(default_factory=list)
    legacy_patterns: list   = field(default_factory=list)
    todos: list             = field(default_factory=list)
    import_categories: dict = field(default_factory=dict)
    # External tool results
    ruff_issues: list         = field(default_factory=list)
    mypy_issues: list         = field(default_factory=list)
    mi_score: Optional[float] = None
    mi_rank:  Optional[str]   = None


# ── Scan configuration ────────────────────────────────────────────────────────

@dataclass
class ScanOptions:
    """All knobs that drive a scan. Persisted verbatim in the config file."""

    # ── Tracking ──────────────────────────────────────────────────────────────
    include_calls:            bool = True
    track_line_counts:        bool = True
    track_complexity:         bool = True
    track_return_types:       bool = True
    track_annotations:        bool = False
    track_exceptions:         bool = False
    track_import_categories:  bool = False
    track_todos:              bool = True
    track_wrappers:           bool = True

    # ── Anti-patterns ─────────────────────────────────────────────────────────
    detect_wildcard:          bool = True
    detect_duplicate_imports: bool = True
    detect_unused_imports:    bool = False
    detect_mutable_defaults:  bool = True
    detect_bare_except:       bool = True
    detect_long_functions:    bool = True
    detect_too_many_args:     bool = True
    detect_god_classes:       bool = True
    detect_print:             bool = False
    detect_exec_eval:         bool = True

    # ── Legacy code (AST-based) ───────────────────────────────────────────────
    detect_percent_format:    bool = False   # "hello %s" % name
    detect_super_args:        bool = False   # super(Cls, self) → super()
    detect_type_comments:     bool = False   # # type: int  (PEP 484 comments)

    # ── External tools ────────────────────────────────────────────────────────
    run_ruff_analysis:        bool = HAS_RUFF
    run_radon_analysis:       bool = HAS_RADON
    run_mypy_analysis:        bool = HAS_MYPY

    # ── Mypy — strictness ─────────────────────────────────────────────────────
    # When mypy_strict=True, --strict is passed and individual flags are implied.
    mypy_strict:                      bool = False
    mypy_disallow_untyped_defs:       bool = False
    mypy_disallow_incomplete_defs:    bool = False
    mypy_check_untyped_defs:          bool = False
    mypy_disallow_any_generics:       bool = False
    mypy_warn_return_any:             bool = False
    mypy_warn_unused_ignores:         bool = False
    mypy_no_implicit_optional:        bool = True
    mypy_strict_equality:             bool = False
    mypy_disallow_untyped_decorators: bool = False

    # ── Mypy — ignores ────────────────────────────────────────────────────────
    mypy_ignore_missing_imports: bool = True
    mypy_disable_error_codes:    str  = ""

    # ── Mypy — severity filter ────────────────────────────────────────────────
    mypy_show_errors:   bool = True
    mypy_show_warnings: bool = True
    mypy_show_notes:    bool = False

    # ── Thresholds ────────────────────────────────────────────────────────────
    long_function_threshold: int = 50
    max_args:                int = 5
    god_class_threshold:     int = 15

    # ── Linter / fixer (active code modification) ─────────────────────────────
    # All default to False (or to a safe default) — fixing files is destructive
    # and must be opt-in. Preview mode is on by default so the very first click
    # of the Fix button shows a diff instead of writing.
    lint_apply_fixes:  bool = False    # ruff check --fix
    lint_unsafe_fixes: bool = False    # add --unsafe-fixes
    lint_format_code:  bool = False    # run ruff format
    lint_preview_only: bool = True     # use --diff, do not write
