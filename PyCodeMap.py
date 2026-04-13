# -*- coding: utf-8 -*-
"""
PyCodeMap: Python AST Code Map Generator — PySide6 GUI
Scans selected Python files and produces an LLM-ready code map.

Copyright (c) 2026 opticsWolf

SPDX-License-Identifier: Apache-2.0
"""

import ast
import sys
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QProgressBar,
    QFrame, QSplitter, QStatusBar, QComboBox, QCheckBox,
    QSizePolicy, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QPalette


# ─────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────

@dataclass
class FunctionInfo:
    name: str
    lineno: int
    args: list
    decorators: list
    docstring: Optional[str]
    calls: list = field(default_factory=list)
    is_async: bool = False


@dataclass
class ClassInfo:
    name: str
    lineno: int
    bases: list
    docstring: Optional[str]
    methods: list = field(default_factory=list)


@dataclass
class ModuleMap:
    path: str
    docstring: Optional[str]
    imports: list
    functions: list
    classes: list
    globals: list


# ─────────────────────────────────────────────
#  AST visitor
# ─────────────────────────────────────────────

class CodeMapVisitor(ast.NodeVisitor):
    def __init__(self):
        self.imports: list = []
        self.functions: list = []
        self.classes: list = []
        self.globals: list = []
        self._current_class: Optional[ClassInfo] = None

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        cls = ClassInfo(
            name=node.name,
            lineno=node.lineno,
            bases=[ast.unparse(b) for b in node.bases],
            docstring=ast.get_docstring(node),
        )
        prev = self._current_class
        self._current_class = cls
        self.generic_visit(node)
        self._current_class = prev
        self.classes.append(cls)

    def _visit_func(self, node):
        calls = list({
            ast.unparse(n.func)
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and hasattr(n, "func")
        })
        fn = FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            args=[a.arg for a in node.args.args],
            decorators=[ast.unparse(d) for d in node.decorator_list],
            docstring=ast.get_docstring(node),
            calls=calls,
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )
        if self._current_class:
            self._current_class.methods.append(fn)
        else:
            self.functions.append(fn)

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def visit_Assign(self, node):
        if self._current_class is None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.globals.append(target.id)
        self.generic_visit(node)


def build_module_map(filepath: str) -> ModuleMap:
    source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(source)
    visitor = CodeMapVisitor()
    visitor.visit(tree)
    return ModuleMap(
        path=filepath,
        docstring=ast.get_docstring(tree),
        imports=visitor.imports,
        functions=visitor.functions,
        classes=visitor.classes,
        globals=visitor.globals,
    )


# ─────────────────────────────────────────────
#  Serialisers
# ─────────────────────────────────────────────

def to_text(m: ModuleMap) -> str:
    lines = [f"## Module: {m.path}"]
    if m.docstring:
        lines.append(f'  Purpose: {m.docstring.splitlines()[0]}')
    if m.imports:
        lines.append(f"  Imports: {', '.join(m.imports)}")
    if m.globals:
        lines.append(f"  Globals: {', '.join(m.globals)}")

    for cls in m.classes:
        bases = f"({', '.join(cls.bases)})" if cls.bases else ""
        lines.append(f"\n  class {cls.name}{bases}  [line {cls.lineno}]")
        if cls.docstring:
            lines.append(f'    "{cls.docstring.splitlines()[0]}"')
        for fn in cls.methods:
            prefix = "async " if fn.is_async else ""
            decs = "".join(f"@{d} " for d in fn.decorators)
            lines.append(f"    {decs}{prefix}def {fn.name}({', '.join(fn.args)})")
            if fn.docstring:
                lines.append(f'      "{fn.docstring.splitlines()[0]}"')
            if fn.calls:
                lines.append(f"      calls: {', '.join(fn.calls[:6])}")

    for fn in m.functions:
        prefix = "async " if fn.is_async else ""
        decs = "".join(f"@{d} " for d in fn.decorators)
        lines.append(f"\n  {decs}{prefix}def {fn.name}({', '.join(fn.args)})  [line {fn.lineno}]")
        if fn.docstring:
            lines.append(f'    "{fn.docstring.splitlines()[0]}"')
        if fn.calls:
            lines.append(f"    calls: {', '.join(fn.calls[:6])}")

    return "\n".join(lines)


def _fn_to_dict(fn: FunctionInfo) -> dict:
    return {
        "name": fn.name, "line": fn.lineno,
        "args": fn.args, "decorators": fn.decorators,
        "docstring": fn.docstring, "calls": fn.calls,
        "async": fn.is_async,
    }


