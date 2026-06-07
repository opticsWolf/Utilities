# -*- coding: utf-8 -*-
"""
Strictness presets.

Each preset is a partial dict of ScanOptions overrides applied on top of
ScanOptions() defaults. The dropdown switches between them; "Custom" is a
sentinel meaning "user has tweaked something — don't apply a preset".

Severity ladder (loosely):

    Lenient   — only the bugs that almost always matter
    Standard  — sensible defaults (close to ScanOptions() factory values)
    Strict    — most checks on, mypy --strict, all legacy patterns
    Pedantic  — everything on, tightest thresholds
"""

from dataclasses import fields
from typing import Dict, Any

from .models import ScanOptions
from .constants import HAS_RUFF, HAS_RADON, HAS_MYPY


CUSTOM = "Custom"

# Ordered for a sensible dropdown.
PRESET_ORDER = ["Lenient", "Standard", "Strict", "Pedantic", CUSTOM]


# ── Preset definitions ────────────────────────────────────────────────────────
# Each preset only specifies the fields it cares about; everything else stays
# at the dataclass default.

_PRESETS: Dict[str, Dict[str, Any]] = {

    "Lenient": dict(
        # tracking — keep informative output minimal
        include_calls=True,
        track_line_counts=True,
        track_complexity=False,
        track_return_types=False,
        track_annotations=False,
        track_exceptions=False,
        track_import_categories=False,
        track_todos=True,
        track_wrappers=False,

        # anti-patterns — only the genuinely dangerous ones
        detect_wildcard=True,
        detect_duplicate_imports=True,
        detect_unused_imports=False,
        detect_mutable_defaults=True,
        detect_bare_except=True,
        detect_long_functions=False,
        detect_too_many_args=False,
        detect_god_classes=False,
        detect_print=False,
        detect_exec_eval=True,

        # legacy — off
        detect_percent_format=False,
        detect_super_args=False,
        detect_type_comments=False,

        # external tools — off by default (heavy)
        run_ruff_analysis=False,
        run_radon_analysis=False,
        run_mypy_analysis=False,

        # mypy strictness (irrelevant when off, but keep coherent)
        mypy_strict=False,
        mypy_ignore_missing_imports=True,
        mypy_show_errors=True,
        mypy_show_warnings=False,
        mypy_show_notes=False,

        # thresholds — generous
        long_function_threshold=100,
        max_args=8,
        god_class_threshold=25,
    ),

    "Standard": dict(
        # exact ScanOptions() defaults — see models.py
        include_calls=True,
        track_line_counts=True,
        track_complexity=True,
        track_return_types=True,
        track_annotations=False,
        track_exceptions=False,
        track_import_categories=False,
        track_todos=True,
        track_wrappers=True,

        detect_wildcard=True,
        detect_duplicate_imports=True,
        detect_unused_imports=False,
        detect_mutable_defaults=True,
        detect_bare_except=True,
        detect_long_functions=True,
        detect_too_many_args=True,
        detect_god_classes=True,
        detect_print=False,
        detect_exec_eval=True,

        detect_percent_format=False,
        detect_super_args=False,
        detect_type_comments=False,

        run_ruff_analysis=HAS_RUFF,
        run_radon_analysis=HAS_RADON,
        run_mypy_analysis=HAS_MYPY,

        mypy_strict=False,
        mypy_no_implicit_optional=True,
        mypy_ignore_missing_imports=True,
        mypy_show_errors=True,
        mypy_show_warnings=True,
        mypy_show_notes=False,

        long_function_threshold=50,
        max_args=5,
        god_class_threshold=15,
    ),

    "Strict": dict(
        # tracking — show everything useful
        include_calls=True,
        track_line_counts=True,
        track_complexity=True,
        track_return_types=True,
        track_annotations=True,
        track_exceptions=True,
        track_import_categories=True,
        track_todos=True,
        track_wrappers=True,

        # anti-patterns — full sweep, including unused imports
        detect_wildcard=True,
        detect_duplicate_imports=True,
        detect_unused_imports=True,
        detect_mutable_defaults=True,
        detect_bare_except=True,
        detect_long_functions=True,
        detect_too_many_args=True,
        detect_god_classes=True,
        detect_print=False,
        detect_exec_eval=True,

        # legacy — all on
        detect_percent_format=True,
        detect_super_args=True,
        detect_type_comments=True,

        # external tools
        run_ruff_analysis=HAS_RUFF,
        run_radon_analysis=HAS_RADON,
        run_mypy_analysis=HAS_MYPY,

        # mypy --strict — implies all individual flags
        mypy_strict=True,
        mypy_ignore_missing_imports=True,
        mypy_show_errors=True,
        mypy_show_warnings=True,
        mypy_show_notes=False,

        # thresholds — tighter
        long_function_threshold=40,
        max_args=4,
        god_class_threshold=12,
    ),

    "Pedantic": dict(
        # everything on, tightest knobs
        include_calls=True,
        track_line_counts=True,
        track_complexity=True,
        track_return_types=True,
        track_annotations=True,
        track_exceptions=True,
        track_import_categories=True,
        track_todos=True,
        track_wrappers=True,

        detect_wildcard=True,
        detect_duplicate_imports=True,
        detect_unused_imports=True,
        detect_mutable_defaults=True,
        detect_bare_except=True,
        detect_long_functions=True,
        detect_too_many_args=True,
        detect_god_classes=True,
        detect_print=True,
        detect_exec_eval=True,

        detect_percent_format=True,
        detect_super_args=True,
        detect_type_comments=True,

        run_ruff_analysis=HAS_RUFF,
        run_radon_analysis=HAS_RADON,
        run_mypy_analysis=HAS_MYPY,

        mypy_strict=True,
        mypy_ignore_missing_imports=False,    # don't hide missing stubs
        mypy_show_errors=True,
        mypy_show_warnings=True,
        mypy_show_notes=True,                  # surface notes too

        long_function_threshold=30,
        max_args=3,
        god_class_threshold=10,
    ),
}


# ── Public helpers ────────────────────────────────────────────────────────────

def get_preset_names() -> list:
    """Return the preset names in dropdown order. 'Custom' is included last."""
    return list(PRESET_ORDER)


def apply_preset(name: str) -> ScanOptions:
    """
    Build a ScanOptions instance for the given preset name.

    Unknown names (including 'Custom') return a default ScanOptions() — for
    'Custom' this is by design: the caller should overlay the user's existing
    widget state instead of calling apply_preset().
    """
    overrides = _PRESETS.get(name, {})
    opts = ScanOptions()
    for key, value in overrides.items():
        if hasattr(opts, key):
            setattr(opts, key, value)
    return opts


def detect_preset(opts: ScanOptions) -> str:
    """
    Reverse-lookup: which preset (if any) does the given ScanOptions match?

    Returns the preset name on exact match, else 'Custom'. Useful when loading
    persisted config — the dropdown should show the right label.
    """
    snapshot = {f.name: getattr(opts, f.name) for f in fields(opts)}
    for name, overrides in _PRESETS.items():
        # All fields specified by the preset must match; unspecified fields
        # are ignored (they take their dataclass default and the preset is
        # agnostic about them).
        if all(snapshot.get(k) == v for k, v in overrides.items()):
            # Additionally, fields NOT in the preset must equal ScanOptions()
            # defaults — otherwise the user has clearly diverged.
            defaults = ScanOptions()
            untouched_match = all(
                snapshot[f.name] == getattr(defaults, f.name)
                for f in fields(opts)
                if f.name not in overrides
            )
            if untouched_match:
                return name
    return CUSTOM
