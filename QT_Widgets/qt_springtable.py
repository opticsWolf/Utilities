# -*- coding: utf-8 -*-
"""
PADDOL: Python Advanced Design & Dispersion Optimization Lab
Copyright (c) 2025 opticsWolf

SPDX-License-Identifier: LGPL-3.0-or-later

Refactored by: Principal Python Performance Engineer
"""

import sys
import json
import numpy as np
from typing import Any, Literal, Optional
from pathlib import Path
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QMimeData, 
    QByteArray, QDataStream, QIODevice
)
from PySide6.QtGui import QResizeEvent, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QTableView, QHeaderView, QVBoxLayout, QWidget, QTableWidget,
    QTableWidgetItem, QPushButton, QHBoxLayout, QAbstractItemView, 
    QLabel, QFrame, QMessageBox
)

# ==========================================
# 1. The High-Performance Model
# ==========================================
class NumpyTableModel(QAbstractTableModel):
    """
    A high-performance Qt Table Model backed by a NumPy array.
    """
    def __init__(self, data: np.ndarray, headers: list[str]) -> None:
        super().__init__()
        self._data = data
        self._headers = headers

    def set_headers(self, headers: list[str]) -> None:
        self._headers = headers
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(headers) - 1)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid(): return 0
        return self._data.shape[0]

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid(): return 0
        return self._data.shape[1]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid(): return None
        if role == Qt.ItemDataRole.DisplayRole:
            val = self._data[index.row(), index.column()]
            if hasattr(val, "item"): return val.item()
            return str(val) if val is not None else ""
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if index.isValid() and role == Qt.ItemDataRole.EditRole:
            self._data[index.row(), index.column()] = value
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self._headers[section] if section < len(self._headers) else str(section)
            return str(section + 1)
        return None

    def sort(self, column: int, order: Qt.SortOrder) -> None:
        self.layoutAboutToBeChanged.emit()
        try:
            indices = np.argsort(self._data[:, column], kind='stable')
        except TypeError:
            col_str = self._data[:, column].astype(str)
            indices = np.argsort(col_str, kind='stable')
        if order == Qt.SortOrder.DescendingOrder:
            indices = indices[::-1]
        self._data = self._data[indices]
        self.layoutChanged.emit()

    # --- Drag & Drop Support ---
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not index.isValid(): return Qt.ItemFlag.ItemIsDropEnabled
        return base_flags | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return ["application/x-paddol-row"]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        encoded_data = QByteArray()
        stream = QDataStream(encoded_data, QIODevice.OpenModeFlag.WriteOnly)
        if indexes: stream.writeInt32(indexes[0].row())
        mime.setData("application/x-paddol-row", encoded_data)
        return mime

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex) -> bool:
        if not data.hasFormat("application/x-paddol-row"): return False
        if action == Qt.DropAction.IgnoreAction: return True
        
        encoded_data = data.data("application/x-paddol-row")
        stream = QDataStream(encoded_data, QIODevice.OpenModeFlag.ReadOnly)
        src_row = stream.readInt32()
        dst_row = row
        if dst_row == -1: dst_row = parent.row() if parent.isValid() else self.rowCount()
        if src_row == dst_row: return False

        self.beginMoveRows(QModelIndex(), src_row, src_row, QModelIndex(), dst_row)
        row_data = self._data[src_row].copy()
        self._data = np.delete(self._data, src_row, axis=0)
        insert_idx = dst_row if src_row > dst_row else dst_row - 1
        self._data = np.insert(self._data, insert_idx, row_data, axis=0)
        self.endMoveRows()
        return True
    
    def reset_model(self, data: np.ndarray) -> None:
        self.beginResetModel()
        self._data = data
        self.endResetModel()