def to_json(m: ModuleMap) -> dict:
    return {
        "path": m.path,
        "docstring": m.docstring,
        "imports": m.imports,
        "globals": m.globals,
        "functions": [_fn_to_dict(f) for f in m.functions],
        "classes": [
            {
                "name": c.name, "line": c.lineno,
                "bases": c.bases, "docstring": c.docstring,
                "methods": [_fn_to_dict(f) for f in c.methods],
            }
            for c in m.classes
        ],
    }


EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", "env", ".git", "node_modules",
                "dist", "build", ".mypy_cache", ".pytest_cache"}


# ─────────────────────────────────────────────
#  Worker thread  (takes an explicit file list)
# ─────────────────────────────────────────────

class ScanWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(list, dict)
    error = Signal(str)

    def __init__(self, files: list, include_calls: bool):
        super().__init__()
        self.files = files
        self.include_calls = include_calls

    def run(self):
        try:
            total = len(self.files)
            maps = []
            stats = {"modules": 0, "classes": 0, "functions": 0, "errors": 0}

            for i, fp in enumerate(self.files):
                self.progress.emit(i + 1, total, Path(fp).name)
                try:
                    m = build_module_map(fp)
                    if not self.include_calls:
                        for fn in m.functions:
                            fn.calls = []
                        for cls in m.classes:
                            for fn in cls.methods:
                                fn.calls = []
                    maps.append(m)
                    stats["modules"] += 1
                    stats["classes"] += len(m.classes)
                    stats["functions"] += len(m.functions) + sum(
                        len(c.methods) for c in m.classes)
                except SyntaxError:
                    stats["errors"] += 1

            self.finished.emit(maps, stats)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────
#  File tree widget with shift-click support
# ─────────────────────────────────────────────

