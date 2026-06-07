# -*- coding: utf-8 -*-
"""Render ModuleMap objects to either human-readable text or JSON-friendly dicts."""

from .external_tools import build_mypy_cmd
from .models import FunctionInfo, ModuleMap, ScanOptions


def _fn_extras(fn: FunctionInfo, opts: ScanOptions) -> str:
    """Inline extras string: line counts, complexity, wrapper indicator."""
    bits = []
    if opts.track_line_counts and fn.num_lines:
        bits.append(f"{fn.num_lines}L")
    if opts.track_complexity:
        bits.append(f"cc={fn.complexity}")
    meta = f"  ({', '.join(bits)})" if bits else ""
    wrap = (
        f"  ↪ {fn.wrapper_target}()"
        if (opts.track_wrappers and fn.is_wrapper and fn.wrapper_target) else ""
    )
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
        bases   = f"({', '.join(cls.bases)})" if cls.bases else ""
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
    if opts.run_mypy_analysis:
        out["mypy_cmd"] = build_mypy_cmd(opts)
    return out
