# -*- coding: utf-8 -*-
"""
PyCodeRadar: Extended Python Code Map & Refactoring Radar — PySide6 GUI

Copyright (c) 2026 opticsWolf
SPDX-License-Identifier: Apache-2.0

Features
--------
* Full AST metadata: calls, signatures, complexity, annotations, exceptions,
  import categories, TODO markers.
* Wrapper function / method detection — identifies thin delegation / passthrough
  functions so they can be inlined or documented.
* Legacy code pattern detection (AST-based): %-format strings, super() with
  explicit args, PEP 484 type comments.
* Anti-pattern detection: wildcard / duplicate / unused imports, mutable
  default arguments, bare except, long functions, too many args, god classes,
  exec/eval, print leftovers.
* External tool integration (optional): Ruff deep smells, Radon Maintainability
  Index, Mypy static type checking with configurable strictness (strict mode or
  per-flag), ignore-missing-imports, per-code suppression, and severity filter.
* File-tree panel with tristate folder checkboxes and shift-click range select.
"""

# ==========================================
# 1. MODULES & GLOBALS
# ==========================================

import ast
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QProgressBar,
    QFrame, QSplitter, QStatusBar, QComboBox, QCheckBox, QSpinBox,
    QSizePolicy, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
    QScrollArea, QLineEdit,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QPalette

# ── External tool availability ────────────────────────────────────────────────
HAS_RUFF  = shutil.which("ruff")  is not None
HAS_RADON = shutil.which("radon") is not None
HAS_MYPY  = shutil.which("mypy")  is not None

# ── stdlib set (Python 3.10+) ─────────────────────────────────────────────────
try:
    _STDLIB_MODULES = set(sys.stdlib_module_names)
except AttributeError:
    _STDLIB_MODULES = set()

EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", "env", ".git", "node_modules",
                "dist", "build", ".mypy_cache", ".pytest_cache"}


# ==========================================
# 2. DATA CLASSES
# ==========================================

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
    calls: list            = field(default_factory=list)
    is_async: bool         = False
    line_end: Optional[int] = None
    num_lines: int         = 0
    complexity: int        = 1
    annotations: dict      = field(default_factory=dict)
    return_type: Optional[str] = None
    exceptions_raised: list = field(default_factory=list)
    num_args: int          = 0
    # Wrapper detection
    is_wrapper: bool          = False
    wrapper_target: Optional[str] = None


@dataclass
class ClassInfo:
    name: str
    lineno: int
    bases: list
    docstring: Optional[str]
    methods: list          = field(default_factory=list)
    line_end: Optional[int] = None
    num_lines: int         = 0


@dataclass
class AntiPattern:
    category: str
    message: str
    lineno: int


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


@dataclass
class ModuleMap:
    path: str
    docstring: Optional[str]
    imports: list
    functions: list
    classes: list
    globals: list
    anti_patterns: list    = field(default_factory=list)
    legacy_patterns: list  = field(default_factory=list)   # ← separate legacy bucket
    todos: list            = field(default_factory=list)
    import_categories: dict = field(default_factory=dict)
    # External tool results
    ruff_issues: list      = field(default_factory=list)
    mypy_issues: list      = field(default_factory=list)
    mi_score: Optional[float] = None
    mi_rank:  Optional[str]   = None


@dataclass
class ScanOptions:
    # ── Tracking ──────────────────────────────────────────────────────────────
    include_calls:            bool = True
    track_line_counts:        bool = True
    track_complexity:         bool = True
    track_return_types:       bool = True
    track_annotations:        bool = False
    track_exceptions:         bool = False
    track_import_categories:  bool = False
    track_todos:              bool = True
    track_wrappers:           bool = True     # ← wrapper detection
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
    mypy_strict:                    bool = False
    mypy_disallow_untyped_defs:     bool = False  # --disallow-untyped-defs
    mypy_disallow_incomplete_defs:  bool = False  # --disallow-incomplete-defs
    mypy_check_untyped_defs:        bool = False  # --check-untyped-defs
    mypy_disallow_any_generics:     bool = False  # --disallow-any-generics
    mypy_warn_return_any:           bool = False  # --warn-return-any
    mypy_warn_unused_ignores:       bool = False  # --warn-unused-ignores
    mypy_no_implicit_optional:      bool = True   # --no-implicit-optional
    mypy_strict_equality:           bool = False  # --strict-equality
    mypy_disallow_untyped_decorators: bool = False  # --disallow-untyped-decorators
    # ── Mypy — ignores ────────────────────────────────────────────────────────
    mypy_ignore_missing_imports:    bool = True   # --ignore-missing-imports
    mypy_disable_error_codes:       str  = ""     # comma-sep, e.g. "import-untyped,no-untyped-def"
    # ── Mypy — severity filter ────────────────────────────────────────────────
    mypy_show_errors:   bool = True
    mypy_show_warnings: bool = True
    mypy_show_notes:    bool = False
    # ── Thresholds ────────────────────────────────────────────────────────────
    long_function_threshold:  int  = 50
    max_args:                 int  = 5
    god_class_threshold:      int  = 15


# ==========================================
# 3. BACKEND: HELPERS
# ==========================================

def _categorize_imports(imports: list) -> dict:
    stdlib, third, local = [], [], []
    for imp in imports:
        if imp.from_module and imp.from_module.startswith('.'):
            local.append(imp.raw); continue
        top = (imp.from_module or imp.local_name or imp.raw).split('.')[0].split(' ')[0]
        if not top:              local.append(imp.raw)
        elif top in _STDLIB_MODULES: stdlib.append(imp.raw)
        else:                    third.append(imp.raw)
    return {"stdlib": stdlib, "third_party": third, "local": local}


_COMPLEXITY_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While,
    ast.IfExp, ast.Assert,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)


def _cyclomatic_complexity(node: ast.AST) -> int:
    score = 1
    for sub in ast.walk(node):
        if isinstance(sub, _COMPLEXITY_NODES):
            score += 1
        elif isinstance(sub, ast.BoolOp):
            score += max(0, len(sub.values) - 1)
        elif isinstance(sub, ast.Try):
            score += len(sub.handlers)
        elif hasattr(ast, "Match") and isinstance(sub, ast.Match):
            score += len(sub.cases)
        if isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in sub.generators:
                score += len(gen.ifs)
    return score


def _is_mutable_default(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.List): return "list"
    if isinstance(node, ast.Dict): return "dict"
    if isinstance(node, ast.Set):  return "set"
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in {"list", "dict", "set"} and not node.args and not node.keywords:
            return name + "()"
    return None


def _detect_wrapper(node: ast.AST) -> tuple:
    """
    Heuristic wrapper detector.

    A function is classified as a wrapper when its effective body (excluding a
    leading docstring) contains <= 4 statements and exactly one Call node in
    total.  Returns (is_wrapper: bool, target: str | None).
    """
    body = node.body  # type: ignore[attr-defined]
    # Skip leading docstring
    start = 1 if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ) else 0
    effective = body[start:]

    if not effective or len(effective) > 4:
        return False, None

    calls = [n for stmt in effective for n in ast.walk(stmt) if isinstance(n, ast.Call)]
    if len(calls) != 1:
        return False, None

    try:
        target = ast.unparse(calls[0].func)
    except Exception:
        target = "?"
    return True, target


# ==========================================
# 4. BACKEND: AST PARSER
# ==========================================

