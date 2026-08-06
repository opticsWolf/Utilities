# -*- coding: utf-8 -*-
from __future__ import annotations
"""
PADDOL: Unified Table Control Widget (Standard & Transposed)
Copyright (c) 2025 opticsWolf

A single class structure handling both Column-based (List) and Row-based (Card)
views via an 'is_transposed' flag.
"""

import sys
from typing import Any, List, Optional, Callable, TypedDict, Union, Literal, Dict, Type

from PySide6.QtCore import (
    Qt, QPoint, QAbstractItemModel, QModelIndex, QTime, QDate, 
    QRegularExpression
)
from PySide6.QtGui import (
    QIntValidator, QDoubleValidator, QRegularExpressionValidator,
    QPainter, QColor, QAction
)
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QWidget, QTableWidgetItem, QHBoxLayout,
    QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit, QLabel,
    QSlider, QMainWindow, QTimeEdit, QDateEdit, QPushButton, QColorDialog, 
    QAbstractItemView, QMenu, QStyle, QStyleOptionViewItem, QStyledItemDelegate,
    QHeaderView
)

# ──────────────────────────────────────────────────────────────
# Robust Dependency Loading
# ──────────────────────────────────────────────────────────────
# A. Spring Table Fallback
try:
    from qt_springtable import SpringTableWidget
except ImportError:
    from PySide6.QtWidgets import QTableWidget
    class SpringTableWidget(QTableWidget):
        """Mock fallback if library missing"""
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.setAlternatingRowColors(kwargs.get('alternating_rows', False))
            self.setSortingEnabled(kwargs.get('enable_sorting', False))
        def configure_columns(self, config): pass

# B. Color Wheel Fallback
try:
    from qt_colorwheel import ColorGeneratorDialog
    _HAS_COLORWHEEL = True
except ImportError:
    _HAS_COLORWHEEL = False

# ──────────────────────────────────────────────────────────────
# Type Definitions
# ──────────────────────────────────────────────────────────────

class PropertyDescriptor(TypedDict, total=False):
    """Schema for property definitions to ensure type safety."""
    attr: str
    label: str
    widget_type: Type[QWidget]
    value_type: str 
    readonly: bool
    editable: bool
    unit: str
    value_range: tuple[float, float]
    step_size: float
    decimals: int       
    items: List[str]  
    always_visible: bool 
    orientation: Qt.Orientation
    getter: Callable[[Any], Any]
    setter: Callable[[Any, Any], None]
    default: Any
    precision: Literal["min", "secs"]
    with_label: bool
    min_width: int
    max_width: int
    draggable: bool

# ──────────────────────────────────────────────────────────────
# 1. Unified Delegate
# ──────────────────────────────────────────────────────────────

