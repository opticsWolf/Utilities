"""
UV Project Management Pane

Merged implementation combining the best features from three upstream versions.
Includes:
- Project folder as QLineEdit with folder/file pickers.
- Wide refresh button with label.
- Initialize button placed below project name.
- Combined "Python & Environment" collapsible group:
    * Python version label, line edit, two square buttons (🐍 apply, 🔍 detect from env)
    * Three horizontal buttons: Lock Dependencies (🔒), Sync Environment (⚡), Export requirements.txt (📄 square)
- Dependency management, run, build, publish sections.
- Full settings persistence.
- uv version check, pyproject.toml parsing, console scripts display.
- **Auto‑detect dependencies from imports** (AST) with dev‑dependency detection (tests/ folders, conftest.py, *_test.py).
"""

from .mixin import UvProjectMixin
from .scanner import DependencyScannerThread
from .dialogs import DependencyUpdateDialog

__all__ = ["UvProjectMixin", "DependencyScannerThread", "DependencyUpdateDialog"]