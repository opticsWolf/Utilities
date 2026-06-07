# -*- coding: utf-8 -*-
"""Custom Qt widgets: FileTreeWidget and the syntax highlighter for the report pane."""

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from .constants import EXCLUDE_DIRS


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

    # ── Internals ─────────────────────────────────────────────────────────────

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
    """Highlights the analysis report — block-level severity colors plus token rules."""

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
        rule(r"^\s*⚠.*",   "#fca5a5", bold=True, whole_line=True, bg="#3f1d1d")
        rule(r"^\s*📜.*",  "#fde68a", bold=True, whole_line=True, bg="#2d2208")
        rule(r"^\s*🛑.*",  "#ef4444", bold=True, whole_line=True, bg="#450a0a")
        rule(r"^\s*🛡️.*", "#60a5fa", bold=True, whole_line=True, bg="#1e3a8a")
        rule(r"^\s*✎.*",   "#fcd34d",            whole_line=True, bg="#2e2512")
        rule(r"^\s*🔧.*",  "#a7f3d0", bold=True, whole_line=True, bg="#0e2d22")

        # ── Diff highlighting (preview output from ruff --diff) ───────────
        # File markers must come before the +/- rules to avoid bg clash.
        rule(r"^(?:\+\+\+|---) .*",  "#9ca3af", bold=True, whole_line=True, bg="#0d1117")
        rule(r"^@@.*@@.*",            "#7dd3fc", bold=True, whole_line=True, bg="#0b1e2c")
        rule(r"^\+(?!\+\+).*",        "#86efac",            whole_line=True, bg="#0e2316")
        rule(r"^-(?!--).*",           "#fca5a5",            whole_line=True, bg="#2d1414")

        # ── Per-token inline rules ─────────────────────────────────────────
        rule(r"^## Module:.*",                "#7dd3fc", bold=True)
        rule(r"\[MI: [0-9.]+ \([A-F]\)\]",    "#10b981", bold=True)
        rule(r"\bclass\s+\w+",                "#f9a8d4", bold=True)
        rule(r"\b(?:async\s+)?def\s+\w+",     "#86efac")
        rule(r"@\w+",                          "#fbbf24")
        rule(r'"[^"]*"',                       "#a5b4fc")
        rule(r"\[line \d+\]",                  "#6b7280")
        rule(r"\bcalls:.*",                    "#94a3b8")
        rule(r"\braises:.*",                   "#f87171")
        rule(r"(?:Purpose|Imports(?:\s*\[[^\]]+\])?|Globals):.*", "#d1d5db")
        rule(r"->\s*[\w\[\], .|]+",            "#c4b5fd")
        rule(r"\bcc=\d+",                      "#fdba74")
        rule(r"\b\d+L\b",                      "#fdba74")
        rule(r"↪\s+\S+\(\)",                   "#34d399")    # wrapper target

    def highlightBlock(self, text):
        for pattern, fmt in self._block_rules:
            if pattern.match(text):
                self.setFormat(0, len(text), fmt)
                return
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