class UnifiedPropertyDelegate(QStyledItemDelegate):
    """
    Handles both Standard (Col=Prop) and Transposed (Row=Prop) modes.
    """
    def __init__(
        self, 
        properties: List[PropertyDescriptor], 
        parent: Optional[Any] = None,
        is_transposed: bool = False
    ) -> None:
        super().__init__(parent)
        self._properties = properties
        self._is_transposed = is_transposed
        
        # --- O(1) Factory Dispatch ---
        self._editor_creators: Dict[Type[QWidget], Callable] = {
            QCheckBox: self._create_checkbox,
            QDoubleSpinBox: self._create_double_spinbox,
            QSpinBox: self._create_spinbox,
            QLineEdit: self._create_line_edit,
            QComboBox: self._create_combobox,
            QSlider: self._create_slider_wrapper,
            QTimeEdit: self._create_time_edit,
            QDateEdit: self._create_date_edit,
            QPushButton: self._create_color_button
        }

        self._editor_setters: Dict[Type[QWidget], Callable] = {
            QCheckBox: lambda w, v, p: w.setChecked(bool(v)),
            QDoubleSpinBox: lambda w, v, p: w.setValue(float(v) if v is not None else 0.0),
            QSpinBox: lambda w, v, p: w.setValue(int(float(v)) if v is not None else 0),
            QLineEdit: lambda w, v, p: w.setText(str(v)),
            QComboBox: self._set_combo_data,
            QTimeEdit: lambda w, v, p: w.setTime(self._to_qtime(v)),
            QDateEdit: lambda w, v, p: w.setDate(self._to_qdate(v)),
            QPushButton: lambda w, v, p: self._update_color_button_face(w, v)
        }

        self._model_setters: Dict[Type[QWidget], Callable] = {
            QCheckBox: lambda w: w.isChecked(),
            QDoubleSpinBox: lambda w: w.value(),
            QSpinBox: lambda w: w.value(),
            QLineEdit: lambda w: w.text(),
            QComboBox: lambda w: w.currentText(),
            QTimeEdit: lambda w: w.time(),
            QDateEdit: lambda w: w.date(),
            QPushButton: lambda w: w.property("color_value")
        }

    # --- Core Abstraction ---

    def _get_property(self, index: QModelIndex) -> PropertyDescriptor:
        """Determines property definition based on orientation."""
        if not index.isValid(): return {}
        # If transposed, Row defines property. If standard, Column defines property.
        idx = index.row() if self._is_transposed else index.column()
        if idx < 0 or idx >= len(self._properties): return {}
        return self._properties[idx]

    # --- Data Helpers ---

    @staticmethod
    def get_value(obj: Any, prop: PropertyDescriptor) -> Any:
        if obj is None: return None
        
        val = None
        found = False

        if "getter" in prop:
            val = prop["getter"](obj)
            found = True
        else:
            attr = prop.get("attr")
            if attr and hasattr(obj, attr):
                raw = getattr(obj, attr, None)
                val = raw() if callable(raw) else raw
                found = True
        
        # Fallback to default if value is missing/None to prevent empty display cells
        if (val is None or not found) and "default" in prop:
            return prop["default"]
            
        return val

    @staticmethod
    def set_value(obj: Any, prop: PropertyDescriptor, value: Any) -> None:
        """Safely sets value to object, swallowing TypeErrors to prevent crashes."""
        if obj is None: return
        try:
            if "setter" in prop:
                prop["setter"](obj, value)
                return
            attr = prop.get("attr")
            if not attr: return
            target = getattr(obj, attr, None)
            if callable(target):
                try: target(value)
                except TypeError: pass 
            else:
                setattr(obj, attr, value)
        except Exception as e:
            print(f"[UnifiedPropertyDelegate] Error setting value: {e}")

    @staticmethod
    def _to_qtime(val: Any) -> QTime:
        if isinstance(val, QTime): return val
        if isinstance(val, str): return QTime.fromString(val)
        return QTime.currentTime()

    @staticmethod
    def _to_qdate(val: Any) -> QDate:
        if isinstance(val, QDate): return val
        if isinstance(val, str): return QDate.fromString(val, Qt.ISODate)
        return QDate.currentDate()

    @staticmethod
    def _calculate_dynamic_limits(val: Any) -> tuple[float, float]:
        try: v = float(val) if val is not None else 0.0
        except (ValueError, TypeError): v = 0.0
        if abs(v) < 1e-9: return (0.0, 100.0)
        lower, upper = v * 0.05, v * 2.0
        return (min(lower, upper), max(lower, upper))

    # --- Factory Creators ---
    def _create_checkbox(self, p, prop, v): return QCheckBox(p)
    
    def _create_double_spinbox(self, p, prop, v):
        w = QDoubleSpinBox(p)
        w.setDecimals(prop.get("decimals", 2))
        if "value_range" in prop: w.setRange(*prop["value_range"])
        else: w.setRange(*self._calculate_dynamic_limits(v))
        if "step_size" in prop: w.setSingleStep(prop["step_size"])
        if "unit" in prop: w.setSuffix(f" {prop['unit']}")
        # FIX: Explicitly set value
        w.setValue(float(v) if v is not None else 0.0)
        return w
    
    def _create_spinbox(self, p, prop, v):
        w = QSpinBox(p)
        rng = prop.get("value_range") or self._calculate_dynamic_limits(v)
        w.setRange(int(rng[0]), int(rng[1]))
        if "step_size" in prop: w.setSingleStep(int(prop["step_size"]))
        if "unit" in prop: w.setSuffix(f" {prop['unit']}")
        # FIX: Explicitly set value
        w.setValue(int(float(v)) if v is not None else 0)
        return w
    
    def _create_line_edit(self, p, prop, v):
        w = QLineEdit(p)
        vt = prop.get("value_type")
        if vt == "numeric": w.setValidator(QDoubleValidator(w))
        elif vt == "alphanumeric": w.setValidator(QRegularExpressionValidator(QRegularExpression("^[a-zA-Z0-9_()-]*$"), w))
        # FIX: Explicitly set text
        w.setText(str(v) if v is not None else "")
        return w
    
    def _create_combobox(self, p, prop, v):
        w = QComboBox(p)
        w.addItems(prop.get("items", []))
        # FIX: Explicitly set current item
        if v is not None:
             idx = w.findText(str(v))
             if idx >= 0: w.setCurrentIndex(idx)
        return w
    
    def _create_slider_wrapper(self, p, prop, v): return self._create_slider_widget(p, prop, v, None)
    
    def _create_time_edit(self, p, prop, v): 
        w = QTimeEdit(p)
        w.setDisplayFormat("HH:mm:ss" if prop.get("precision")=="secs" else "HH:mm")
        w.setTime(self._to_qtime(v))
        return w
    
    def _create_date_edit(self, p, prop, v):
        w = QDateEdit(p)
        w.setCalendarPopup(True)
        w.setDisplayFormat("yyyy-MM-dd")
        w.setDate(self._to_qdate(v))
        return w
    
    def _create_color_button(self, p, prop, v):
        w = QPushButton(p)
        self._setup_color_button(w, v, None, True, prop)
        return w

    # --- Overrides ---

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget:
        prop = self._get_property(index) 
        if not prop.get("editable", True): return None

        creator = self._editor_creators.get(prop.get("widget_type"))
        if not creator: return super().createEditor(parent, option, index)

        obj = index.data(Qt.UserRole)
        current_val = self.get_value(obj, prop) if obj else index.data(Qt.EditRole)
        return creator(parent, prop, current_val)

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        prop = self._get_property(index) 
        obj = index.data(Qt.UserRole)
        value = self.get_value(obj, prop) if obj is not None else index.data(Qt.EditRole)
        
        if hasattr(editor, "slider"):
            decimals = prop.get("decimals", 0)
            multiplier = 10 ** decimals
            editor.slider.setValue(int(float(value) * multiplier) if value is not None else 0)
            return

        setter = self._editor_setters.get(type(editor))
        if setter:
            try: setter(editor, value, prop)
            except ValueError: pass

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex) -> None:
        prop = self._get_property(index) 
        val = None

        if hasattr(editor, "slider"):
            val = editor.slider.value() / (10 ** prop.get("decimals", 0))
        else:
            getter = self._model_setters.get(type(editor))
            if getter: val = getter(editor)

        # Batch Logic Handled by Parent
        dock_widget = self.parent()
        if dock_widget and hasattr(dock_widget, "apply_batch_edit"):
             dock_widget.apply_batch_edit(index.row(), index.column(), val)
        else:
             model.setData(index, val, Qt.EditRole)

    # --- Formatting & Rendering ---

    @staticmethod
    def format_value(val: Any, prop: PropertyDescriptor) -> str:
        if val is None: return ""
        if isinstance(val, QTime) or prop.get("widget_type") is QTimeEdit:
            fmt = "HH:mm:ss" if prop.get("precision") == "secs" else "HH:mm"
            return UnifiedPropertyDelegate._to_qtime(val).toString(fmt)
        if isinstance(val, QDate) or prop.get("widget_type") is QDateEdit:
            return UnifiedPropertyDelegate._to_qdate(val).toString("yyyy-MM-dd")
        if isinstance(val, (float, int)):
            if "decimals" in prop: return f"{val:.{prop['decimals']}f}"
            if val == 0: return "0"
            if abs(val) < 0.001 or abs(val) >= 100000: return f"{val:.3e}"
            return f"{val:.3f}".rstrip("0").rstrip(".")
        return str(val)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if not index.isValid(): return
        prop = self._get_property(index) 

        if prop.get("always_visible", False):
            self._draw_empty_cell(painter, option, index)
            return

        if prop.get("widget_type") is QPushButton:
            self._paint_color_button_static(painter, option, index, prop)
            return

        super().paint(painter, option, index)

    def _draw_empty_cell(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        opt_copy = QStyleOptionViewItem(option)
        self.initStyleOption(opt_copy, index)
        opt_copy.text = "" 
        QApplication.style().drawControl(QStyle.CE_ItemViewItem, opt_copy, painter)

    def _paint_color_button_static(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex, prop: PropertyDescriptor):
        val = index.data(Qt.EditRole)
        color = QColor(val) if val else QColor(Qt.transparent)
        if color.isValid():
            painter.save()
            rect = option.rect.adjusted(4, 4, -4, -4)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 2, 2)
            if prop.get("with_label", True):
                brightness = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
                painter.setPen(Qt.black if brightness > 128 else Qt.white)
                painter.drawText(rect, Qt.AlignCenter, color.name())
            painter.restore()

    # --- Helpers (Slider, Color) ---

    def _set_combo_data(self, editor: QComboBox, value: Any, prop: PropertyDescriptor):
        idx = editor.findText(str(value))
        if idx >= 0: editor.setCurrentIndex(idx)

    def _create_slider_widget(self, parent: Optional[QWidget], prop: PropertyDescriptor, val: Any, callback: Optional[Callable]) -> QWidget:
        container = QWidget(parent)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)
        slider = QSlider(prop.get("orientation", Qt.Horizontal))
        
        decimals = prop.get("decimals", 0)
        multiplier = 10 ** decimals
        logical_rng = prop.get("value_range") or self._calculate_dynamic_limits(val)
        
        slider.setRange(int(logical_rng[0] * multiplier), int(logical_rng[1] * multiplier))
        try: float_val = float(val) if val is not None else float(logical_rng[0])
        except ValueError: float_val = float(logical_rng[0])
        slider.setValue(int(float_val * multiplier))
        
        unit = prop.get("unit", "")
        formatted = self.format_value(val if val is not None else 0, prop)
        label = QLabel(f"{formatted} {unit}".strip())
        label.setFixedWidth(50)
        
        layout.addWidget(slider)
        layout.addWidget(label)
        container.slider = slider
        container.label = label
        
        def update_lbl(slider_val: int) -> None:
            logical_val = slider_val / multiplier
            txt = f"{logical_val:.{decimals}f}"
            label.setText(f"{txt} {unit}".strip())
            if callback: callback(logical_val)
        
        slider.sliderReleased.connect(lambda: update_lbl(slider.value()))
        slider.valueChanged.connect(lambda v: label.setText(f"{v / multiplier:.{decimals}f} {unit}".strip()))
        return container

    def _setup_color_button(self, button: QPushButton, val: Any, callback: Optional[Callable], is_editor: bool, prop: PropertyDescriptor) -> None:
        """
        Setup color picker button with fallback to qt_colorwheel if available.
        """
        show_label = prop.get("with_label", True)
        button.setProperty("show_label", show_label)
        self._update_color_button_face(button, val)

        def on_click():
            initial = QColor(button.property("color_value"))
            if not initial.isValid(): initial = QColor(Qt.white)
            
            selected_color = None
            if _HAS_COLORWHEEL:
                try:
                    dlg = ColorGeneratorDialog(
                        parent=button, 
                        seed_color=initial.name(), 
                        color_rule="Monochromatic" 
                    )
                    if dlg.exec():
                        generated_colors = dlg.get_colors()
                        if generated_colors: selected_color = generated_colors[0]
                except Exception as e:
                    print(f"ColorGeneratorDialog Error: {e}")
                    selected_color = QColorDialog.getColor(initial, button, "Select Color")
            else:
                selected_color = QColorDialog.getColor(initial, button, "Select Color")

            if selected_color and selected_color.isValid():
                hex_color = selected_color.name()
                self._update_color_button_face(button, hex_color)
                if is_editor:
                    self.commitData.emit(button)
                    self.closeEditor.emit(button)
                elif callback:
                    callback(hex_color)

        button.clicked.connect(on_click)

    def _update_color_button_face(self, button: QPushButton, val: Any) -> None:
        c = QColor(val) if val else QColor(Qt.gray)
        if not c.isValid(): c = QColor(Qt.gray)
        button.setProperty("color_value", c.name())
        show_label = button.property("show_label")
        
        brightness = c.red() * 0.299 + c.green() * 0.587 + c.blue() * 0.114
        text_color = "black" if brightness > 128 else "white"
        
        button.setStyleSheet(f"""
            QPushButton {{ background-color: {c.name()}; color: {text_color}; border: 1px solid #555; border-radius: 4px; font-weight: bold; }}
            QPushButton:hover {{ border: 1px solid {text_color}; }}
        """)
        button.setText(c.name() if show_label else "")

    def create_persistent_widget(self, prop: PropertyDescriptor, val: Any, callback: Callable) -> QWidget:
        t = prop.get("widget_type")
        if t is QSlider: return self._create_slider_widget(None, prop, val, callback)
        if t is QCheckBox:
            c = QWidget(); l = QHBoxLayout(c); l.setContentsMargins(0,0,0,0); l.setAlignment(Qt.AlignCenter)
            w = QCheckBox(); w.setChecked(bool(val)); w.toggled.connect(callback)
            c.input_widget = w; l.addWidget(w)
            return c
        if t in [QDoubleSpinBox, QSpinBox, QLineEdit]:
            creator = self._editor_creators.get(t)
            w = creator(None, prop, val)
            w.editingFinished.connect(lambda: callback(w.value() if hasattr(w, 'value') else w.text()))
            return w
        if t is QComboBox:
            w = self._create_combobox(None, prop, val)
            w.setCurrentText(str(val))
            w.currentTextChanged.connect(callback)
            return w
        if t is QPushButton:
            w = QPushButton()
            self._setup_color_button(w, val, callback, False, prop)
            return w
        return None