class FileTreeWidget(QTreeWidget):
    """
    QTreeWidget showing .py files grouped by directory.

    Features
    --------
    - Every item has a checkbox; folder checkboxes auto-cascade (tristate)
    - Shift+click: range-check all file leaves between last click and current
    - selection_changed(checked, total) signal for live counter updates
    """

    selection_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_clicked_leaf: Optional[QTreeWidgetItem] = None
        self._updating = False
        self.itemChanged.connect(self._on_item_changed)
        # We handle selection-highlighting ourselves; disable Qt's default
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    # ── Public API ───────────────────────────────────────────────────────────

    def populate(self, root_dir: str):
        """Discover .py files under root_dir and fill the tree (all checked)."""
        self._updating = True
        self.clear()
        self._last_clicked_leaf = None
        root = Path(root_dir)

        all_files = sorted([
            p for p in root.rglob("*.py")
            if not any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts)
        ])

        # dir_items maps an absolute Path → its QTreeWidgetItem
        dir_items: dict = {}

        for fp in all_files:
            rel = fp.relative_to(root)
            parent_item = self.invisibleRootItem()

            # Build (or reuse) every ancestor folder node
            accumulated = root
            for part in rel.parts[:-1]:
                accumulated = accumulated / part
                if accumulated not in dir_items:
                    folder_item = QTreeWidgetItem(parent_item, [part])
                    folder_item.setFlags(
                        folder_item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsAutoTristate
                    )
                    folder_item.setCheckState(0, Qt.CheckState.Checked)
                    # UserRole = None  →  marks this as a directory node
                    folder_item.setData(0, Qt.ItemDataRole.UserRole, None)
                    dir_items[accumulated] = folder_item
                parent_item = dir_items[accumulated]

            # File leaf node
            leaf = QTreeWidgetItem(parent_item, [fp.name])
            leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.CheckState.Checked)
            # UserRole = absolute path string  →  marks this as a file leaf
            leaf.setData(0, Qt.ItemDataRole.UserRole, str(fp))

        self.expandAll()
        self._updating = False
        self._emit_counts()

    def checked_files(self) -> list:
        """Return absolute paths of all checked file leaves."""
        out: list = []
        self._collect_checked(self.invisibleRootItem(), out)
        return out

    def set_all(self, state: Qt.CheckState):
        """Check or uncheck every item in the tree."""
        self._updating = True
        self._set_subtree(self.invisibleRootItem(), state)
        self._updating = False
        self._emit_counts()

    def invert(self):
        """Flip the checked state of every file leaf."""
        self._updating = True
        self._invert_leaves(self.invisibleRootItem())
        self._updating = False
        self._emit_counts()

    # ── Mouse override for shift-click range select ──────────────────────────

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item and event.button() == Qt.MouseButton.LeftButton:
            is_leaf = item.data(0, Qt.ItemDataRole.UserRole) is not None
            if is_leaf:
                if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        and self._last_clicked_leaf is not None):
                    self._range_toggle(self._last_clicked_leaf, item)
                    self._last_clicked_leaf = item
                    return          # we handled it; don't call super
                else:
                    self._last_clicked_leaf = item
        super().mousePressEvent(event)

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int):
        if not self._updating:
            self._emit_counts()

    def _emit_counts(self):
        leaves: list = []
        self._collect_all_leaves(self.invisibleRootItem(), leaves)
        checked = sum(
            1 for it in leaves if it.checkState(0) == Qt.CheckState.Checked
        )
        self.selection_changed.emit(checked, len(leaves))

    def _collect_checked(self, parent: QTreeWidgetItem, out: list):
        for i in range(parent.childCount()):
            child = parent.child(i)
            path = child.data(0, Qt.ItemDataRole.UserRole)
            if path is not None:                          # leaf
                if child.checkState(0) == Qt.CheckState.Checked:
                    out.append(path)
            else:
                self._collect_checked(child, out)

    def _collect_all_leaves(self, parent: QTreeWidgetItem, out: list):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None:
                out.append(child)
            else:
                self._collect_all_leaves(child, out)

    def _set_subtree(self, parent: QTreeWidgetItem, state: Qt.CheckState):
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            self._set_subtree(child, state)

    def _invert_leaves(self, parent: QTreeWidgetItem):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None:
                new_state = (
                    Qt.CheckState.Unchecked
                    if child.checkState(0) == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                )
                child.setCheckState(0, new_state)
            else:
                self._invert_leaves(child)

    def _leaves_in_order(self) -> list:
        """DFS-ordered flat list of all file leaf items (visual tree order)."""
        result: list = []
        self._leaves_dfs(self.invisibleRootItem(), result)
        return result

    def _leaves_dfs(self, parent: QTreeWidgetItem, out: list):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) is not None:
                out.append(child)
            else:
                self._leaves_dfs(child, out)

    def _range_toggle(self, anchor: QTreeWidgetItem, target: QTreeWidgetItem):
        """
        Toggle all leaves from anchor to target inclusive.
        The target's NEW state (opposite of its current state) is applied to
        the whole range, matching VS Code / file-manager shift-click behaviour.
        """
        leaves = self._leaves_in_order()
        try:
            ia, it = leaves.index(anchor), leaves.index(target)
        except ValueError:
            return
        if ia > it:
            ia, it = it, ia

        # Desired final state = opposite of target's current state
        desired = (
            Qt.CheckState.Unchecked
            if target.checkState(0) == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self._updating = True
        for leaf in leaves[ia: it + 1]:
            leaf.setCheckState(0, desired)
        self._updating = False
        self._emit_counts()


# ─────────────────────────────────────────────
#  Syntax highlighter for the output pane
# ─────────────────────────────────────────────

class MapHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        import re
        self._rules = []

        def rule(pattern, color, bold=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            self._rules.append((re.compile(pattern), fmt))

        rule(r"^## Module:.*",          "#7dd3fc", bold=True)
        rule(r"\bclass\s+\w+",          "#f9a8d4", bold=True)
        rule(r"\b(?:async\s+)?def\s+\w+", "#86efac")
        rule(r"@\w+",                   "#fbbf24")
        rule(r'"[^"]*"',                "#a5b4fc")
        rule(r"\[line \d+\]",           "#6b7280")
        rule(r"\bcalls:.*",             "#94a3b8")
        rule(r"(?:Purpose|Imports|Globals):.*", "#d1d5db")

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ─────────────────────────────────────────────
#  Stylesheet
# ─────────────────────────────────────────────

DARK = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
    font-size: 13px;
}
QLabel#title {
    font-size: 20px; font-weight: 700;
    color: #f8fafc; letter-spacing: 0.5px;
}
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
QPushButton#primary:hover   { background-color: #2563eb; }
QPushButton#primary:pressed { background-color: #1e40af; }
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