class CodeMapVisitor(ast.NodeVisitor):
    def __init__(self, opts: ScanOptions):
        self.opts = opts
        self.imports:         list = []
        self.functions:       list = []
        self.classes:         list = []
        self.globals:         list = []
        self.anti_patterns:   list = []
        self.legacy_patterns: list = []
        self._current_class: Optional[ClassInfo] = None
        self._func_depth: int = 0

    # ── Imports ───────────────────────────────────────────────────────────────

    def visit_Import(self, node):
        for alias in node.names:
            local = alias.asname or alias.name.split('.')[0]
            raw   = f"{alias.name} as {alias.asname}" if alias.asname else alias.name
            self.imports.append(ImportInfo(raw=raw, local_name=local, lineno=node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        src = f"{'.' * (node.level or 0)}{node.module or ''}"
        for alias in node.names:
            if alias.name == "*":
                self.imports.append(ImportInfo(
                    raw=f"from {src} import *", local_name="*",
                    lineno=node.lineno, from_module=src, is_wildcard=True,
                ))
                if self.opts.detect_wildcard:
                    self.anti_patterns.append(AntiPattern(
                        "wildcard-import", f"wildcard import: from {src} import *", node.lineno,
                    ))
            else:
                local     = alias.asname or alias.name
                name_part = f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                self.imports.append(ImportInfo(
                    raw=f"from {src} import {name_part}",
                    local_name=local, lineno=node.lineno, from_module=src,
                ))
        self.generic_visit(node)

    # ── Classes ───────────────────────────────────────────────────────────────

    def visit_ClassDef(self, node):
        line_end = getattr(node, "end_lineno", None)
        cls = ClassInfo(
            name=node.name, lineno=node.lineno,
            bases=[ast.unparse(b) for b in node.bases],
            docstring=ast.get_docstring(node),
            line_end=line_end,
            num_lines=(line_end - node.lineno + 1) if line_end else 0,
        )
        prev = self._current_class
        self._current_class = cls
        self.generic_visit(node)
        self._current_class = prev
        self.classes.append(cls)

        if self.opts.detect_god_classes and len(cls.methods) >= self.opts.god_class_threshold:
            self.anti_patterns.append(AntiPattern(
                "god-class",
                f"god class '{cls.name}' with {len(cls.methods)} methods "
                f"(>= {self.opts.god_class_threshold})",
                cls.lineno,
            ))

    # ── Functions ─────────────────────────────────────────────────────────────

    def _visit_func(self, node):
        opts    = self.opts
        line_end = getattr(node, "end_lineno", None)
        num_lines = (line_end - node.lineno + 1) if line_end else 0
        arg_names = [a.arg for a in node.args.args]

        # Annotations
        annotations: dict = {}
        if opts.track_annotations:
            for a in node.args.args:
                if a.annotation is not None:
                    try:
                        annotations[a.arg] = ast.unparse(a.annotation)
                    except Exception:
                        pass

        # Return type
        return_type = None
        if opts.track_return_types and node.returns:
            try:
                return_type = ast.unparse(node.returns)
            except Exception:
                pass

        # Calls (deduplicated, in order of first occurrence)
        calls: list = []
        if opts.include_calls:
            seen: set = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and hasattr(n, "func"):
                    try:
                        s = ast.unparse(n.func)
                    except Exception:
                        continue
                    if s not in seen:
                        seen.add(s); calls.append(s)

        # Exceptions raised
        exceptions_raised: list = []
        if opts.track_exceptions:
            seen = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Raise) and n.exc is not None:
                    exc = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
                    try:
                        s = ast.unparse(exc)
                    except Exception:
                        continue
                    if s not in seen:
                        seen.add(s); exceptions_raised.append(s)

        # Wrapper detection
        is_wrapper, wrapper_target = False, None
        if opts.track_wrappers:
            is_wrapper, wrapper_target = _detect_wrapper(node)

        fn = FunctionInfo(
            name=node.name, lineno=node.lineno,
            args=arg_names,
            decorators=[ast.unparse(d) for d in node.decorator_list],
            docstring=ast.get_docstring(node),
            calls=calls,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            line_end=line_end, num_lines=num_lines,
            complexity=_cyclomatic_complexity(node) if opts.track_complexity else 1,
            annotations=annotations,
            return_type=return_type,
            exceptions_raised=exceptions_raised,
            num_args=len(arg_names),
            is_wrapper=is_wrapper,
            wrapper_target=wrapper_target,
        )

        if self._current_class:
            self._current_class.methods.append(fn)
        else:
            self.functions.append(fn)

        self._check_func_antipatterns(node, fn)

        self._func_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._func_depth -= 1

    visit_FunctionDef      = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def _check_func_antipatterns(self, node, fn: FunctionInfo):
        opts = self.opts
        if opts.detect_mutable_defaults:
            pos_args = node.args.args
            defaults = node.args.defaults or []
            offset   = len(pos_args) - len(defaults)
            for i, d in enumerate(defaults):
                if kind := _is_mutable_default(d):
                    arg_name = pos_args[offset + i].arg if (offset + i) < len(pos_args) else "?"
                    self.anti_patterns.append(AntiPattern(
                        "mutable-default",
                        f"mutable default ({kind}) for arg '{arg_name}' in "
                        f"{'method' if self._current_class else 'function'} '{fn.name}'",
                        node.lineno,
                    ))
            for d in node.args.kw_defaults or []:
                if d and (kind := _is_mutable_default(d)):
                    self.anti_patterns.append(AntiPattern(
                        "mutable-default",
                        f"mutable default ({kind}) for keyword-only arg in '{fn.name}'",
                        node.lineno,
                    ))

        if opts.detect_too_many_args and fn.num_args > opts.max_args:
            self.anti_patterns.append(AntiPattern(
                "too-many-args",
                f"{'method' if self._current_class else 'function'} '{fn.name}' "
                f"has {fn.num_args} arguments (> {opts.max_args})",
                node.lineno,
            ))

        if opts.detect_long_functions and fn.num_lines > opts.long_function_threshold:
            self.anti_patterns.append(AntiPattern(
                "long-function",
                f"{'method' if self._current_class else 'function'} '{fn.name}' "
                f"is {fn.num_lines} lines (> {opts.long_function_threshold})",
                node.lineno,
            ))

    # ── Generic visitors ──────────────────────────────────────────────────────

    def visit_ExceptHandler(self, node):
        if self.opts.detect_bare_except and node.type is None:
            self.anti_patterns.append(AntiPattern(
                "bare-except",
                "bare `except:` clause (catches everything, including SystemExit)",
                node.lineno,
            ))
        self.generic_visit(node)

    def visit_BinOp(self, node):
        """Detect legacy %-style string formatting."""
        if (self.opts.detect_percent_format
                and isinstance(node.op, ast.Mod)
                and isinstance(node.left, ast.Constant)
                and isinstance(node.left.value, str)):
            self.legacy_patterns.append(AntiPattern(
                "legacy-percent-format",
                "%-style string formatting — prefer f-strings or .format()",
                node.lineno,
            ))
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        name = getattr(func, "id", None) if isinstance(func, ast.Name) else getattr(func, "attr", None)

        if isinstance(func, ast.Name):
            if name in {"exec", "eval"} and self.opts.detect_exec_eval:
                self.anti_patterns.append(AntiPattern(
                    "exec-eval", f"use of `{name}()` (arbitrary code execution risk)", node.lineno,
                ))
            elif name == "print" and self.opts.detect_print:
                self.anti_patterns.append(AntiPattern(
                    "print-statement", "`print()` call (leftover debug output?)", node.lineno,
                ))
            # Legacy: super() with explicit args  →  super(Cls, self)
            if name == "super" and node.args and self.opts.detect_super_args:
                self.legacy_patterns.append(AntiPattern(
                    "legacy-super-args",
                    "super() called with explicit arguments — use bare super() in Python 3",
                    node.lineno,
                ))

        self.generic_visit(node)

    def visit_Assign(self, node):
        if self._current_class is None and self._func_depth == 0:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.globals.append(target.id)
        self.generic_visit(node)


# ── Module builder ────────────────────────────────────────────────────────────

_TODO_RE         = re.compile(r'#\s*(TODO|FIXME|XXX|HACK|NOTE)\b[:\s]?(.*)', re.IGNORECASE)
_TYPE_COMMENT_RE = re.compile(r'#\s*type:\s+(?!ignore\b)')    # skip "# type: ignore"


def build_module_map(filepath: str, opts: ScanOptions) -> ModuleMap:
    source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    tree   = ast.parse(source)

    visitor = CodeMapVisitor(opts)
    visitor.visit(tree)

    anti_patterns   = list(visitor.anti_patterns)
    legacy_patterns = list(visitor.legacy_patterns)

    # ── Duplicate imports ─────────────────────────────────────────────────────
    if opts.detect_duplicate_imports:
        seen: dict = {}
        for imp in visitor.imports:
            if imp.is_wildcard: continue
            if imp.local_name in seen:
                anti_patterns.append(AntiPattern(
                    "duplicate-import",
                    f"duplicate import of '{imp.local_name}' (first at line {seen[imp.local_name]})",
                    imp.lineno,
                ))
            else:
                seen[imp.local_name] = imp.lineno

    # ── Unused imports ────────────────────────────────────────────────────────
    if opts.detect_unused_imports:
        used: set = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                used.add(n.id)
            elif isinstance(n, ast.Attribute):
                base = n
                while isinstance(base, ast.Attribute): base = base.value
                if isinstance(base, ast.Name): used.add(base.id)
        for imp in visitor.imports:
            if imp.is_wildcard or imp.local_name == "*": continue
            if imp.local_name and imp.local_name not in used:
                anti_patterns.append(AntiPattern(
                    "unused-import",
                    f"unused import '{imp.local_name}' ({imp.raw})",
                    imp.lineno,
                ))

    # ── PEP 484 type comments ─────────────────────────────────────────────────
    if opts.detect_type_comments:
        for i, line in enumerate(source.splitlines(), 1):
            if _TYPE_COMMENT_RE.search(line):
                legacy_patterns.append(AntiPattern(
                    "legacy-type-comment",
                    "PEP 484 type comment — use inline annotations instead",
                    i,
                ))

    # ── TODOs ─────────────────────────────────────────────────────────────────
    todos = []
    if opts.track_todos:
        for i, line in enumerate(source.splitlines(), 1):
            if m := _TODO_RE.search(line):
                tag  = m.group(1).upper()
                rest = m.group(2).strip()
                todos.append((i, f"{tag}: {rest}" if rest else tag))

    anti_patterns.sort(key=lambda a: a.lineno)
    legacy_patterns.sort(key=lambda a: a.lineno)

    return ModuleMap(
        path=filepath,
        docstring=ast.get_docstring(tree),
        imports=visitor.imports,
        functions=visitor.functions,
        classes=visitor.classes,
        globals=visitor.globals,
        anti_patterns=anti_patterns,
        legacy_patterns=legacy_patterns,
        todos=todos,
        import_categories=_categorize_imports(visitor.imports) if opts.track_import_categories else {},
    )


# ==========================================
# 5. BACKEND: EXTERNAL TOOLS
# ==========================================

# ── Mypy command builder ─────────────────────────────────────────────────────

# Maps ScanOptions attr → mypy CLI flag (used when not in --strict mode)
_MYPY_FLAG_MAP: List[tuple] = [
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


def _build_mypy_cmd(opts: ScanOptions) -> List[str]:
    """Assemble the mypy CLI command from ScanOptions."""
    cmd = ["mypy", "--no-error-summary", "--hide-error-context", "--show-error-codes"]
    if opts.mypy_strict:
        cmd.append("--strict")
    else:
        for attr, flag in _MYPY_FLAG_MAP:
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
                    _build_mypy_cmd(opts) + chunk,
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
# 6. BACKEND: FORMATTERS
# ==========================================

def _fn_extras(fn: FunctionInfo, opts: ScanOptions) -> str:
    """Inline extras string: line counts, complexity, wrapper indicator."""
    bits = []
    if opts.track_line_counts and fn.num_lines:
        bits.append(f"{fn.num_lines}L")
    if opts.track_complexity:
        bits.append(f"cc={fn.complexity}")
    meta = f"  ({', '.join(bits)})" if bits else ""
    wrap = f"  ↪ {fn.wrapper_target}()" if (opts.track_wrappers and fn.is_wrapper and fn.wrapper_target) else ""
    return meta + wrap


def _format_signature(fn: FunctionInfo, opts: ScanOptions) -> str:
    parts = []
    for a in fn.args:
        if opts.track_annotations and a in fn.annotations:
            parts.append(f"{a}: {fn.annotations[a]}")
        else:
            parts.append(a)
    sig = f"({', '.join(parts)})"
    if opts.track_return_types and fn.return_type:
        sig += f" -> {fn.return_type}"
    return sig


def to_text(m: ModuleMap, opts: ScanOptions) -> str:
    mi_str = f"  [MI: {m.mi_score:.1f} ({m.mi_rank})]" if m.mi_score is not None else ""
    lines  = [f"## Module: {m.path}{mi_str}"]
    if m.docstring:
        lines.append(f'  Purpose: {m.docstring.splitlines()[0]}')

    # Imports
    if m.import_categories:
        for label, key in (("stdlib", "stdlib"), ("third-party", "third_party"), ("local", "local")):
            if bucket := m.import_categories.get(key):
                lines.append(f"  Imports [{label}]: {', '.join(bucket)}")
    elif m.imports:
        lines.append(f"  Imports: {', '.join(i.raw for i in m.imports)}")

    if m.globals:
        lines.append(f"  Globals: {', '.join(m.globals)}")

    # AST anti-patterns
    if m.anti_patterns:
        lines.append(f"\n  ⚠ Anti-patterns ({len(m.anti_patterns)}):")
        for ap in m.anti_patterns:
            lines.append(f"    ⚠ [line {ap.lineno}] {ap.category}: {ap.message}")

    # Legacy patterns
    if m.legacy_patterns:
        lines.append(f"\n  📜 Legacy patterns ({len(m.legacy_patterns)}):")
        for lp in m.legacy_patterns:
            lines.append(f"    📜 [line {lp.lineno}] {lp.category}: {lp.message}")

    # External: Ruff
    if m.ruff_issues:
        lines.append(f"\n  🛑 Ruff findings ({len(m.ruff_issues)}):")
        for r in m.ruff_issues:
            lines.append(f"    🛑 [line {r.row}] [{r.code}] {r.message}")

    # External: Mypy
    if m.mypy_issues:
        lines.append(f"\n  🛡️ Mypy findings ({len(m.mypy_issues)}):")
        for my in m.mypy_issues:
            lines.append(f"    🛡️ [line {my.line}] {my.severity}: {my.message}")

    # TODOs
    if m.todos:
        lines.append(f"\n  ✎ TODO markers ({len(m.todos)}):")
        for ln, text in m.todos:
            lines.append(f"    ✎ [line {ln}] {text}")

    # Classes
    for cls in m.classes:
        bases  = f"({', '.join(cls.bases)})" if cls.bases else ""
        c_extra = f"  ({cls.num_lines}L)" if opts.track_line_counts and cls.num_lines else ""
        lines.append(f"\n  class {cls.name}{bases}  [line {cls.lineno}]{c_extra}")
        if cls.docstring:
            lines.append(f'    "{cls.docstring.splitlines()[0]}"')
        for fn in cls.methods:
            pre = "async " if fn.is_async else ""
            dec = "".join(f"@{d} " for d in fn.decorators)
            sig = _format_signature(fn, opts)
            lines.append(f"    {dec}{pre}def {fn.name}{sig}{_fn_extras(fn, opts)}")
            if fn.docstring:
                lines.append(f'      "{fn.docstring.splitlines()[0]}"')
            if fn.calls:
                lines.append(f"      calls: {', '.join(fn.calls[:6])}")
            if opts.track_exceptions and fn.exceptions_raised:
                lines.append(f"      raises: {', '.join(fn.exceptions_raised)}")

    # Module-level functions
    for fn in m.functions:
        pre = "async " if fn.is_async else ""
        dec = "".join(f"@{d} " for d in fn.decorators)
        sig = _format_signature(fn, opts)
        lines.append(f"\n  {dec}{pre}def {fn.name}{sig}  [line {fn.lineno}]{_fn_extras(fn, opts)}")
        if fn.docstring:
            lines.append(f'    "{fn.docstring.splitlines()[0]}"')
        if fn.calls:
            lines.append(f"    calls: {', '.join(fn.calls[:6])}")
        if opts.track_exceptions and fn.exceptions_raised:
            lines.append(f"    raises: {', '.join(fn.exceptions_raised)}")

    return "\n".join(lines)


def _fn_to_dict(fn: FunctionInfo, opts: ScanOptions) -> dict:
    d: dict = {
        "name": fn.name, "line": fn.lineno,
        "args": fn.args, "decorators": fn.decorators,
        "docstring": fn.docstring, "calls": fn.calls,
        "async": fn.is_async,
    }
    if opts.track_line_counts:
        d["num_lines"] = fn.num_lines; d["line_end"] = fn.line_end
    if opts.track_complexity:
        d["complexity"] = fn.complexity
    if opts.track_annotations and fn.annotations:
        d["annotations"] = fn.annotations
    if opts.track_return_types and fn.return_type:
        d["return_type"] = fn.return_type
    if opts.track_exceptions and fn.exceptions_raised:
        d["raises"] = fn.exceptions_raised
    if opts.track_wrappers and fn.is_wrapper:
        d["wrapper"] = True
        if fn.wrapper_target:
            d["wrapper_target"] = fn.wrapper_target
    return d


def to_json(m: ModuleMap, opts: ScanOptions) -> dict:
    out: dict = {
        "path": m.path, "docstring": m.docstring,
        "imports": [i.raw for i in m.imports],
        "globals": m.globals,
        "functions": [_fn_to_dict(f, opts) for f in m.functions],
        "classes": [
            {
                "name": c.name, "line": c.lineno,
                "bases": c.bases, "docstring": c.docstring,
                **({"num_lines": c.num_lines, "line_end": c.line_end}
                   if opts.track_line_counts else {}),
                "methods": [_fn_to_dict(f, opts) for f in c.methods],
            }
            for c in m.classes
        ],
    }
    if m.anti_patterns:
        out["anti_patterns"] = [
            {"category": a.category, "message": a.message, "line": a.lineno}
            for a in m.anti_patterns
        ]
    if m.legacy_patterns:
        out["legacy_patterns"] = [
            {"category": a.category, "message": a.message, "line": a.lineno}
            for a in m.legacy_patterns
        ]
    if m.todos:
        out["todos"] = [{"line": ln, "text": t} for ln, t in m.todos]
    if m.import_categories:
        out["import_categories"] = m.import_categories
    if m.mi_score is not None:
        out["mi_score"] = m.mi_score; out["mi_rank"] = m.mi_rank
    if m.ruff_issues:
        out["ruff_issues"] = [{"code": r.code, "message": r.message, "line": r.row}
                               for r in m.ruff_issues]
    if m.mypy_issues:
        out["mypy_issues"] = [{"line": my.line, "severity": my.severity, "message": my.message}
                               for my in m.mypy_issues]
    # Embed the effective mypy command for reproducibility
    if opts.run_mypy_analysis:
        out["mypy_cmd"] = _build_mypy_cmd(opts)
    return out


# ==========================================
# 7. FRONTEND: WIDGETS
# ==========================================

class FileTreeWidget(QTreeWidget):
    """
    .py file tree with tristate folder checkboxes and shift-click range select.
    """
    selection_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_clicked_leaf: Optional[QTreeWidgetItem] = None
        self._updating = False
        self.itemChanged.connect(self._on_item_changed)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    def populate(self, root_dir: str):
        self._updating = True
        self.clear(); self._last_clicked_leaf = None
        root = Path(root_dir)
        all_files = sorted([
            p for p in root.rglob("*.py")
            if not any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts)
        ])
        dir_items: dict = {}
        for fp in all_files:
            rel         = fp.relative_to(root)
            parent_item = self.invisibleRootItem()
            acc         = root
            for part in rel.parts[:-1]:
                acc = acc / part
                if acc not in dir_items:
                    fi = QTreeWidgetItem(parent_item, [part])
                    fi.setFlags(fi.flags()
                                | Qt.ItemFlag.ItemIsUserCheckable
                                | Qt.ItemFlag.ItemIsAutoTristate)
                    fi.setCheckState(0, Qt.CheckState.Checked)
                    fi.setData(0, Qt.ItemDataRole.UserRole, None)
                    dir_items[acc] = fi
                parent_item = dir_items[acc]
            leaf = QTreeWidgetItem(parent_item, [fp.name])
            leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.CheckState.Checked)
            leaf.setData(0, Qt.ItemDataRole.UserRole, str(fp))
        self.expandAll()
        self._updating = False
        self._emit_counts()

    def checked_files(self) -> list:
        out: list = []
        self._collect_checked(self.invisibleRootItem(), out)
        return out

    def set_all(self, state: Qt.CheckState):
        self._updating = True
        self._set_subtree(self.invisibleRootItem(), state)
        self._updating = False
        self._emit_counts()

    def invert(self):
        self._updating = True
        self._invert_leaves(self.invisibleRootItem())
        self._updating = False
        self._emit_counts()

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item and event.button() == Qt.MouseButton.LeftButton:
            is_leaf = item.data(0, Qt.ItemDataRole.UserRole) is not None
            if is_leaf:
                if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        and self._last_clicked_leaf is not None):
                    self._range_toggle(self._last_clicked_leaf, item)
                    self._last_clicked_leaf = item
                    return
                else:
                    self._last_clicked_leaf = item
        super().mousePressEvent(event)

    # ── Internals ──────────────────────────────────────────────────────────

    def _on_item_changed(self, _item, _col):
        if not self._updating: self._emit_counts()

    def _emit_counts(self):
        leaves: list = []
        self._collect_all_leaves(self.invisibleRootItem(), leaves)
        checked = sum(1 for it in leaves if it.checkState(0) == Qt.CheckState.Checked)
        self.selection_changed.emit(checked, len(leaves))

    def _collect_checked(self, parent, out):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None:
                if child.checkState(0) == Qt.CheckState.Checked:
                    out.append(child.data(0, Qt.ItemDataRole.UserRole))
            else:
                self._collect_checked(child, out)

    def _collect_all_leaves(self, parent, out):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None: out.append(child)
            else: self._collect_all_leaves(child, out)

    def _set_subtree(self, parent, state):
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            self._set_subtree(child, state)

    def _invert_leaves(self, parent):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None:
                child.setCheckState(0,
                    Qt.CheckState.Unchecked
                    if child.checkState(0) == Qt.CheckState.Checked
                    else Qt.CheckState.Checked)
            else:
                self._invert_leaves(child)

    def _leaves_in_order(self) -> list:
        out: list = []
        self._leaves_dfs(self.invisibleRootItem(), out)
        return out

    def _leaves_dfs(self, parent, out):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None: out.append(child)
            else: self._leaves_dfs(child, out)

    def _range_toggle(self, anchor, target):
        leaves = self._leaves_in_order()
        try:
            ia, it = leaves.index(anchor), leaves.index(target)
        except ValueError:
            return
        if ia > it: ia, it = it, ia
        desired = (Qt.CheckState.Unchecked
                   if target.checkState(0) == Qt.CheckState.Checked
                   else Qt.CheckState.Checked)
        self._updating = True
        for leaf in leaves[ia:it + 1]:
            leaf.setCheckState(0, desired)
        self._updating = False
        self._emit_counts()


class MapHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules, self._block_rules = [], []

        def rule(pattern, color, bold=False, whole_line=False, bg=None):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold: fmt.setFontWeight(QFont.Weight.Bold)
            if bg:   fmt.setBackground(QColor(bg))
            target = self._block_rules if whole_line else self._rules
            target.append((re.compile(pattern), fmt))

        # ── Whole-line block highlights (applied first) ────────────────────
        rule(r"^\s*⚠.*",  "#fca5a5", bold=True, whole_line=True, bg="#3f1d1d")
        rule(r"^\s*📜.*", "#fde68a", bold=True, whole_line=True, bg="#2d2208")
        rule(r"^\s*🛑.*", "#ef4444", bold=True, whole_line=True, bg="#450a0a")
        rule(r"^\s*🛡️.*", "#60a5fa", bold=True, whole_line=True, bg="#1e3a8a")
        rule(r"^\s*✎.*",  "#fcd34d",             whole_line=True, bg="#2e2512")

        # ── Per-token inline rules ─────────────────────────────────────────
        rule(r"^## Module:.*",                "#7dd3fc", bold=True)
        rule(r"\[MI: [0-9.]+ \([A-F]\)\]",   "#10b981", bold=True)
        rule(r"\bclass\s+\w+",                "#f9a8d4", bold=True)
        rule(r"\b(?:async\s+)?def\s+\w+",    "#86efac")
        rule(r"@\w+",                          "#fbbf24")
        rule(r'"[^"]*"',                       "#a5b4fc")
        rule(r"\[line \d+\]",                  "#6b7280")
        rule(r"\bcalls:.*",                    "#94a3b8")
        rule(r"\braises:.*",                   "#f87171")
        rule(r"(?:Purpose|Imports(?:\s*\[[^\]]+\])?|Globals):.*", "#d1d5db")
        rule(r"->\s*[\w\[\], .|]+",            "#c4b5fd")
        rule(r"\bcc=\d+",                      "#fdba74")
        rule(r"\b\d+L\b",                      "#fdba74")
        rule(r"↪\s+\S+\(\)",                  "#34d399")   # wrapper target

    def highlightBlock(self, text):
        for pattern, fmt in self._block_rules:
            if pattern.match(text):
                self.setFormat(0, len(text), fmt)
                return
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ==========================================
# 8. FRONTEND: WORKER THREAD
# ==========================================

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
                    stats["issues"]    += (len(m.anti_patterns) + len(m.legacy_patterns)
                                           + len(m.ruff_issues) + len(m.mypy_issues))
                except SyntaxError:
                    stats["errors"] += 1

            # Sort worst MI first (files with no MI score go last)
            maps.sort(key=lambda x: x.mi_score if x.mi_score is not None else 999)
            self.finished.emit(maps, stats)

        except Exception as e:
            self.error.emit(str(e))