# ──────────────────────────────────────────────────────────────
# 2. Unified Control Widget
# ──────────────────────────────────────────────────────────────

class UnifiedTableControlWidget(SpringTableWidget):
    """
    Combines Standard and Transposed logic.
    - transposed=False: Rows=Entities, Cols=Properties (Standard)
    - transposed=True:  Rows=Properties, Cols=Entities (Matrix)
    """
    def __init__(
        self, 
        parent: Optional[QWidget] = None, 
        properties_list: List[PropertyDescriptor] = None, 
        item_list: List[Any] = None,
        transposed: bool = False,
        **kwargs
    ):
        # 1. Disable generic drag/drop to prevent "single cell overwrite" crashes.
        kwargs['enable_row_drag_drop'] = False
        
        super().__init__(parent=parent, **kwargs)

        self.properties_list = properties_list or []
        self.item_list = item_list or []
        self._is_transposed = transposed
        self._is_updating = False 

        # --- SELECTION MODE CONFIGURATION ---
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)

        # --- REORDERING CONFIGURATION ---
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setSectionsMovable(True)
        self.horizontalHeader().setHighlightSections(True)
        self.verticalHeader().setHighlightSections(True)

        # Delegate setup
        self._delegate = UnifiedPropertyDelegate(
            self.properties_list, self, is_transposed=transposed
        )
        self.setItemDelegate(self._delegate)

        self.populate_table()
        
        self.itemChanged.connect(self.on_item_changed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def populate_table(self) -> None:
        """Intelligently populates based on orientation."""
        self.blockSignals(True)
        self.clearContents()

        if self._is_transposed:
            # ROWS = Properties, COLS = Items
            self.setRowCount(len(self.properties_list))
            self.setColumnCount(len(self.item_list))
            
            # Headers
            self.setVerticalHeaderLabels([p.get("label", "") for p in self.properties_list])
            self.setHorizontalHeaderLabels([str(getattr(x, "id_code", f"Item {i}")) for i, x in enumerate(self.item_list)])
            
            self._configure_transposed_columns()
            
            for r, prop in enumerate(self.properties_list):
                for c, obj in enumerate(self.item_list):
                    self._create_cell(r, c, obj, prop)
        else:
            # ROWS = Items, COLS = Properties
            self.setRowCount(len(self.item_list))
            self.setColumnCount(len(self.properties_list))
            
            self.setHorizontalHeaderLabels([p.get("label", "") for p in self.properties_list])
            self.setVerticalHeaderLabels([str(getattr(x, "id_code", str(i+1))) for i, x in enumerate(self.item_list)])
            
            self._configure_standard_columns()
            
            for r, obj in enumerate(self.item_list):
                for c, prop in enumerate(self.properties_list):
                    self._create_cell(r, c, obj, prop)

        self.blockSignals(False)

    def _configure_standard_columns(self):
        config = []
        for prop in self.properties_list:
            col_cfg = {"label": prop.get("label", "")}
            if "min_width" in prop: col_cfg["min_width"] = prop["min_width"]
            config.append(col_cfg)
        if hasattr(self, 'configure_columns'): self.configure_columns(config)

    def _configure_transposed_columns(self):
        max_min = 80
        for p in self.properties_list:
            max_min = max(max_min, p.get("min_width", 0))
        
        config = [{"min_width": max_min} for _ in self.item_list]
        if hasattr(self, 'configure_columns'): self.configure_columns(config)

    def _create_cell(self, row: int, col: int, obj: Any, prop: PropertyDescriptor) -> None:
        val = UnifiedPropertyDelegate.get_value(obj, prop)
        is_editable = prop.get("editable", True)

        if prop.get("always_visible", False):
            def _persist_cb(v):
                self.apply_batch_edit(row, col, v)
            
            w = self._delegate.create_persistent_widget(prop, val, _persist_cb)
            if w:
                if not is_editable: w.setEnabled(False)
                self.setCellWidget(row, col, w)
                item = QTableWidgetItem()
                item.setData(Qt.UserRole, obj) 
                self.setItem(row, col, item)
                return

        unit = prop.get("unit", "")
        formatted_val = UnifiedPropertyDelegate.format_value(val, prop)
        display_text = f"{formatted_val} {unit}".strip()

        item = QTableWidgetItem(display_text)
        item.setData(Qt.EditRole, val)
        item.setData(Qt.DisplayRole, display_text)
        item.setData(Qt.UserRole, obj)
        
        if not is_editable or prop.get("readonly", False):
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            
        self.setItem(row, col, item)
    
    def apply_batch_edit(self, row: int, col: int, value: Any) -> None:
        if self._is_updating: return
        self._is_updating = True
        self.blockSignals(True)
        
        try:
            source_prop_idx = row if self._is_transposed else col
            if source_prop_idx >= len(self.properties_list): return
            prop = self.properties_list[source_prop_idx]

            if not prop.get("editable", True): return

            source_index = self.model().index(row, col)
            is_selected = self.selectionModel().isSelected(source_index)
            
            targets_indices = []

            if is_selected:
                selected_indexes = self.selectionModel().selectedIndexes()
                for idx in selected_indexes:
                    i_r, i_c = idx.row(), idx.column()
                    
                    idx_prop_index = i_r if self._is_transposed else i_c
                    if idx_prop_index == source_prop_idx:
                        targets_indices.append((i_r, i_c))
            else:
                targets_indices.append((row, col))

            for t_row, t_col in targets_indices:
                target_item_idx = t_col if self._is_transposed else t_row
                if target_item_idx >= len(self.item_list): continue
                
                obj = self.item_list[target_item_idx]
                UnifiedPropertyDelegate.set_value(obj, prop, value)
                
                item = self.item(t_row, t_col)
                if item:
                    item.setData(Qt.EditRole, value)
                    item.setData(Qt.UserRole, obj)
                    if not prop.get("always_visible", False):
                        unit = prop.get("unit", "")
                        formatted = UnifiedPropertyDelegate.format_value(value, prop)
                        item.setData(Qt.DisplayRole, f"{formatted} {unit}".strip())
                
                if prop.get("always_visible", False):
                    widget = self.cellWidget(t_row, t_col)
                    if widget: self._update_persistent_widget(widget, value, prop)

        finally:
            self.blockSignals(False)
            self._is_updating = False

    def on_item_changed(self, item: QTableWidgetItem) -> None:
        if not item or self._is_updating: return
        self._is_updating = True
        self.blockSignals(True)
        try:
            row, col = item.row(), item.column()
            
            if self._is_transposed:
                if row >= len(self.properties_list): return
                if col >= len(self.item_list): return
                prop = self.properties_list[row]
                obj = item.data(Qt.UserRole) or self.item_list[col]
            else:
                if col >= len(self.properties_list): return
                if row >= len(self.item_list): return
                prop = self.properties_list[col]
                obj = item.data(Qt.UserRole) or self.item_list[row]

            val = item.data(Qt.EditRole)
            UnifiedPropertyDelegate.set_value(obj, prop, val)
            
            if not prop.get("always_visible", False):
                unit = prop.get("unit", "")
                formatted = UnifiedPropertyDelegate.format_value(val, prop)
                item.setData(Qt.DisplayRole, f"{formatted} {unit}".strip())
        except Exception as e:
            print(f"Update error: {e}")
        finally:
            self.blockSignals(False)
            self._is_updating = False

    def _update_persistent_widget(self, widget: QWidget, val: Any, prop: PropertyDescriptor) -> None:
        widget.blockSignals(True)
        try:
            if hasattr(widget, "input_widget"): widget.input_widget.setChecked(bool(val))
            elif hasattr(widget, "slider"): 
                decimals = prop.get("decimals", 0)
                multiplier = 10 ** decimals
                widget.slider.setValue(int(float(val) * multiplier))
                if hasattr(widget, "label"):
                    widget.label.setText(f"{float(val):.{decimals}f} {prop.get('unit','')}".strip())
            elif isinstance(widget, (QDoubleSpinBox, QSpinBox)): 
                widget.setValue(float(val))
            elif isinstance(widget, QComboBox): 
                widget.setCurrentText(str(val))
            elif isinstance(widget, QPushButton): 
                self._delegate._update_color_button_face(widget, val)
        finally:
            widget.blockSignals(False)

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None: return
        
        if self._is_transposed:
            prop = self.properties_list[item.row()]
        else:
            prop = self.properties_list[item.column()]
            
        if not prop.get("editable", True) or "default" not in prop: return
        
        menu = QMenu(self)
        action = menu.addAction(f"Reset '{prop['label']}' to {prop['default']}")
        if menu.exec(self.viewport().mapToGlobal(pos)) == action:
            self.apply_batch_edit(item.row(), item.column(), prop['default'])

# ──────────────────────────────────────────────────────────────
# Example Usage
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    class SimEntity:
        def __init__(self, name, mass, material):
            self.id_code = name
            self.mass = mass
            self.material = material
            self.color = "#3498db"
            self.visible = True
            self.velocity = 0.0
            # FIX: Initialize particles to avoid 'None' display issue
            self.particles = 100 
            self.opacity = 1.0
            self.start_time = "00:00:00"
            self.last_updated = "2025-01-01"
            
        def get_momentum(self): return self.mass * self.velocity
        def set_momentum(self, value):
            try:
                m = float(self.mass)
                if m > 0: self.velocity = value / m
            except (ValueError, TypeError): pass

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion") 

    props: List[PropertyDescriptor] = [
        {"attr": "id_code", "label": "ID", "widget_type": QLineEdit, "value_type": "alphanumeric", "default": "ENT_001", "min_width": 80},
        {"attr": "notes", "label": "Notes (Locked)", "widget_type": QLineEdit, "editable": False, "default": "", "min_width": 100},
        {"attr": "mass", "label": "Mass", "widget_type": QDoubleSpinBox, "unit": "kg", "value_range": (0.1, 1000.0), "decimals": 1, "step_size": 0.5, "default": 10.0, "min_width": 70},
        {"attr": "velocity", "label": "Velocity", "widget_type": QDoubleSpinBox, "unit": "m/s", "decimals": 4, "step_size": 0.0001, "default": 0.0, "min_width": 70},
        {"attr": "particles", "label": "Particles", "widget_type": QSpinBox, "unit": "cnt", "step_size": 10, "default": 100},
        {"attr": "opacity", "label": "Opacity", "widget_type": QSlider, "decimals": 2, "value_range": (0.0, 1.0), "always_visible": True, "default": 1.0, "min_width": 150},
        {"attr": "limit_gauge", "label": "Gauge (Locked)", "widget_type": QSlider, "decimals": 2, "always_visible": True, "editable": False, "value_range": (0.0, 1.0), "default": 0.0, "min_width": 150},
        {"attr": "material_type", "label": "Material", "widget_type": QComboBox, "items": ["Silicon", "Gallium", "Vacuum", "Gold"], "always_visible": True, "default": "Vacuum", "min_width": 90},
        {"attr": "is_visible", "label": "Visible", "widget_type": QCheckBox, "always_visible": True, "default": True, "min_width": 60},
        {"attr": "color_primary", "label": "Color 1", "widget_type": QPushButton, "always_visible": True, "with_label": True, "default": "#000000", "min_width": 80},
        {"attr": "color_accent", "label": "Color 2", "widget_type": QPushButton, "always_visible": True, "with_label": False, "default": "#FFFFFF", "min_width": 50},
        {"attr": "start_time", "label": "Time", "widget_type": QTimeEdit, "precision": "secs", "default": "00:00:00"},
        {"attr": "last_updated", "label": "Date", "widget_type": QDateEdit, "default": "2025-01-01"},
        {"label": "Momentum (Calc)", "widget_type": QDoubleSpinBox, "unit": "kg⋅m/s", "getter": lambda obj: obj.get_momentum(), "setter": lambda obj, val: obj.set_momentum(val), "decimals": 2, "min_width": 100}
    ]

    data = [SimEntity(f"ENT_{i}", 10.0 + i, "Si") for i in range(5)]

    win = QMainWindow()
    central = QWidget()
    layout = QHBoxLayout(central)

    # 1. Standard Mode (List View)
    tbl_standard = UnifiedTableControlWidget(
        properties_list=props, item_list=data, transposed=False, 
        show_headers=True, alternating_rows=True
    )
    
    # 2. Transposed Mode (Card View)
    tbl_transposed = UnifiedTableControlWidget(
        properties_list=props, item_list=data, transposed=True, 
        show_headers=True, alternating_rows=True, alternate_color="lighter"
    )

    dock1 = QDockWidget("Standard (Row=Item)", win)
    dock1.setWidget(tbl_standard)
    dock2 = QDockWidget("Transposed (Row=Prop)", win)
    dock2.setWidget(tbl_transposed)

    win.addDockWidget(Qt.LeftDockWidgetArea, dock1)
    win.addDockWidget(Qt.RightDockWidgetArea, dock2)
    win.resize(1200, 600)
    win.show()

    sys.exit(app.exec())