/* ── Text / Output pane ── */
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
    font-size: 12px;
    alternate-background-color: #0d1320;
    show-decoration-selected: 0;
    outline: none;
}
QTreeWidget::item          { padding: 3px 4px; border-radius: 3px; }
QTreeWidget::item:hover    { background-color: #182030; }
QTreeWidget::branch        { background: transparent; }

/* ── Progress bar ── */
QProgressBar {
    background-color: #1e293b; border: none;
    border-radius: 4px; height: 6px; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #2563eb, stop:1 #7c3aed);
    border-radius: 4px;
}

/* ── Combo / checkbox ── */
QComboBox {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 5px; padding: 5px 10px; color: #e2e8f0; min-width: 80px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #1e293b; border: 1px solid #334155;
    selection-background-color: #1d4ed8;
}

QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #475569; border-radius: 3px;
    background-color: #1e293b;
}
QCheckBox::indicator:checked { background-color: #2563eb; border-color: #2563eb; }

/* ── Structural frames ── */
QFrame#card    { background-color: #141a25; border: 1px solid #1e293b; border-radius: 8px; }
QFrame#divider { background-color: #1e293b; max-height: 1px; }

/* ── Labels ── */
QLabel#stat      { color: #94a3b8; font-size: 12px; }
QLabel#statval   { color: #38bdf8; font-size: 14px; font-weight: 700; }
QLabel#selfmt    { color: #64748b; font-size: 11px; }
QLabel#panelhead {
    color: #475569; font-size: 10px; font-weight: 700;
    letter-spacing: 1.2px;
}