# ==========================================
# 9. FRONTEND: OPTION DEFINITIONS
# ==========================================

# (attr_name, label, tooltip)
_TRACK_OPTIONS: list = [
    ("include_calls",           "Call graph",
     "List functions called from each function/method."),
    ("track_line_counts",       "Line counts",
     "Show how many lines each function/class spans."),
    ("track_complexity",        "Cyclomatic complexity",
     "Estimate branching complexity (CC) for each function."),
    ("track_return_types",      "Return types",
     "Include annotated return types in signatures."),
    ("track_annotations",       "Arg type annotations",
     "Include per-argument type annotations in signatures."),
    ("track_exceptions",        "Exceptions raised",
     "List exception types raised by each function."),
    ("track_import_categories", "Group imports (stdlib / third-party / local)",
     "Split the import list into three labelled groups."),
    ("track_todos",             "TODO / FIXME / XXX comments",
     "Scan source comments for TODO/FIXME/XXX/HACK/NOTE tags."),
    ("track_wrappers",          "Wrapper functions / methods",
     "Identify thin passthrough functions that mainly delegate to one other call.\n"
     "Shown as  ↪ target()  after the signature."),
]

_ANTIPATTERN_OPTIONS: list = [
    ("detect_wildcard",          "Wildcard imports (`from x import *`)",
     "Flag `from x import *` statements."),
    ("detect_duplicate_imports", "Duplicate imports",
     "Flag names imported more than once."),
    ("detect_unused_imports",    "Unused imports",
     "Flag imports whose local name is never referenced."),
    ("detect_mutable_defaults",  "Mutable default arguments",
     "Flag `def f(x=[])` / `def f(x={})` patterns."),
    ("detect_bare_except",       "Bare `except:` clauses",
     "Flag `except:` without an exception type."),
    ("detect_exec_eval",         "`exec()` / `eval()` usage",
     "Flag direct use of exec() or eval()."),
    ("detect_long_functions",    "Long functions",
     "Flag functions exceeding the line-count threshold."),
    ("detect_too_many_args",     "Too many arguments",
     "Flag functions exceeding the argument-count threshold."),
    ("detect_god_classes",       "God classes",
     "Flag classes exceeding the method-count threshold."),
    ("detect_print",             "`print()` leftovers",
     "Flag top-level print() calls as possible debug output."),
]

