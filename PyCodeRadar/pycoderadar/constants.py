# -*- coding: utf-8 -*-
"""Constants and runtime feature detection."""

import shutil
import sys


# ── External tool availability ────────────────────────────────────────────────
HAS_RUFF  = shutil.which("ruff")  is not None
HAS_RADON = shutil.which("radon") is not None
HAS_MYPY  = shutil.which("mypy")  is not None

# ── stdlib set (Python 3.10+) ─────────────────────────────────────────────────
try:
    _STDLIB_MODULES = set(sys.stdlib_module_names)
except AttributeError:
    _STDLIB_MODULES = set()

# Directories to skip when walking a project tree.
EXCLUDE_DIRS = {
    "__pycache__", ".venv", "venv", "env", ".git", "node_modules",
    "dist", "build", ".mypy_cache", ".pytest_cache",
}

# Application identity (used for QSettings / config paths).
APP_NAME    = "PyCodeRadar"
APP_VENDOR  = "opticsWolf"
CONFIG_FILE = "config.json"