# ==========================================
# 2. The High-Performance Spring Table Widget
# ==========================================
class SpringTableWidget(QTableWidget):
    """
    A QTableWidget with proportional resizing, a 'spring' column,
    and built-in JSON state persistence.
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
        rows_resizable: bool = False
    ) -> None:
        """
        Initializes the SpringTableWidget.

        Args:
            rows: Initial number of rows.
            cols: Initial number of columns.
            enable_sorting: Enable column sorting (mutually exclusive with drag-drop).
            enable_row_drag_drop: Enable internal row reordering.
            show_headers: Visibility of horizontal headers.
            show_row_labels: Visibility of vertical headers.
            alternating_rows: Enable zebra striping.
            alternate_color: Color strategy for zebra striping.
            rows_resizable: Allow user to resize row height.
        """
        super().__init__(rows, cols)

        # Configuration
        self._min_widths: dict[int, int] = {}
        self._max_widths: dict[int, int] = {}
        self._draggable_column_indices: set[int] = set()

        # State
        self._saved_state: QByteArray | None = None
        self._default_state: QByteArray | None = None
        self._is_initialized: bool = False
        self._is_resizing: bool = False

        # Setup Visuals
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(alternating_rows)
        if alternating_rows and alternate_color:
            self.set_alternating_color(alternate_color)

        self.horizontalHeader().setVisible(show_headers)
        self.verticalHeader().setVisible(show_row_labels)

        # Header Config
        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setStretchLastSection(False)
        h_header.setSectionsMovable(True)
        if h_header.sortIndicatorSection() == -1:
            h_header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        # Row Config
        v_header = self.verticalHeader()
        mode = QHeaderView.ResizeMode.Interactive if rows_resizable else QHeaderView.ResizeMode.Fixed
        v_header.setSectionResizeMode(mode)

        # Signals
        h_header.sectionResized.connect(self._on_column_resized)
        h_header.sectionMoved.connect(self._on_column_moved)

        # Mode Initialization
        if enable_row_drag_drop:
            self.switch_to_drag()
        else:
            self.switch_to_sort()
            self.setSortingEnabled(enable_sorting)

    # --- Persistence API ---

    def save_state_to_file(self, filepath: str | Path) -> None:
        """
        Saves current column widths and visual ordering to a JSON file.

        Args:
            filepath: Path to the JSON file.
        """
        header = self.horizontalHeader()
        state = {"columns": []}

        for logical_idx in range(header.count()):
            col_data = {
                "logical_index": logical_idx,
                "width": self.columnWidth(logical_idx),
                "visual_index": header.visualIndex(logical_idx)
            }
            state["columns"].append(col_data)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=4)
            print(f">> State saved to {filepath}")
        except OSError as e:
            print(f"Error saving state: {e}")

    def load_state_from_file(self, filepath: str | Path) -> None:
        """
        Loads column widths and ordering from a JSON file.

        Args:
            filepath: Path to the JSON file.
        """
        path = Path(filepath)
        if not path.exists():
            print(f"File not found: {filepath}")
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Error loading state: {e}")
            return

        header = self.horizontalHeader()
        columns = state.get("columns", [])

        if not columns:
            return

        self._is_resizing = True
        header.blockSignals(True)

        # 1. Restore Widths
        for col_data in columns:
            logical_idx = col_data["logical_index"]
            width = col_data["width"]
            if logical_idx < header.count():
                self.setColumnWidth(logical_idx, width)

        # 2. Restore Ordering
        columns_by_visual = sorted(columns, key=lambda x: x["visual_index"])
        for visual_pos, col_data in enumerate(columns_by_visual):
            logical_idx = col_data["logical_index"]
            current_visual = header.visualIndex(logical_idx)

            if current_visual != visual_pos:
                header.moveSection(current_visual, visual_pos)

        header.blockSignals(False)
        self._is_resizing = False
        self._update_spring_column()
        print(f">> State loaded from {filepath}")

    # --- Public API ---

    def configure_columns(self, config: list[dict[str, Any]]) -> None:
        """
        Configures column properties (labels, min/max widths, draggable).

        Args:
            config: List of dicts containing configuration per column.
        """
        self._draggable_column_indices.clear()
        self._min_widths.clear()
        self._max_widths.clear()

        # Ensure we have enough columns
        if self.columnCount() < len(config):
            self.setColumnCount(len(config))

        for i, cfg in enumerate(config):
            if "label" in cfg:
                self.setHorizontalHeaderItem(i, QTableWidgetItem(cfg["label"]))
            if "min_width" in cfg:
                self._min_widths[i] = cfg["min_width"]
            if "max_width" in cfg:
                self._max_widths[i] = cfg["max_width"]
            if cfg.get("draggable", True):
                self._draggable_column_indices.add(i)

        if self.isVisible():
            self._recalculate_widths_ratio(1.0)

    def switch_to_sort(self) -> None:
        """Enables sorting mode and disables drag-and-drop."""
        self._set_drag_enabled(False)
        if self.horizontalHeader().sortIndicatorSection() == -1:
            self.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSectionsClickable(True)

    def switch_to_drag(self) -> None:
        """Enables row drag-and-drop mode and disables sorting."""
        self._set_drag_enabled(True)

    def reset_table_state(self) -> None:
        """Restores the default column layout."""
        if self._default_state:
            self.horizontalHeader().restoreState(self._default_state)
            self._update_spring_column()

    # --- Internal Logic & Overrides ---

    def _set_drag_enabled(self, enable: bool) -> None:
        self.setDragEnabled(enable)
        self.setAcceptDrops(enable)
        if enable:
            self.setSortingEnabled(False)
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDropIndicatorShown(True)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def dropEvent(self, event) -> None:
        """
        Custom drop event to handle row reordering (Insert-Move) 
        instead of the default Overwrite-Move.
        """
        if not event.isAccepted() and event.source() == self:
            drop_row = self.indexAt(event.pos()).row()
            drop_col = self.indexAt(event.pos()).column()
            
            # If dropped on empty space, append to end
            if drop_row == -1:
                drop_row = self.rowCount()

            # Get selected rows
            selection = self.selectedItems()
            if not selection:
                return
            
            # Map items to rows
            rows = sorted(list(set(item.row() for item in selection)))
            
            # Avoid self-drop logic issues
            if any(r == drop_row for r in rows):
                return

            # Perform Move
            # 1. Extract data from source rows
            rows_data = []
            for r in rows:
                row_items = []
                for c in range(self.columnCount()):
                    item = self.item(r, c)
                    # Clone item
                    new_item = QTableWidgetItem(item)
                    row_items.append(new_item)
                rows_data.append(row_items)

            # 2. Insert new rows
            # Adjust drop row if dragging downwards
            insert_idx = drop_row
            
            for row_items in rows_data:
                self.insertRow(insert_idx)
                for c, item in enumerate(row_items):
                    self.setItem(insert_idx, c, item)
                insert_idx += 1

            # 3. Delete old rows (Reverse order to maintain indices)
            # We must account for the offset created by insertion if source was below target
            rows_to_delete = []
            for r in rows:
                if r >= drop_row: 
                    rows_to_delete.append(r + len(rows))
                else:
                    rows_to_delete.append(r)
            
            for r in sorted(rows_to_delete, reverse=True):
                self.removeRow(r)

            event.accept()
            # Select the newly moved rows
            self.clearSelection()
            # (Selection logic could be added here if needed)
            
        else:
            super().dropEvent(event)

    def _update_spring_column(self) -> None:
        if self._is_resizing: return
        header = self.horizontalHeader()
        count = header.count()
        if count == 0: return

        last_visual = count - 1
        last_logical = header.logicalIndex(last_visual)
        used_width = sum(self.columnWidth(header.logicalIndex(i))
                         for i in range(count) if i != last_visual)

        viewport_width = self.viewport().width()
        new_width = max(self._min_widths.get(last_logical, 0), viewport_width - used_width)

        if self.columnWidth(last_logical) != new_width:
            self._is_resizing = True
            header.blockSignals(True)
            self.setColumnWidth(last_logical, new_width)
            header.blockSignals(False)
            self._is_resizing = False

    def _recalculate_widths_ratio(self, ratio: float) -> None:
        header = self.horizontalHeader()
        count = header.count()
        self._is_resizing = True
        header.blockSignals(True)
        rounding_accumulator = 0.0

        for i in range(count - 1):
            logical = header.logicalIndex(i)
            current_w = self.columnWidth(logical)
            target = (current_w * ratio) + rounding_accumulator
            new_w_int = int(round(target))

            min_w = self._min_widths.get(logical, 30)
            max_w = self._max_widths.get(logical, 999999)
            new_w_int = max(min_w, min(new_w_int, max_w))

            rounding_accumulator = target - new_w_int
            if abs(rounding_accumulator) > 5.0: rounding_accumulator = 0.0

            self.setColumnWidth(logical, new_w_int)

        header.blockSignals(False)
        self._is_resizing = False
        self._update_spring_column()

    def resizeEvent(self, event: QResizeEvent) -> None:
        old_w = event.oldSize().width()
        new_w = event.size().width()
        super().resizeEvent(event)
        if old_w <= 0 or new_w <= 0: return
        ratio = new_w / old_w
        self._recalculate_widths_ratio(ratio)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._is_initialized:
            self._default_state = self.horizontalHeader().saveState()
            if self._saved_state is None:
                self._saved_state = self.horizontalHeader().saveState()
            self._is_initialized = True
        self._update_spring_column()

    def _on_column_moved(self, logical: int, old_visual: int, new_visual: int) -> None:
        if logical not in self._draggable_column_indices:
            h = self.horizontalHeader()
            h.blockSignals(True)
            h.moveSection(new_visual, old_visual)
            h.blockSignals(False)
        else:
            self._update_spring_column()

    def _on_column_resized(self, logical: int, old_size: int, new_size: int) -> None:
        if self._is_resizing: return
        min_w = self._min_widths.get(logical, 30)
        max_w = self._max_widths.get(logical, 999999)
        corrected = max(min_w, min(new_size, max_w))

        if corrected != new_size:
            self.horizontalHeader().blockSignals(True)
            self.setColumnWidth(logical, corrected)
            self.horizontalHeader().blockSignals(False)

        self._update_spring_column()

    def set_alternating_color(self, color_spec: str | QColor | Literal["lighter", "darker"]) -> None:
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        target = base
        if color_spec == "lighter": target = base.lighter(110)
        elif color_spec == "darker": target = base.darker(105)
        elif isinstance(color_spec, (str, QColor)): target = QColor(color_spec)
        palette.setColor(QPalette.ColorRole.AlternateBase, target)
        self.setPalette(palette)


# ==========================================
# 3. The Configurable Responsive View
# ==========================================
class SpringTableView(QTableView):
    """
    A QTableView that proportionally resizes columns and maintains a 'spring' column.
    Now includes JSON file persistence.
    """

    def __init__(
        self, 
        enable_sorting: bool = False, 
        enable_row_drag_drop: bool = False,
        show_headers: bool = True,
        show_row_labels: bool = True,
        alternating_rows: bool = True,
        alternate_color: str | QColor | Literal["lighter", "darker"] | None = "lighter",
        rows_resizable: bool = False
    ) -> None:
        super().__init__()
        
        # Configuration
        self._min_widths: dict[int, int] = {}
        self._max_widths: dict[int, int] = {}
        self._draggable_column_indices: set[int] = set()
        
        # State
        self._saved_state: QByteArray | None = None
        self._default_state: QByteArray | None = None
        self._is_initialized: bool = False
        self._is_resizing: bool = False 

        # Setup
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(alternating_rows)
        if alternating_rows and alternate_color:
            self.set_alternating_color(alternate_color)
        
        self.horizontalHeader().setVisible(show_headers)
        self.verticalHeader().setVisible(show_row_labels)
        
        # Headers
        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h_header.setStretchLastSection(False)
        h_header.setSectionsMovable(True)
        if h_header.sortIndicatorSection() == -1:
            h_header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        # Rows
        v_header = self.verticalHeader()
        mode = QHeaderView.ResizeMode.Interactive if rows_resizable else QHeaderView.ResizeMode.Fixed
        v_header.setSectionResizeMode(mode)

        # Signals
        h_header.sectionResized.connect(self._on_column_resized)
        h_header.sectionMoved.connect(self._on_column_moved)

        # Mode Init
        if enable_row_drag_drop:
            self.switch_to_drag()
        else:
            self.switch_to_sort()
            self.setSortingEnabled(enable_sorting)

    # --- Persistence API (New) ---

    def save_state_to_file(self, filepath: str | Path) -> None:
        """
        Saves current column widths and visual ordering to a JSON file.
        
        Args:
            filepath: Path to the JSON file.
        """
        header = self.horizontalHeader()
        state = {
            "columns": []
        }
        
        # Iterate logical indices to grab their current visual properties
        for logical_idx in range(header.count()):
            col_data = {
                "logical_index": logical_idx,
                "width": self.columnWidth(logical_idx),
                "visual_index": header.visualIndex(logical_idx)
            }
            state["columns"].append(col_data)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=4)
            print(f">> State saved to {filepath}")
        except OSError as e:
            print(f"Error saving state: {e}")

    def load_state_from_file(self, filepath: str | Path) -> None:
        """
        Loads column widths and ordering from a JSON file.
        
        Args:
            filepath: Path to the JSON file.
        """
        path = Path(filepath)
        if not path.exists():
            print(f"File not found: {filepath}")
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Error loading state: {e}")
            return

        header = self.horizontalHeader()
        columns = state.get("columns", [])
        
        if not columns:
            return

        self._is_resizing = True # Block internal spring logic during bulk update
        header.blockSignals(True)

        # 1. Restore Widths
        for col_data in columns:
            logical_idx = col_data["logical_index"]
            width = col_data["width"]
            if logical_idx < header.count():
                self.setColumnWidth(logical_idx, width)

        # 2. Restore Ordering
        # To restore order, we must move sections.
        # We sort the saved data by 'visual_index' to know what *should* be 1st, 2nd, etc.
        columns_by_visual = sorted(columns, key=lambda x: x["visual_index"])
        
        for visual_pos, col_data in enumerate(columns_by_visual):
            logical_idx = col_data["logical_index"]
            current_visual = header.visualIndex(logical_idx)
            
            if current_visual != visual_pos:
                header.moveSection(current_visual, visual_pos)

        header.blockSignals(False)
        self._is_resizing = False
        
        self._update_spring_column()
        print(f">> State loaded from {filepath}")

    # --- Existing Public API ---

    def configure_columns(self, config: list[dict[str, Any]]) -> None:
        model = self.model()
        if not model: return

        labels = []
        col_count = model.columnCount()
        self._draggable_column_indices.clear()
        self._min_widths.clear()
        self._max_widths.clear()

        for i in range(col_count):
            cfg = config[i] if i < len(config) else {}
            if "label" in cfg: labels.append(cfg["label"])
            else:
                current = model.headerData(i, Qt.Orientation.Horizontal)
                labels.append(str(current) if current else str(i))
            if "min_width" in cfg: self._min_widths[i] = cfg["min_width"]
            if "max_width" in cfg: self._max_widths[i] = cfg["max_width"]
            if cfg.get("draggable", True): self._draggable_column_indices.add(i)

        if hasattr(model, "set_headers") and callable(model.set_headers):
            model.set_headers(labels)

        if self.isVisible(): self._recalculate_widths_ratio(1.0)

    def switch_to_sort(self) -> None:
        self._set_drag_enabled(False)
        if self.horizontalHeader().sortIndicatorSection() == -1:
            self.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSectionsClickable(True)

    def switch_to_drag(self) -> None:
        self._set_drag_enabled(True)

    def save_layout(self) -> None:
        self._saved_state = self.horizontalHeader().saveState()

    def restore_layout(self) -> None:
        if self._saved_state:
            self.horizontalHeader().restoreState(self._saved_state)
            self._update_spring_column()

    def reset_table(self) -> None:
        if self._default_state:
            self.horizontalHeader().restoreState(self._default_state)
            self._update_spring_column()

    # --- Internal Logic ---

    def _set_drag_enabled(self, enable: bool) -> None:
        self.setDragEnabled(enable)
        self.setAcceptDrops(enable)
        if enable:
            self.setSortingEnabled(False)
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDropIndicatorShown(True)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def _update_spring_column(self) -> None:
        if self._is_resizing: return
        header = self.horizontalHeader()
        count = header.count()
        if count == 0: return

        last_visual = count - 1
        last_logical = header.logicalIndex(last_visual)
        used_width = sum(self.columnWidth(header.logicalIndex(i)) 
                         for i in range(count) if i != last_visual)
        
        viewport_width = self.viewport().width()
        new_width = max(self._min_widths.get(last_logical, 0), viewport_width - used_width)

        if self.columnWidth(last_logical) != new_width:
            self._is_resizing = True
            header.blockSignals(True)
            self.setColumnWidth(last_logical, new_width)
            header.blockSignals(False)
            self._is_resizing = False

    def _recalculate_widths_ratio(self, ratio: float) -> None:
        header = self.horizontalHeader()
        count = header.count()
        self._is_resizing = True
        header.blockSignals(True)
        rounding_accumulator = 0.0
        
        for i in range(count - 1):
            logical = header.logicalIndex(i)
            current_w = self.columnWidth(logical)
            target = (current_w * ratio) + rounding_accumulator
            new_w_int = int(round(target))
            
            min_w = self._min_widths.get(logical, 30)
            max_w = self._max_widths.get(logical, 999999)
            new_w_int = max(min_w, min(new_w_int, max_w))

            rounding_accumulator = target - new_w_int
            if abs(rounding_accumulator) > 5.0: rounding_accumulator = 0.0 
            
            self.setColumnWidth(logical, new_w_int)

        header.blockSignals(False)
        self._is_resizing = False
        self._update_spring_column()

    def resizeEvent(self, event: QResizeEvent) -> None:
        old_w = event.oldSize().width()
        new_w = event.size().width()
        super().resizeEvent(event)
        if old_w <= 0 or new_w <= 0: return
        ratio = new_w / old_w
        self._recalculate_widths_ratio(ratio)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._is_initialized:
            self._default_state = self.horizontalHeader().saveState()
            if self._saved_state is None: self.save_layout()
            self._is_initialized = True
        self._update_spring_column()

    def _on_column_moved(self, logical: int, old_visual: int, new_visual: int) -> None:
        if logical not in self._draggable_column_indices:
            h = self.horizontalHeader()
            h.blockSignals(True)
            h.moveSection(new_visual, old_visual) 
            h.blockSignals(False)
        else:
            self._update_spring_column()

    def _on_column_resized(self, logical: int, old_size: int, new_size: int) -> None:
        if self._is_resizing: return
        min_w = self._min_widths.get(logical, 30)
        max_w = self._max_widths.get(logical, 999999)
        corrected = max(min_w, min(new_size, max_w))
        
        if corrected != new_size:
            self.horizontalHeader().blockSignals(True)
            self.setColumnWidth(logical, corrected)
            self.horizontalHeader().blockSignals(False)
            
        self._update_spring_column()

    def set_alternating_color(self, color_spec: str | QColor | Literal["lighter", "darker"]) -> None:
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base)
        target = base
        if color_spec == "lighter": target = base.lighter(110)
        elif color_spec == "darker": target = base.darker(105)
        elif isinstance(color_spec, (str, QColor)): target = QColor(color_spec)
        palette.setColor(QPalette.ColorRole.AlternateBase, target)
        self.setPalette(palette)


# ==========================================
# 4. Main Controller (Demo)
# ==========================================
class ComplexTableController(QWidget):
    """
    Main controller demonstrating the PADDOL table system.
    """
    CONFIG_FILE = "paddol_table_layout.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PADDOL High-Performance Table")
        self.resize(1000, 700)
        
        self.layout_main = QVBoxLayout(self)
        
        # 1. Data & Model
        rows = 100
        self.data_source = self._generate_data(rows)
        self.headers = ["ID", "Category", "Value (Int)", "Notes", "Spring"]
        self.model = NumpyTableModel(self.data_source, self.headers)
        
        # 2. View
        self.table = SpringTableView(
            enable_sorting=True,
            enable_row_drag_drop=False,
            alternating_rows=True,
            alternate_color="#f0f0f5",
            rows_resizable=True
        )
        self.table.setModel(self.model)
        
        # 3. Configuration
        self.table.configure_columns([
            {"label": "ID", "min_width": 50, "max_width": 80, "draggable": False},
            {"label": "Category", "min_width": 100},
            {"label": "Value (Int)", "min_width": 80, "max_width": 120},
            {"label": "Notes (Draggable)", "min_width": 150},
            {"label": "Spring Filler", "min_width": 50}
        ])
        
        self.layout_main.addWidget(self.table)
        self._create_controls()

    def _generate_data(self, rows: int) -> np.ndarray:
        data = np.empty((rows, 5), dtype=object)
        data[:, 0] = np.arange(rows)
        data[:, 1] = np.random.choice(["Alpha", "Beta", "Gamma"], size=rows)
        data[:, 2] = np.random.randint(100, 9999, size=rows)
        data[:, 3] = [f"Note_{i:03d}" for i in range(rows)]
        data[:, 4] = ""
        return data

    def _create_controls(self) -> None:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        h_layout = QHBoxLayout(panel)
        
        # Mode Controls
        self.btn_sort = QPushButton("Sort Mode")
        self.btn_sort.setCheckable(True)
        self.btn_sort.setChecked(True)
        self.btn_sort.clicked.connect(lambda: self._toggle_mode("sort"))
        
        self.btn_drag = QPushButton("Drag Mode")
        self.btn_drag.setCheckable(True)
        self.btn_drag.clicked.connect(lambda: self._toggle_mode("drag"))
        
        # Persistence Controls
        btn_save = QPushButton("Save to Disk")
        btn_save.clicked.connect(self._save_to_disk)
        
        btn_load = QPushButton("Load from Disk")
        btn_load.clicked.connect(self._load_from_disk)

        btn_reset = QPushButton("Reset Defaults")
        btn_reset.clicked.connect(self.table.reset_table)
        
        h_layout.addWidget(QLabel("Mode:"))
        h_layout.addWidget(self.btn_sort)
        h_layout.addWidget(self.btn_drag)
        h_layout.addSpacing(20)
        h_layout.addWidget(btn_save)
        h_layout.addWidget(btn_load)
        h_layout.addStretch()
        h_layout.addWidget(btn_reset)
        
        self.layout_main.addWidget(panel)

    def _toggle_mode(self, mode: Literal["sort", "drag"]) -> None:
        if mode == "sort":
            self.table.switch_to_sort()
            self.btn_sort.setChecked(True)
            self.btn_drag.setChecked(False)
        else:
            self.table.switch_to_drag()
            self.btn_sort.setChecked(False)
            self.btn_drag.setChecked(True)

    def _save_to_disk(self) -> None:
        self.table.save_state_to_file(self.CONFIG_FILE)
        QMessageBox.information(self, "Saved", f"Layout saved to {self.CONFIG_FILE}")

    def _load_from_disk(self) -> None:
        if Path(self.CONFIG_FILE).exists():
            self.table.load_state_from_file(self.CONFIG_FILE)
        else:
            QMessageBox.warning(self, "Error", "No saved layout file found.")

#------- Example code -----
if __name__ == "__main__":
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    app.setStyle("Fusion")
    
    window = ComplexTableController()
    window.show()
    
    sys.exit(app.exec())