_LEGACY_OPTIONS: list = [
    ("detect_percent_format",  "%-style string formatting",
     'Flag `"hello %s" % name` — prefer f-strings or .format().\n'
     "Only triggers when the left operand is a string literal."),
    ("detect_super_args",      "super() with explicit args",
     "Flag `super(ClassName, self)` — use bare `super()` in Python 3."),
    ("detect_type_comments",   "PEP 484 type comments  (# type: int)",
     "Flag inline `# type:` comments — use inline annotations instead.\n"
     "`# type: ignore` is intentionally excluded."),
]


# ==========================================
# 10. STYLESHEET
# ==========================================

DARK = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
    font-size: 13px;
}
QLabel#title    { font-size: 20px; font-weight: 700; color: #f8fafc; letter-spacing: 0.5px; }
QLabel#subtitle { color: #64748b; font-size: 12px; }

/* ── Buttons ── */
QPushButton {
    background-color: #1e293b; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 6px;
    padding: 6px 14px; font-size: 12px;
}
QPushButton:hover   { background-color: #273549; border-color: #4f7ec0; }
QPushButton:pressed { background-color: #172033; }
QPushButton:disabled { color: #475569; border-color: #1e293b; }

QPushButton#primary {
    background-color: #1d4ed8; border-color: #2563eb;
    color: #fff; font-weight: 600;
}
QPushButton#primary:hover    { background-color: #2563eb; }
QPushButton#primary:pressed  { background-color: #1e40af; }
QPushButton#primary:disabled { background-color: #1e3a5f; color: #6b7280; }

QPushButton#save {
    background-color: #065f46; border-color: #059669;
    color: #ecfdf5; font-weight: 600;
}
QPushButton#save:hover    { background-color: #047857; }
QPushButton#save:disabled { background-color: #1a2e28; color: #6b7280; }

QPushButton#sel {
    padding: 3px 10px; font-size: 11px;
    background-color: #141a25; border-color: #1e293b;
}
QPushButton#sel:hover { background-color: #1e293b; border-color: #334155; }

QPushButton#ghost {
    background-color: transparent; border: 1px solid #334155;
    color: #94a3b8; padding: 3px 8px; font-size: 11px;
}
QPushButton#ghost:hover { color: #e2e8f0; border-color: #4f7ec0; }

/* ── Text / Output ── */
QTextEdit {
    background-color: #0a0d14; color: #cbd5e1;
    border: 1px solid #1e293b; border-radius: 6px;
    font-family: "Cascadia Code","Fira Code","JetBrains Mono",monospace;
    font-size: 12px; padding: 8px;
    selection-background-color: #1d4ed8;
}

