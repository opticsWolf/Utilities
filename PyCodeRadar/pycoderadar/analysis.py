# -*- coding: utf-8 -*-
"""
Static AST analysis: helpers, the visitor that walks a module, and the
module-builder that wires everything together into a ModuleMap.
"""

import ast
import re
from pathlib import Path
from typing import Optional

from .constants import _STDLIB_MODULES
from .models import (
    AntiPattern, ClassInfo, FunctionInfo, ImportInfo, ModuleMap, ScanOptions,
)


# ==========================================
# Helpers
# ==========================================

def _categorize_imports(imports: list) -> dict:
    """Bucket imports into stdlib / third-party / local (relative)."""
    stdlib, third, local = [], [], []
    for imp in imports:
        if imp.from_module and imp.from_module.startswith('.'):
            local.append(imp.raw); continue
        top = (imp.from_module or imp.local_name or imp.raw).split('.')[0].split(' ')[0]
        if not top:                  local.append(imp.raw)
        elif top in _STDLIB_MODULES: stdlib.append(imp.raw)
        else:                        third.append(imp.raw)
    return {"stdlib": stdlib, "third_party": third, "local": local}


_COMPLEXITY_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While,
    ast.IfExp, ast.Assert,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)


def _cyclomatic_complexity(node: ast.AST) -> int:
    """Approximate McCabe CC via decision-point counting."""
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
    """Return a label like 'list' / 'dict()' if `node` is a mutable default."""
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
    total. Returns (is_wrapper: bool, target: str | None).
    """
    body = node.body  # type: ignore[attr-defined]
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
# AST visitor
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
        opts      = self.opts
        line_end  = getattr(node, "end_lineno", None)
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


# ==========================================
# Module builder
# ==========================================

_TODO_RE         = re.compile(r'#\s*(TODO|FIXME|XXX|HACK|NOTE)\b[:\s]?(.*)', re.IGNORECASE)
_TYPE_COMMENT_RE = re.compile(r'#\s*type:\s+(?!ignore\b)')   # skip "# type: ignore"


def build_module_map(filepath: str, opts: ScanOptions) -> ModuleMap:
    """Parse a single .py file and return a fully populated ModuleMap."""
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
