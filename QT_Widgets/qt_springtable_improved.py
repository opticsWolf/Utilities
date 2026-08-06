# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
PADDOL: Python Advanced Design & Dispersion Optimization Lab
Copyright (c) 2025 opticsWolf

SPDX-License-Identifier: LGPL-3.0-or-later

Consolidated Spring Table Module
=================================
Provides high-performance Qt table components with proportional column resizing,
a "spring" column that fills remaining viewport space, persistent layout state,
and support for both QTableView (model/view) and QTableWidget paradigms.

Classes:
    NumpyTableModel    - NumPy-backed QAbstractTableModel with sort & drag/drop.
    SpringTableView    - QTableView with spring column, proportional resize, persistence.
    SpringTableWidget  - QTableWidget with spring column, proportional resize, persistence.
"""

import sys
import json
import logging
import numpy as np
from typing import Any, Literal, Optional
from pathlib import Path
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QMimeData,
    QByteArray, QDataStream, QIODevice,
)
from PySide6.QtGui import QResizeEvent, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QTableView, QHeaderView, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QPushButton, QHBoxLayout,
    QAbstractItemView, QLabel, QFrame, QMessageBox,
)

logger = logging.getLogger(__name__)

# ============================================================================
# 1. The High-Performance Model
# ============================================================================
class NumpyTableModel(QAbstractTableModel):
    """
    A high-performance Qt table model backed by a NumPy array.

    Supports column sorting (stable, with mixed-type fallback), row reordering
    via drag-and-drop with MIME encoding, and in-place cell editing.

    Args:
        data:    2D NumPy array (dtype=object recommended for mixed types).
        headers: Column header labels.
    """

    MIME_TYPE = "application/x-paddol-row"

    def __init__(self, data: np.ndarray, headers: list[str]) -> None:
        super().__init__()
        self._data = data
        self._headers = list(headers)

    # -- Properties ----------------------------------------------------------

    @property
    def raw_data(self) -> np.ndarray:
        """Direct read-only access to the backing array."""
        return self._data

    # -- Header management ---------------------------------------------------

    def set_headers(self, headers: list[str]) -> None:
        """Replace column headers and notify attached views."""
        self._headers = list(headers)
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(headers) - 1
        )

    # -- QAbstractTableModel interface ---------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return self._data.shape[0]

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return self._data.shape[1]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            val = self._data[index.row(), index.column()]
            # Convert numpy scalars to native Python types for Qt display
            if hasattr(val, "item"):
                return val.item()
            return str(val) if val is not None else ""
        return None

    def setData(
        self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        if index.isValid() and role == Qt.ItemDataRole.EditRole:
            self._data[index.row(), index.column()] = value
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def headerData(
        self, section: int, orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._headers[section] if section < len(self._headers) else str(section)
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )

    # -- Sorting -------------------------------------------------------------

    def sort(self, column: int, order: Qt.SortOrder) -> None:
        """
        Sort rows by *column* using a stable algorithm.

        Falls back to lexicographic (string) comparison when the column
        contains mixed types that NumPy cannot compare natively.
        """
        self.layoutAboutToBeChanged.emit()
        try:
            indices = np.argsort(self._data[:, column], kind="stable")
        except TypeError:
            indices = np.argsort(self._data[:, column].astype(str), kind="stable")
        if order == Qt.SortOrder.DescendingOrder:
            indices = indices[::-1]
        self._data = self._data[indices]
        self.layoutChanged.emit()

    # -- Drag & drop ---------------------------------------------------------

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [self.MIME_TYPE]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        buf = QByteArray()
        stream = QDataStream(buf, QIODevice.OpenModeFlag.WriteOnly)
        if indexes:
            stream.writeInt32(indexes[0].row())
        mime.setData(self.MIME_TYPE, buf)
        return mime

    def dropMimeData(
        self, data: QMimeData, action: Qt.DropAction,
        row: int, column: int, parent: QModelIndex,
    ) -> bool:
        if not data.hasFormat(self.MIME_TYPE):
            return False
        if action == Qt.DropAction.IgnoreAction:
            return True

        stream = QDataStream(data.data(self.MIME_TYPE), QIODevice.OpenModeFlag.ReadOnly)
        src_row = stream.readInt32()
        dst_row = row if row != -1 else (parent.row() if parent.isValid() else self.rowCount())

        if src_row == dst_row:
            return False

        self.beginMoveRows(QModelIndex(), src_row, src_row, QModelIndex(), dst_row)
        row_data = self._data[src_row].copy()
        self._data = np.delete(self._data, src_row, axis=0)
        insert_idx = dst_row if src_row > dst_row else dst_row - 1
        self._data = np.insert(self._data, insert_idx, row_data, axis=0)
        self.endMoveRows()
        return True

    # -- Bulk operations -----------------------------------------------------

    def reset_data(self, data: np.ndarray) -> None:
        """Replace the entire dataset and reset the model."""
        self.beginResetModel()
        self._data = data
        self.endResetModel()

    def reorder_rows(self, new_indices: list[int] | np.ndarray) -> None:
        """
        Reorder rows according to *new_indices*.

        Raises:
            ValueError: If len(new_indices) != rowCount().
        """
        if len(new_indices) != self.rowCount():
            raise ValueError(
                f"Index length {len(new_indices)} does not match row count {self.rowCount()}."
            )
        self.layoutAboutToBeChanged.emit()
        self._data = self._data[np.asarray(new_indices, dtype=int)]
        self.layoutChanged.emit()


# ============================================================================
# 2. Spring Column Mixin  (shared logic for View and Widget)
# ============================================================================
class _SpringColumnMixin:
    """
    Mixin that adds spring-column behaviour, proportional resize logic,
    column constraint enforcement, drag-lock for non-draggable columns,
    and JSON layout persistence.

    The "spring column" is always the *last visual column*; it automatically
    expands or contracts so that columns fill the viewport exactly.

    Must be mixed into a class that inherits from QTableView or QTableWidget.
    """

    # -- Mixin initialiser (call from subclass __init__) ---------------------

    def _init_spring(
        self,
        enable_sorting: bool,
        enable_row_drag_drop: bool,
        show_headers: bool,
        show_row_labels: bool,
        alternating_rows: bool,
        alternate_color: str | QColor | Literal["lighter", "darker"] | None,
        rows_resizable: bool,
    ) -> None:
        # Column constraints
        self._min_widths: dict[int, int] = {}
        self._max_widths: dict[int, int] = {}
        self._draggable_column_indices: set[int] = set()

        # State
        self._saved_state: QByteArray | None = None
        self._default_state: QByteArray | None = None
        self._is_initialized: bool = False
        self._is_resizing: bool = False

        # Visual setup
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(alternating_rows)
        if alternating_rows and alternate_color:
            self.set_alternating_color(alternate_color)

        self.horizontalHeader().setVisible(show_headers)
        self.verticalHeader().setVisible(show_row_labels)

        # Header configuration
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(False)
        h.setSectionsMovable(True)
        h.setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        # Row height
        v_mode = QHeaderView.ResizeMode.Interactive if rows_resizable else QHeaderView.ResizeMode.Fixed
        self.verticalHeader().setSectionResizeMode(v_mode)

        # Signals
        h.sectionResized.connect(self._on_column_resized)
        h.sectionMoved.connect(self._on_column_moved)

        # Initial mode
        if enable_row_drag_drop:
            self.switch_to_drag()
        else:
            self.switch_to_sort()
            if not enable_sorting:
                self.setSortingEnabled(False)

    # -- Mode switching ------------------------------------------------------

    def switch_to_sort(self) -> None:
        """Enable column sorting; disable row drag-and-drop."""
        self._set_drag_drop(False)
        h = self.horizontalHeader()
        if h.sortIndicatorSection() == -1:
            h.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        h.setSectionsClickable(True)

    def switch_to_drag(self) -> None:
        """Enable row drag-and-drop; disable sorting."""
        self._set_drag_drop(True)

    def _set_drag_drop(self, enable: bool) -> None:
        self.setDragEnabled(enable)
        self.setAcceptDrops(enable)
        if enable:
            self.setSortingEnabled(False)
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDragDropOverwriteMode(False)
            self.setDropIndicatorShown(True)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    # -- Column configuration ------------------------------------------------

    def configure_columns(self, config: list[dict[str, Any]]) -> None:
        """
        Apply per-column settings from a list of dicts.

        Each dict may contain:
            label      (str)  : Column header text.
            min_width  (int)  : Minimum column width in pixels.
            max_width  (int)  : Maximum column width in pixels.
            draggable  (bool) : Whether the column can be reordered (default True).

        The method delegates header-label updates to whichever mechanism is
        appropriate for the concrete class (model.set_headers for QTableView,
        setHorizontalHeaderLabels for QTableWidget).
        """
        self._draggable_column_indices.clear()
        self._min_widths.clear()
        self._max_widths.clear()

        col_count = self._get_column_count()
        labels: list[str] = []

        for i in range(col_count):
            cfg = config[i] if i < len(config) else {}
            labels.append(cfg.get("label", self._current_header_text(i)))
            if "min_width" in cfg:
                self._min_widths[i] = cfg["min_width"]
            if "max_width" in cfg:
                self._max_widths[i] = cfg["max_width"]
            if cfg.get("draggable", True):
                self._draggable_column_indices.add(i)

        self._apply_header_labels(labels)

        if self.isVisible():
            self._recalculate_widths_ratio(1.0)

    # -- Alternating row color -----------------------------------------------

    def set_alternating_color(
        self, color_spec: str | QColor | Literal["lighter", "darker"]
    ) -> None:
        """
        Set the alternate-row background colour.

        Accepts ``"lighter"`` / ``"darker"`` (derived from the current base),
        a hex string, or a ``QColor`` instance.
        """
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        if color_spec == "lighter":
            target = base.lighter(110)
        elif color_spec == "darker":
            target = base.darker(105)
        elif isinstance(color_spec, (str, QColor)):
            target = QColor(color_spec)
        else:
            return
        if target.isValid():
            palette.setColor(QPalette.ColorRole.AlternateBase, target)
            self.setPalette(palette)

    # -- In-memory layout persistence ----------------------------------------

    def save_layout(self) -> None:
        """Snapshot the current header state (widths + order) into memory."""
        self._saved_state = self.horizontalHeader().saveState()

    def restore_layout(self) -> None:
        """Restore a previously saved header snapshot."""
        if self._saved_state:
            self.horizontalHeader().restoreState(self._saved_state)
            self._update_spring_column()

    def reset_table(self) -> None:
        """Restore the factory-default header state captured on first show."""
        if self._default_state:
            self.horizontalHeader().restoreState(self._default_state)
            self._update_spring_column()

    # -- JSON file persistence -----------------------------------------------

    def save_state_to_file(self, filepath: str | Path) -> None:
        """
        Persist column widths and visual ordering to a JSON file.

        Args:
            filepath: Destination file path.
        """
        header = self.horizontalHeader()
        state = {
            "columns": [
                {
                    "logical_index": i,
                    "width": self.columnWidth(i),
                    "visual_index": header.visualIndex(i),
                }
                for i in range(header.count())
            ]
        }
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=4)
            logger.info("State saved to %s", filepath)
        except OSError:
            logger.exception("Failed to save state to %s", filepath)

    def load_state_from_file(self, filepath: str | Path) -> None:
        """
        Restore column widths and ordering from a JSON file.

        Args:
            filepath: Source file path.
        """
        path = Path(filepath)
        if not path.exists():
            logger.warning("Layout file not found: %s", filepath)
            return

        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to load state from %s", filepath)
            return

        columns = state.get("columns", [])
        if not columns:
            return

        header = self.horizontalHeader()
        self._is_resizing = True
        header.blockSignals(True)

        # 1. Restore widths
        for col in columns:
            idx = col["logical_index"]
            if idx < header.count():
                self.setColumnWidth(idx, col["width"])

        # 2. Restore visual ordering
        for visual_pos, col in enumerate(sorted(columns, key=lambda c: c["visual_index"])):
            current = header.visualIndex(col["logical_index"])
            if current != visual_pos:
                header.moveSection(current, visual_pos)

        header.blockSignals(False)
        self._is_resizing = False
        self._update_spring_column()
        logger.info("State loaded from %s", filepath)

    # -- Qt event overrides --------------------------------------------------

    def _spring_show_event(self, event) -> None:
        """Call from subclass showEvent *after* super().showEvent(event)."""
        if not self._is_initialized:
            self._default_state = self.horizontalHeader().saveState()
            if self._saved_state is None:
                self.save_layout()
            self._is_initialized = True
        self._update_spring_column()

    def _spring_resize_event(self, event: QResizeEvent) -> None:
        """Call from subclass resizeEvent *after* super().resizeEvent(event)."""
        old_w = event.oldSize().width()
        new_w = event.size().width()
        if new_w <= 0:
            return
        if old_w <= 0:
            self._update_spring_column()
            return
        self._recalculate_widths_ratio(new_w / old_w)

    # -- Internal slots & helpers --------------------------------------------

    def _on_column_moved(self, logical: int, old_visual: int, new_visual: int) -> None:
        """Revert moves for non-draggable columns; recalculate spring otherwise."""
        if logical not in self._draggable_column_indices:
            h = self.horizontalHeader()
            h.blockSignals(True)
            h.moveSection(new_visual, old_visual)
            h.blockSignals(False)
        else:
            self._update_spring_column()

    def _on_column_resized(self, logical: int, old_size: int, new_size: int) -> None:
        """Enforce min/max constraints and recalculate the spring column."""
        if self._is_resizing:
            return

        # Skip manual resize of the spring column itself
        header = self.horizontalHeader()
        last_logical = header.logicalIndex(header.count() - 1)
        if logical == last_logical:
            return

        min_w = self._min_widths.get(logical, 30)
        max_w = self._max_widths.get(logical, 999_999)
        corrected = max(min_w, min(new_size, max_w))

        if corrected != new_size:
            header.blockSignals(True)
            self.setColumnWidth(logical, corrected)
            header.blockSignals(False)

        self._update_spring_column()

    def _update_spring_column(self) -> None:
        """Resize the last visual column to fill remaining viewport space."""
        if self._is_resizing:
            return
        header = self.horizontalHeader()
        count = header.count()
        if count == 0:
            return

        last_visual = count - 1
        last_logical = header.logicalIndex(last_visual)
        used = sum(
            self.columnWidth(header.logicalIndex(i))
            for i in range(count) if i != last_visual
        )
        desired = max(self._min_widths.get(last_logical, 0), self.viewport().width() - used)

        if self.columnWidth(last_logical) != desired:
            self._is_resizing = True
            header.blockSignals(True)
            self.setColumnWidth(last_logical, desired)
            header.blockSignals(False)
            self._is_resizing = False

    def _recalculate_widths_ratio(self, ratio: float) -> None:
        """Scale all non-spring columns by *ratio*, respecting constraints."""
        header = self.horizontalHeader()
        count = header.count()
        if count == 0:
            return

        self._is_resizing = True
        header.blockSignals(True)
        rounding_acc = 0.0

        for i in range(count - 1):
            logical = header.logicalIndex(i)
            target = self.columnWidth(logical) * ratio + rounding_acc
            new_w = int(round(target))

            min_w = self._min_widths.get(logical, 30)
            max_w = self._max_widths.get(logical, 999_999)
            new_w = max(min_w, min(new_w, max_w))

            rounding_acc = target - new_w
            if abs(rounding_acc) > 5.0:
                rounding_acc = 0.0

            self.setColumnWidth(logical, new_w)

        header.blockSignals(False)
        self._is_resizing = False
        self._update_spring_column()

    # -- Abstract helpers (implemented differently per subclass) --------------

    def _get_column_count(self) -> int:
        raise NotImplementedError

    def _current_header_text(self, col: int) -> str:
        raise NotImplementedError

    def _apply_header_labels(self, labels: list[str]) -> None:
        raise NotImplementedError


# ============================================================================
# 3. SpringTableView  (model/view pattern)
# ============================================================================
class SpringTableView(_SpringColumnMixin, QTableView):
    """
    A ``QTableView`` with proportional column resizing, a spring column,
    and built-in layout persistence.  Pair with ``NumpyTableModel`` or
    any ``QAbstractTableModel``.

    Args:
        enable_sorting:      Enable column-header click sorting.
        enable_row_drag_drop: Enable internal row reordering via drag-and-drop.
        show_headers:        Show horizontal column headers.
        show_row_labels:     Show vertical row-number headers.
        alternating_rows:    Zebra-stripe row backgrounds.
        alternate_color:     Colour strategy for zebra striping.
        rows_resizable:      Allow users to resize row heights.
    """

    def __init__(
        self,
        enable_sorting: bool = False,
        enable_row_drag_drop: bool = False,
        show_headers: bool = True,
        show_row_labels: bool = True,
        alternating_rows: bool = True,
        alternate_color: str | QColor | Literal["lighter", "darker"] | None = "lighter",
        rows_resizable: bool = False,
    ) -> None:
        QTableView.__init__(self)
        self._init_spring(
            enable_sorting, enable_row_drag_drop,
            show_headers, show_row_labels,
            alternating_rows, alternate_color, rows_resizable,
        )

    # -- Mixin hooks ---------------------------------------------------------

    def _get_column_count(self) -> int:
        m = self.model()
        return m.columnCount() if m else 0

    def _current_header_text(self, col: int) -> str:
        m = self.model()
        if m:
            val = m.headerData(col, Qt.Orientation.Horizontal)
            return str(val) if val else str(col)
        return str(col)

    def _apply_header_labels(self, labels: list[str]) -> None:
        m = self.model()
        if m and hasattr(m, "set_headers") and callable(m.set_headers):
            m.set_headers(labels)

    # -- Qt overrides --------------------------------------------------------

    def showEvent(self, event) -> None:
        QTableView.showEvent(self, event)
        self._spring_show_event(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        QTableView.resizeEvent(self, event)
        self._spring_resize_event(event)


# ============================================================================
# 4. SpringTableWidget  (item-based pattern)
# ============================================================================
class SpringTableWidget(_SpringColumnMixin, QTableWidget):
    """
    A ``QTableWidget`` with proportional column resizing, a spring column,
    and built-in layout persistence.

    Includes a custom ``dropEvent`` that performs insert-move row reordering
    instead of Qt's default overwrite-move behaviour.

    Args:
        parent:              Parent widget.
        rows:                Initial row count.
        cols:                Initial column count.
        enable_sorting:      Enable column-header click sorting.
        enable_row_drag_drop: Enable internal row reordering via drag-and-drop.
        show_headers:        Show horizontal column headers.
        show_row_labels:     Show vertical row-number headers.
        alternating_rows:    Zebra-stripe row backgrounds.
        alternate_color:     Colour strategy for zebra striping.
        rows_resizable:      Allow users to resize row heights.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        rows: int = 0,
        cols: int = 0,
        enable_sorting: bool = False,
        enable_row_drag_drop: bool = False,
        show_headers: bool = True,
        show_row_labels: bool = True,
        alternating_rows: bool = True,
        alternate_color: str | QColor | Literal["lighter", "darker"] | None = "lighter",
        rows_resizable: bool = False,
    ) -> None:
        QTableWidget.__init__(self, rows, cols, parent)
        self._init_spring(
            enable_sorting, enable_row_drag_drop,
            show_headers, show_row_labels,
            alternating_rows, alternate_color, rows_resizable,
        )

    # -- Mixin hooks ---------------------------------------------------------

    def _get_column_count(self) -> int:
        return self.columnCount()

    def _current_header_text(self, col: int) -> str:
        item = self.horizontalHeaderItem(col)
        return item.text() if item else str(col)

    def _apply_header_labels(self, labels: list[str]) -> None:
        # Ensure column count matches
        if self.columnCount() < len(labels):
            self.setColumnCount(len(labels))
        self.setHorizontalHeaderLabels(labels)

    # -- Qt overrides --------------------------------------------------------

    def showEvent(self, event) -> None:
        QTableWidget.showEvent(self, event)
        self._spring_show_event(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        QTableWidget.resizeEvent(self, event)
        self._spring_resize_event(event)

    def dropEvent(self, event) -> None:
        """
        Custom drop handler that performs insert-move row reordering
        instead of Qt's default overwrite-move behaviour.
        """
        if not event.isAccepted() and event.source() is self:
            drop_row = self.indexAt(event.pos()).row()
            if drop_row == -1:
                drop_row = self.rowCount()

            selection = self.selectedItems()
            if not selection:
                return

            src_rows = sorted({item.row() for item in selection})
            if any(r == drop_row for r in src_rows):
                return

            # 1. Extract row data
            rows_data = []
            for r in src_rows:
                row_items = [QTableWidgetItem(self.item(r, c)) for c in range(self.columnCount())]
                rows_data.append(row_items)

            # 2. Insert at target position
            insert_idx = drop_row
            for row_items in rows_data:
                self.insertRow(insert_idx)
                for c, item in enumerate(row_items):
                    self.setItem(insert_idx, c, item)
                insert_idx += 1

            # 3. Delete original rows (adjust indices for the insertion offset)
            rows_to_delete = [
                r + len(src_rows) if r >= drop_row else r
                for r in src_rows
            ]
            for r in sorted(rows_to_delete, reverse=True):
                self.removeRow(r)

            event.accept()
        else:
            QTableWidget.dropEvent(self, event)


# ============================================================================
# 5. Demo Application
# ============================================================================
class _DemoController(QWidget):
    """Interactive demo showing SpringTableView + NumpyTableModel."""

    CONFIG_FILE = "paddol_table_layout.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PADDOL Spring Table Demo")
        self.resize(1000, 700)

        layout = QVBoxLayout(self)

        # Data & model
        rows = 100
        self._data = self._generate_data(rows)
        headers = ["ID", "Category", "Value (Int)", "Notes", "Spring"]
        self.model = NumpyTableModel(self._data, headers)

        # Table view
        self.table = SpringTableView(
            enable_sorting=True,
            alternating_rows=True,
            alternate_color="#f0f0f5",
            rows_resizable=True,
        )
        self.table.setModel(self.model)
        self.table.configure_columns([
            {"label": "ID",               "min_width": 50,  "max_width": 80,  "draggable": False},
            {"label": "Category",         "min_width": 100},
            {"label": "Value (Int)",      "min_width": 80,  "max_width": 120},
            {"label": "Notes (Draggable)","min_width": 150},
            {"label": "Spring Filler",    "min_width": 50},
        ])
        layout.addWidget(self.table)

        # Controls
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(panel)

        self.btn_sort = QPushButton("Sort Mode")
        self.btn_sort.setCheckable(True)
        self.btn_sort.setChecked(True)
        self.btn_sort.clicked.connect(lambda: self._set_mode("sort"))

        self.btn_drag = QPushButton("Drag Mode")
        self.btn_drag.setCheckable(True)
        self.btn_drag.clicked.connect(lambda: self._set_mode("drag"))

        btn_save = QPushButton("Save to Disk")
        btn_save.clicked.connect(self._save)

        btn_load = QPushButton("Load from Disk")
        btn_load.clicked.connect(self._load)

        btn_reset = QPushButton("Reset Defaults")
        btn_reset.clicked.connect(self.table.reset_table)

        h.addWidget(QLabel("Mode:"))
        h.addWidget(self.btn_sort)
        h.addWidget(self.btn_drag)
        h.addSpacing(20)
        h.addWidget(btn_save)
        h.addWidget(btn_load)
        h.addStretch()
        h.addWidget(btn_reset)
        layout.addWidget(panel)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _generate_data(rows: int) -> np.ndarray:
        data = np.empty((rows, 5), dtype=object)
        data[:, 0] = np.arange(rows)
        data[:, 1] = np.random.choice(["Alpha", "Beta", "Gamma"], size=rows)
        data[:, 2] = np.random.randint(100, 9999, size=rows)
        data[:, 3] = [f"Note_{i:03d}" for i in range(rows)]
        data[:, 4] = ""
        return data

    def _set_mode(self, mode: str) -> None:
        is_sort = mode == "sort"
        self.btn_sort.setChecked(is_sort)
        self.btn_drag.setChecked(not is_sort)
        (self.table.switch_to_sort if is_sort else self.table.switch_to_drag)()

    def _save(self) -> None:
        self.table.save_state_to_file(self.CONFIG_FILE)
        QMessageBox.information(self, "Saved", f"Layout saved to {self.CONFIG_FILE}")

    def _load(self) -> None:
        if Path(self.CONFIG_FILE).exists():
            self.table.load_state_from_file(self.CONFIG_FILE)
        else:
            QMessageBox.warning(self, "Error", "No saved layout file found.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = _DemoController()
    window.show()
    sys.exit(app.exec())