QStatusBar {
    background-color: #0a0d14; color: #475569;
    border-top: 1px solid #1e293b; font-size: 11px;
}
QSplitter::handle:horizontal { background-color: #1e293b; width: 3px; }
"""


# ─────────────────────────────────────────────
#  Main Window
# ─────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python AST Code Map Generator")
        self.setMinimumSize(1100, 680)
        self._root_dir: Optional[str] = None
        self._result_text: str = ""
        self._thread: Optional[QThread] = None
        self._worker: Optional[ScanWorker] = None
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
        lbl_title = QLabel("AST Code Map"); lbl_title.setObjectName("title")
        lbl_sub = QLabel("Extract structured Python metadata for LLM context")
        lbl_sub.setObjectName("subtitle")
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_sub)
        header.addLayout(title_col)
        header.addStretch()
        header.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox(); self.fmt_combo.addItems(["Text", "JSON"])
        header.addWidget(self.fmt_combo)
        self.chk_calls = QCheckBox("Include call graph"); self.chk_calls.setChecked(True)
        header.addWidget(self.chk_calls)
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
        self.btn_scan = QPushButton("▶  Generate Map"); self.btn_scan.setObjectName("primary")
        self.btn_scan.setFixedWidth(150); self.btn_scan.setEnabled(False)
        self.btn_scan.clicked.connect(self._start_scan)
        cl.addWidget(btn_open); cl.addWidget(self.lbl_path, 1); cl.addWidget(self.btn_scan)
        root_layout.addWidget(card)

        # ── Progress bar ──────────────────────────────────────────────────────
        pr = QHBoxLayout()
        self.progress_bar = QProgressBar(); self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.lbl_progress = QLabel(""); self.lbl_progress.setObjectName("stat")
        self.lbl_progress.setFixedWidth(260)
        pr.addWidget(self.progress_bar); pr.addWidget(self.lbl_progress)
        root_layout.addLayout(pr)

        # ── Main horizontal splitter ──────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        root_layout.addWidget(splitter, 1)

        # ── LEFT: file tree panel ─────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 6, 0); ll.setSpacing(5)

        # Header row
        th = QHBoxLayout()
        lf = QLabel("FILES"); lf.setObjectName("panelhead")
        self.lbl_sel_count = QLabel("—"); self.lbl_sel_count.setObjectName("selfmt")
        self.lbl_sel_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        th.addWidget(lf); th.addStretch(); th.addWidget(self.lbl_sel_count)
        ll.addLayout(th)

        # Bulk-action buttons
        brow = QHBoxLayout(); brow.setSpacing(4)
        for txt, slot in [("Select All", self._sel_all),
                          ("Deselect All", self._sel_none),
                          ("Invert", self._sel_invert)]:
            b = QPushButton(txt); b.setObjectName("sel"); b.setFixedHeight(24)
            b.clicked.connect(slot); brow.addWidget(b)
        brow.addStretch()
        ll.addLayout(brow)

        # Shift-click hint
        hint = QLabel("Shift+click  for range selection")
        hint.setObjectName("selfmt")
        ll.addWidget(hint)

        # Tree
        self.file_tree = FileTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.selection_changed.connect(self._on_tree_changed)
        ll.addWidget(self.file_tree, 1)

        splitter.addWidget(left)

        # ── RIGHT: output panel ───────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(6, 0, 0, 0); rl.setSpacing(5)

        # Header row with inline stats + save button
        oh = QHBoxLayout()
        lo = QLabel("OUTPUT"); lo.setObjectName("panelhead")
        oh.addWidget(lo); oh.addStretch()

        def mini_stat(label):
            col = QVBoxLayout(); col.setSpacing(0)
            v = QLabel("—"); v.setObjectName("statval")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_ = QLabel(label); l_.setObjectName("selfmt")
            l_.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(v); col.addWidget(l_)
            oh.addLayout(col); oh.addSpacing(14)
            return v

        self.stat_modules = mini_stat("modules")
        self.stat_classes = mini_stat("classes")
        self.stat_funcs   = mini_stat("funcs")
        self.stat_errors  = mini_stat("errors")

        self.btn_save = QPushButton("⬇  Save…"); self.btn_save.setObjectName("save")
        self.btn_save.setFixedWidth(100); self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_file)
        oh.addWidget(self.btn_save)
        rl.addLayout(oh)

        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.output.setPlaceholderText(
            "Generated code map will appear here…\n\n"
            "1. Open a folder  →  .py files populate the left panel\n"
            "2. Use checkboxes to include/exclude files:\n"
            "      Click a checkbox to toggle a file or folder\n"
            "      Shift+click to range-check a block of files\n"
            "      Select All / Deselect All / Invert for bulk ops\n"
            "3. Click 'Generate Map'  →  map renders here\n"
            "4. Click 'Save…'  →  export as .txt or .json"
        )
        self.highlighter = MapHighlighter(self.output.document())
        rl.addWidget(self.output, 1)

        splitter.addWidget(right)
        splitter.setSizes([290, 810])

        # ── Status bar ────────────────────────────────────────────────────────
        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Ready — open a folder to begin")

    # ── Tree callbacks ────────────────────────────────────────────────────────

    def _sel_all(self):    self.file_tree.set_all(Qt.CheckState.Checked)
    def _sel_none(self):   self.file_tree.set_all(Qt.CheckState.Unchecked)
    def _sel_invert(self): self.file_tree.invert()

    def _on_tree_changed(self, checked: int, total: int):
        self.lbl_sel_count.setText(f"{checked} / {total} selected")
        can_scan = checked > 0 and self._root_dir is not None
        self.btn_scan.setEnabled(can_scan)

    # ── Folder open ───────────────────────────────────────────────────────────

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Python Project Folder", str(Path.home()))
        if not folder:
            return
        self._root_dir = folder
        self.lbl_path.setText(folder if len(folder) <= 72 else "…" + folder[-69:])
        self.output.clear()
        self._result_text = ""
        self.btn_save.setEnabled(False)
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs, self.stat_errors):
            s.setText("—")
        self.file_tree.populate(folder)
        self.status.showMessage(f"Loaded: {folder}")

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _start_scan(self):
        selected = self.file_tree.checked_files()
        if not selected:
            self.status.showMessage("No files selected — nothing to scan.")
            return

        self.btn_scan.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.output.clear()
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs, self.stat_errors):
            s.setText("…")

        self._thread = QThread()
        self._worker = ScanWorker(selected, self.chk_calls.isChecked())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()
        self.status.showMessage(f"Scanning {len(selected)} file(s)…")

    def _on_progress(self, current: int, total: int, name: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.lbl_progress.setText(f"{current}/{total}  {name}")

    def _on_finished(self, maps: list, stats: dict):
        fmt = self.fmt_combo.currentText().lower()
        if fmt == "json":
            self._result_text = json.dumps([to_json(m) for m in maps], indent=2)
        else:
            self._result_text = "\n\n".join(to_text(m) for m in maps)

        self.output.setPlainText(self._result_text)
        self.stat_modules.setText(str(stats["modules"]))
        self.stat_classes.setText(str(stats["classes"]))
        self.stat_funcs.setText(str(stats["functions"]))
        self.stat_errors.setText(str(stats["errors"]))

        checked = len(self.file_tree.checked_files())
        self.btn_scan.setEnabled(checked > 0)
        self.btn_save.setEnabled(bool(self._result_text))
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.lbl_progress.setText("Done")
        self.status.showMessage(
            f"Done — {stats['modules']} modules, "
            f"{stats['classes']} classes, {stats['functions']} functions"
        )

    def _on_error(self, msg: str):
        self.output.setPlainText(f"[Error]\n{msg}")
        self.btn_scan.setEnabled(len(self.file_tree.checked_files()) > 0)
        self.status.showMessage(f"Error: {msg}")

    def _save_file(self):
        fmt = self.fmt_combo.currentText().lower()
        ext = "json" if fmt == "json" else "txt"
        default = str(Path(self._root_dir or ".") / f"code_map.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Code Map", default,
            f"{'JSON' if fmt == 'json' else 'Text'} files (*.{ext});;All files (*)",
        )
        if path:
            Path(path).write_text(self._result_text, encoding="utf-8")
            self.status.showMessage(f"Saved → {path}")


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
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