/* ── File tree ── */
QTreeWidget {
    background-color: #0a0d14; color: #cbd5e1;
    border: 1px solid #1e293b; border-radius: 6px;
    font-size: 12px; alternate-background-color: #0d1320;
    show-decoration-selected: 0; outline: none;
}
QTreeWidget::item       { padding: 3px 4px; border-radius: 3px; }
QTreeWidget::item:hover { background-color: #182030; }
QTreeWidget::branch     { background: transparent; }

/* ── Progress ── */
QProgressBar {
    background-color: #1e293b; border: none;
    border-radius: 4px; height: 6px; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #7c3aed);
    border-radius: 4px;
}

/* ── Combo / checkbox / spinbox ── */
QComboBox {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 5px; padding: 5px 10px; color: #e2e8f0; min-width: 80px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #1e293b; border: 1px solid #334155;
    selection-background-color: #1d4ed8;
}

QCheckBox { spacing: 6px; color: #cbd5e1; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #475569; border-radius: 3px;
    background-color: #1e293b;
}
QCheckBox::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
QCheckBox:disabled { color: #475569; }

QSpinBox {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 4px; padding: 2px 6px;
    color: #e2e8f0; font-size: 12px; min-width: 52px;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #273549; border: none; width: 14px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background-color: #2563eb; }

QLineEdit {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 4px; padding: 3px 7px;
    color: #e2e8f0; font-size: 12px;
    selection-background-color: #1d4ed8;
}
QLineEdit:focus  { border-color: #2563eb; }
QLineEdit:disabled { color: #475569; background-color: #141a25; }

/* ── Structural frames ── */
QFrame#card    { background-color: #141a25; border: 1px solid #1e293b; border-radius: 8px; }
QFrame#optcard { background-color: #111722; border: 1px solid #1e293b; border-radius: 8px; }
QFrame#extcard { background-color: #0e1a14; border: 1px solid #1a3025; border-radius: 8px; }
QFrame#mypycard { background-color: #0e1520; border: 1px solid #1a2a40; border-radius: 8px; }
QFrame#divider { background-color: #1e293b; max-height: 1px; }

/* ── Scroll area ── */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ── Labels ── */
QLabel#stat      { color: #94a3b8; font-size: 12px; }
QLabel#statval   { color: #38bdf8; font-size: 14px; font-weight: 700; }
QLabel#statwarn  { color: #fb923c; font-size: 14px; font-weight: 700; }
QLabel#selfmt    { color: #64748b; font-size: 11px; }
QLabel#panelhead { color: #475569; font-size: 10px; font-weight: 700; letter-spacing: 1.2px; }
QLabel#sechead   { color: #94a3b8; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
QLabel#mypyhead  { color: #7dd3fc; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
QLabel#threshold { color: #64748b; font-size: 11px; }
QLabel#fieldlbl  { color: #64748b; font-size: 11px; min-width: 110px; }
QLabel#toolfound { color: #34d399; font-size: 11px; }
QLabel#toolmiss  { color: #f87171; font-size: 11px; }

QStatusBar {
    background-color: #0a0d14; color: #475569;
    border-top: 1px solid #1e293b; font-size: 11px;
}
QSplitter::handle:horizontal { background-color: #1e293b; width: 3px; }
"""


# ==========================================
# 11. FRONTEND: MAIN WINDOW
# ==========================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyCodeRadar — Extended Code Map & Refactoring Radar")
        self.setMinimumSize(1200, 760)
        self._root_dir: Optional[str] = None
        self._result_text: str = ""
        self._thread: Optional[QThread] = None
        self._worker: Optional[ScanWorker] = None
        self._check_widgets: dict = {}
        self._spin_widgets:  dict = {}
        self._text_widgets:  dict = {}        # attr → QLineEdit
        self._mypy_strict_flags: list = []    # checkboxes disabled under --strict
        self._active_opts:   Optional[ScanOptions] = None
        self._setup_ui()
        self.setStyleSheet(DARK)

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 8)
        root_layout.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        lbl_title = QLabel("PyCodeRadar"); lbl_title.setObjectName("title")
        lbl_sub   = QLabel("AST Code Map · Wrapper Detection · Legacy Analysis · Ruff / Radon / Mypy")
        lbl_sub.setObjectName("subtitle")
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_sub)
        header.addLayout(title_col); header.addStretch()
        header.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox(); self.fmt_combo.addItems(["Text", "JSON"])
        header.addWidget(self.fmt_combo)
        root_layout.addLayout(header)

        div = QFrame(); div.setObjectName("divider"); div.setFrameShape(QFrame.Shape.HLine)
        root_layout.addWidget(div)

        # ── Folder picker card ────────────────────────────────────────────────
        card = QFrame(); card.setObjectName("card")
        cl = QHBoxLayout(card); cl.setContentsMargins(12, 8, 12, 8); cl.setSpacing(10)
        btn_open = QPushButton("⊞  Open Folder…"); btn_open.setFixedWidth(140)
        btn_open.clicked.connect(self._open_folder)
        self.lbl_path = QLabel("No folder selected"); self.lbl_path.setObjectName("stat")
        self.lbl_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.btn_scan = QPushButton("▶  Analyse"); self.btn_scan.setObjectName("primary")
        self.btn_scan.setFixedWidth(150); self.btn_scan.setEnabled(False)
        self.btn_scan.clicked.connect(self._start_scan)
        cl.addWidget(btn_open); cl.addWidget(self.lbl_path, 1); cl.addWidget(self.btn_scan)
        root_layout.addWidget(card)

        # ── Progress bar ──────────────────────────────────────────────────────
        pr = QHBoxLayout()
        self.progress_bar = QProgressBar(); self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.lbl_progress = QLabel(""); self.lbl_progress.setObjectName("stat")
        self.lbl_progress.setFixedWidth(300)
        pr.addWidget(self.progress_bar); pr.addWidget(self.lbl_progress)
        root_layout.addLayout(pr)

        # ── Splitter ──────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        root_layout.addWidget(splitter, 1)

        # ── LEFT: file tree + options ─────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 6, 0); ll.setSpacing(5)

        th = QHBoxLayout()
        lf = QLabel("FILES"); lf.setObjectName("panelhead")
        self.lbl_sel_count = QLabel("—"); self.lbl_sel_count.setObjectName("selfmt")
        self.lbl_sel_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        th.addWidget(lf); th.addStretch(); th.addWidget(self.lbl_sel_count)
        ll.addLayout(th)

        brow = QHBoxLayout(); brow.setSpacing(4)
        for txt, slot in [("Select All", self._sel_all),
                          ("Deselect All", self._sel_none),
                          ("Invert", self._sel_invert)]:
            b = QPushButton(txt); b.setObjectName("sel"); b.setFixedHeight(24)
            b.clicked.connect(slot); brow.addWidget(b)
        brow.addStretch()
        ll.addLayout(brow)

        hint = QLabel("Shift+click for range selection"); hint.setObjectName("selfmt")
        ll.addWidget(hint)

        self.file_tree = FileTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.selection_changed.connect(self._on_tree_changed)
        ll.addWidget(self.file_tree, 1)
        ll.addWidget(self._build_options_panel())

        splitter.addWidget(left)

        # ── RIGHT: output ─────────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(6, 0, 0, 0); rl.setSpacing(5)

        oh = QHBoxLayout()
        lo = QLabel("OUTPUT"); lo.setObjectName("panelhead")
        oh.addWidget(lo); oh.addStretch()

        def mini_stat(label, warn=False):
            col = QVBoxLayout(); col.setSpacing(0)
            v = QLabel("—"); v.setObjectName("statwarn" if warn else "statval")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_ = QLabel(label); l_.setObjectName("selfmt")
            l_.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(v); col.addWidget(l_)
            oh.addLayout(col); oh.addSpacing(14)
            return v

        self.stat_modules  = mini_stat("modules")
        self.stat_classes  = mini_stat("classes")
        self.stat_funcs    = mini_stat("funcs")
        self.stat_issues   = mini_stat("⚠ issues", warn=True)
        self.stat_errors   = mini_stat("errors")

        self.btn_save = QPushButton("⬇  Save…"); self.btn_save.setObjectName("save")
        self.btn_save.setFixedWidth(100); self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_file)
        oh.addWidget(self.btn_save)
        rl.addLayout(oh)

        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.output.setPlaceholderText(
            "Analysis results will appear here…\n\n"
            "1. Open a folder  →  .py files populate the left panel\n"
            "2. Tick / untick files;  Shift+click for range selection\n"
            "3. Configure options below the file tree\n"
            "4. Click 'Analyse'  →  report renders here\n"
            "5. Click 'Save…'  →  export as .txt or .json"
        )
        self.highlighter = MapHighlighter(self.output.document())
        rl.addWidget(self.output, 1)

        splitter.addWidget(right)
        splitter.setSizes([320, 880])

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Ready — open a folder to begin")

    # ── Options panel ─────────────────────────────────────────────────────────

    def _build_options_panel(self) -> QWidget:
        defaults = ScanOptions()
        scroll   = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(420)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 4, 0, 4); vbox.setSpacing(6)

        # ── TRACK card ────────────────────────────────────────────────────────
        track_card = self._make_option_card("TRACK  —  additional metadata")
        for attr, label, tip in _TRACK_OPTIONS:
            self._add_checkbox(track_card, attr, label, tip, getattr(defaults, attr))
        vbox.addWidget(track_card)

        # ── ANTI-PATTERNS card ────────────────────────────────────────────────
        anti_card = self._make_option_card("DETECT  —  anti-patterns")
        for attr, label, tip in _ANTIPATTERN_OPTIONS:
            self._add_checkbox(anti_card, attr, label, tip, getattr(defaults, attr))
        self._add_threshold_grid(anti_card, defaults)
        self._add_quick_actions(anti_card, _ANTIPATTERN_OPTIONS)
        vbox.addWidget(anti_card)

        # ── LEGACY card ───────────────────────────────────────────────────────
        legacy_card = self._make_option_card("DETECT  —  legacy code patterns")
        for attr, label, tip in _LEGACY_OPTIONS:
            self._add_checkbox(legacy_card, attr, label, tip, getattr(defaults, attr))
        hint_lbl = QLabel(
            "Ruff's UP ruleset also covers many legacy patterns when enabled below."
        )
        hint_lbl.setObjectName("selfmt"); hint_lbl.setWordWrap(True)
        legacy_card.layout().addWidget(hint_lbl)
        self._add_quick_actions(legacy_card, _LEGACY_OPTIONS)
        vbox.addWidget(legacy_card)

        # ── EXTERNAL TOOLS card ───────────────────────────────────────────────
        ext_card = self._make_ext_card()
        vbox.addWidget(ext_card)

        # ── MYPY CONFIGURATION card ───────────────────────────────────────────
        mypy_card = self._make_mypy_card(defaults)
        vbox.addWidget(mypy_card)

        vbox.addStretch()
        scroll.setWidget(container)
        return scroll

    def _make_option_card(self, title: str) -> QFrame:
        card = QFrame(); card.setObjectName("optcard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(3)
        hdr  = QLabel(title); hdr.setObjectName("sechead")
        lay.addWidget(hdr)
        return card

    def _add_checkbox(self, card: QFrame, attr: str, label: str,
                      tooltip: str, default: bool):
        cb = QCheckBox(label)
        cb.setChecked(default); cb.setToolTip(tooltip)
        card.layout().addWidget(cb)
        self._check_widgets[attr] = cb

    def _add_threshold_grid(self, card: QFrame, defaults: ScanOptions):
        from PySide6.QtWidgets import QGridLayout as _Grid
        grid = _Grid()
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(8); grid.setVerticalSpacing(4)

        def add_row(row, attr, label, lo, hi, default):
            lbl = QLabel(label); lbl.setObjectName("threshold")
            spin = QSpinBox(); spin.setRange(lo, hi); spin.setValue(default)
            spin.setToolTip(f"Threshold for '{attr}'")
            grid.addWidget(lbl, row, 0); grid.addWidget(spin, row, 1)
            self._spin_widgets[attr] = spin

        add_row(0, "long_function_threshold", "Max function lines:", 10, 500, defaults.long_function_threshold)
        add_row(1, "max_args",                "Max arguments:",       1,  30, defaults.max_args)
        add_row(2, "god_class_threshold",     "Max methods/class:",   3, 100, defaults.god_class_threshold)
        card.layout().addLayout(grid)

    def _add_quick_actions(self, card: QFrame, group: list):
        row = QHBoxLayout(); row.setContentsMargins(0, 5, 0, 0)
        for label, slot in [("All",      lambda g=group: self._toggle_group(g, True)),
                             ("None",     lambda g=group: self._toggle_group(g, False)),
                             ("Defaults", lambda g=group: self._reset_group(g, ScanOptions()))]:
            b = QPushButton(label); b.setObjectName("ghost"); b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        card.layout().addLayout(row)

    def _make_ext_card(self) -> QFrame:
        card = QFrame(); card.setObjectName("extcard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(4)
        lay.addWidget(QLabel("EXTERNAL TOOLS  —  optional deep analysis", objectName="sechead"))

        def tool_row(attr, tool_name, description, available):
            cb = QCheckBox(f"{tool_name}: {description}")
            cb.setChecked(available); cb.setEnabled(available)
            if not available:
                cb.setText(f"{tool_name}: {description}  (not installed)")
            status = QLabel("✓ found" if available else "✗ not found")
            status.setObjectName("toolfound" if available else "toolmiss")
            row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb, 1); row.addWidget(status)
            lay.addLayout(row)
            self._check_widgets[attr] = cb

        tool_row("run_ruff_analysis",  "Ruff",  "deep smells, legacy syntax (UP rules)",  HAS_RUFF)
        tool_row("run_radon_analysis", "Radon", "Maintainability Index (MI score)",         HAS_RADON)
        tool_row("run_mypy_analysis",  "Mypy",  "static type checking",                     HAS_MYPY)

        note = QLabel("Files sorted worst-to-best MI score in output when Radon is enabled.")
        note.setObjectName("selfmt"); note.setWordWrap(True)
        lay.addWidget(note)
        return card

    def _make_mypy_card(self, defaults: ScanOptions) -> QFrame:
        card = QFrame(); card.setObjectName("mypycard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10); lay.setSpacing(4)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QLabel("MYPY  —  strictness & filters"); hdr.setObjectName("mypyhead")
        lay.addWidget(hdr)

        # ── Strict mode master toggle ─────────────────────────────────────────
        cb_strict = QCheckBox("Strict mode  (--strict  · implies all flags below)")
        cb_strict.setChecked(defaults.mypy_strict)
        cb_strict.setToolTip(
            "Passes --strict to mypy, which enables the full set of strictness checks.\n"
            "Individual flag checkboxes are disabled while this is active — mypy will\n"
            "apply all of them regardless."
        )
        self._check_widgets["mypy_strict"] = cb_strict
        lay.addWidget(cb_strict)

        # thin separator
        sep = QFrame(); sep.setObjectName("divider"); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        # ── Individual strictness flags ───────────────────────────────────────
        _STRICT_FLAGS: list = [
            ("mypy_disallow_untyped_defs",      "--disallow-untyped-defs",
             "Require type annotations on every function definition."),
            ("mypy_disallow_incomplete_defs",   "--disallow-incomplete-defs",
             "Reject partially annotated functions (some args typed, some not)."),
            ("mypy_check_untyped_defs",         "--check-untyped-defs",
             "Type-check the bodies of functions even when they lack annotations."),
            ("mypy_disallow_any_generics",      "--disallow-any-generics",
             "Disallow generic types without explicit type parameters (e.g. List[Any])."),
            ("mypy_warn_return_any",            "--warn-return-any",
             "Warn when a typed function returns a value typed as Any."),
            ("mypy_warn_unused_ignores",        "--warn-unused-ignores",
             "Warn when a # type: ignore comment is no longer needed."),
            ("mypy_no_implicit_optional",       "--no-implicit-optional",
             "Do not treat default=None as an implicit Optional[T].\n(Enabled by default here — this is almost always what you want.)"),
            ("mypy_strict_equality",            "--strict-equality",
             "Prohibit equality comparisons that can never be True."),
            ("mypy_disallow_untyped_decorators","--disallow-untyped-decorators",
             "Reject decorators that do not have complete type annotations."),
        ]
        self._mypy_strict_flags = []
        for attr, flag_name, tip in _STRICT_FLAGS:
            cb = QCheckBox(flag_name)
            cb.setChecked(getattr(defaults, attr))
            cb.setToolTip(tip)
            cb.setEnabled(not defaults.mypy_strict)
            lay.addWidget(cb)
            self._check_widgets[attr] = cb
            self._mypy_strict_flags.append(cb)

        # wire strict toggle ↔ individual flags enabled state
        def _on_strict_toggled(checked: bool):
            for f in self._mypy_strict_flags:
                f.setEnabled(not checked)
        cb_strict.toggled.connect(_on_strict_toggled)

        # thin separator
        sep2 = QFrame(); sep2.setObjectName("divider"); sep2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep2)

        # ── Ignore options ────────────────────────────────────────────────────
        cb_miss = QCheckBox("--ignore-missing-imports")
        cb_miss.setChecked(defaults.mypy_ignore_missing_imports)
        cb_miss.setToolTip(
            "Suppress errors about missing stub files or missing source for imports.\n"
            "Useful for third-party packages that don't ship type information."
        )
        self._check_widgets["mypy_ignore_missing_imports"] = cb_miss
        lay.addWidget(cb_miss)

        # Disable error codes row
        codes_row = QHBoxLayout(); codes_row.setSpacing(6)
        codes_lbl = QLabel("Disable codes:"); codes_lbl.setObjectName("fieldlbl")
        codes_edit = QLineEdit()
        codes_edit.setPlaceholderText("e.g.  import-untyped, no-untyped-def")
        codes_edit.setText(defaults.mypy_disable_error_codes)
        codes_edit.setToolTip(
            "Comma-separated list of mypy error codes to silence with --disable-error-code.\n"
            "Example:  import-untyped, no-untyped-def, attr-defined\n\n"
            "Full list:  mypy --show-error-codes  or  https://mypy.readthedocs.io/en/stable/error_codes.html"
        )
        codes_row.addWidget(codes_lbl); codes_row.addWidget(codes_edit, 1)
        lay.addLayout(codes_row)
        self._text_widgets["mypy_disable_error_codes"] = codes_edit

        # thin separator
        sep3 = QFrame(); sep3.setObjectName("divider"); sep3.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep3)

        # ── Severity filter ───────────────────────────────────────────────────
        sev_row = QHBoxLayout(); sev_row.setSpacing(0)
        sev_lbl = QLabel("Show:"); sev_lbl.setObjectName("fieldlbl")
        sev_row.addWidget(sev_lbl)
        for attr, label, tip in [
            ("mypy_show_errors",   "Errors",   "Show mypy ERROR messages."),
            ("mypy_show_warnings", "Warnings", "Show mypy WARNING messages."),
            ("mypy_show_notes",    "Notes",    "Show mypy NOTE messages (informational, often verbose)."),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(getattr(defaults, attr))
            cb.setToolTip(tip)
            sev_row.addWidget(cb); sev_row.addSpacing(10)
            self._check_widgets[attr] = cb
        sev_row.addStretch()
        lay.addLayout(sev_row)

        # hint when mypy is not installed
        if not HAS_MYPY:
            note = QLabel("Mypy is not installed — these settings will have no effect.")
            note.setObjectName("toolmiss"); note.setWordWrap(True)
            lay.addWidget(note)

        return card

    def _toggle_group(self, group: list, value: bool):
        for attr, _, _ in group:
            if attr in self._check_widgets:
                self._check_widgets[attr].setChecked(value)

    def _reset_group(self, group: list, defaults: ScanOptions):
        for attr, _, _ in group:
            if attr in self._check_widgets:
                self._check_widgets[attr].setChecked(getattr(defaults, attr))

    def _current_options(self) -> ScanOptions:
        opts = ScanOptions()
        for attr, cb in self._check_widgets.items():
            if hasattr(opts, attr): setattr(opts, attr, cb.isChecked())
        for attr, spin in self._spin_widgets.items():
            if hasattr(opts, attr): setattr(opts, attr, spin.value())
        for attr, edit in self._text_widgets.items():
            if hasattr(opts, attr): setattr(opts, attr, edit.text().strip())
        return opts

    # ── Tree callbacks ────────────────────────────────────────────────────────

    def _sel_all(self):    self.file_tree.set_all(Qt.CheckState.Checked)
    def _sel_none(self):   self.file_tree.set_all(Qt.CheckState.Unchecked)
    def _sel_invert(self): self.file_tree.invert()

    def _on_tree_changed(self, checked: int, total: int):
        self.lbl_sel_count.setText(f"{checked} / {total} selected")
        self.btn_scan.setEnabled(checked > 0 and self._root_dir is not None)

    # ── Folder open ───────────────────────────────────────────────────────────

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Python Project Folder", str(Path.home()))
        if not folder: return
        self._root_dir = folder
        self.lbl_path.setText(folder if len(folder) <= 72 else "…" + folder[-69:])
        self.output.clear(); self._result_text = ""
        self.btn_save.setEnabled(False)
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs,
                  self.stat_issues, self.stat_errors):
            s.setText("—")
        self.file_tree.populate(folder)
        self.status.showMessage(f"Loaded: {folder}")

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _start_scan(self):
        selected = self.file_tree.checked_files()
        if not selected:
            self.status.showMessage("No files selected."); return

        self.btn_scan.setEnabled(False); self.btn_save.setEnabled(False)
        self.output.clear()
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs,
                  self.stat_issues, self.stat_errors):
            s.setText("…")

        self._active_opts = self._current_options()
        self._thread = QThread()
        self._worker = ScanWorker(selected, self._active_opts)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

        ext_note = ""
        if self._active_opts.run_ruff_analysis and HAS_RUFF:   ext_note += " + Ruff"
        if self._active_opts.run_radon_analysis and HAS_RADON: ext_note += " + Radon"
        if self._active_opts.run_mypy_analysis  and HAS_MYPY:
            if self._active_opts.mypy_strict:
                ext_note += " + Mypy (--strict)"
            else:
                flags_on = sum(
                    1 for attr, _ in _MYPY_FLAG_MAP if getattr(self._active_opts, attr)
                )
                ext_note += f" + Mypy ({flags_on} flag{'s' if flags_on != 1 else ''})"
        self.status.showMessage(f"Scanning {len(selected)} file(s){ext_note}…")

    def _on_progress(self, current: int, total: int, name: str):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)
        self.lbl_progress.setText(f"{current}/{total}  {name}")

    def _on_finished(self, maps: list, stats: dict):
        opts = self._active_opts or ScanOptions()
        fmt  = self.fmt_combo.currentText().lower()
        if fmt == "json":
            self._result_text = json.dumps([to_json(m, opts) for m in maps], indent=2)
        else:
            self._result_text = "\n\n".join(to_text(m, opts) for m in maps)

        self.output.setPlainText(self._result_text)
        self.stat_modules.setText(str(stats["modules"]))
        self.stat_classes.setText(str(stats["classes"]))
        self.stat_funcs.setText(str(stats["functions"]))
        self.stat_issues.setText(str(stats["issues"]))
        self.stat_errors.setText(str(stats["errors"]))

        checked = len(self.file_tree.checked_files())
        self.btn_scan.setEnabled(checked > 0)
        self.btn_save.setEnabled(bool(self._result_text))
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.lbl_progress.setText("Done")
        self.status.showMessage(
            f"Done — {stats['modules']} modules, {stats['classes']} classes, "
            f"{stats['functions']} functions"
            + (f", ⚠ {stats['issues']} issue(s)" if stats["issues"] else "")
        )

    def _on_error(self, msg: str):
        self.output.setPlainText(f"[Error]\n{msg}")
        self.btn_scan.setEnabled(len(self.file_tree.checked_files()) > 0)
        self.status.showMessage(f"Error: {msg}")

    def _save_file(self):
        fmt = self.fmt_combo.currentText().lower()
        ext = "json" if fmt == "json" else "txt"
        default = str(Path(self._root_dir or ".") / f"radar_report.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Report", default,
            f"{'JSON' if fmt == 'json' else 'Text'} files (*.{ext});;All files (*)",
        )
        if path:
            Path(path).write_text(self._result_text, encoding="utf-8")
            self.status.showMessage(f"Saved → {path}")


# ==========================================
# 12. ENTRY POINT
# ==========================================

def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor("#0f1117"))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor("#e2e8f0"))
    pal.setColor(QPalette.ColorRole.Base,            QColor("#0a0d14"))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor("#0d1320"))
    pal.setColor(QPalette.ColorRole.Text,            QColor("#e2e8f0"))
    pal.setColor(QPalette.ColorRole.Button,          QColor("#1e293b"))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor("#e2e8f0"))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor("#1d4ed8"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
