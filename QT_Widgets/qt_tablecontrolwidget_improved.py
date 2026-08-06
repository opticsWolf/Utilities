# -*- coding: utf-8 -*-
"""
PADDOL: Unified Table Control Widget (Standard & Transposed)
Copyright (c) 2025 opticsWolf

SPDX-License-Identifier: LGPL-3.0-or-later

A single-class structure handling both Column-based (List) and Row-based (Card)
property table views via a ``transposed`` flag.

Classes
-------
PropertyDescriptor     TypedDict schema for property definitions.
UnifiedPropertyDelegate  Axis-aware delegate (painting, editing, formatting).
UnifiedTableControlWidget  The combined table widget.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Literal, Optional, Type, TypedDict, Union

from PySide6.QtCore import (
    QAbstractItemModel, QDate, QModelIndex, QPoint,
    QRegularExpression, Qt, QTime,
)
from PySide6.QtGui import (
    QAction, QColor, QDoubleValidator, QIntValidator,
    QPainter, QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
    QDateEdit, QDockWidget, QDoubleSpinBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSlider, QSpinBox,
    QStyle, QStyleOptionViewItem, QStyledItemDelegate, QTableWidgetItem,
    QTimeEdit, QVBoxLayout, QWidget,
)

# ──────────────────────────────────────────────────────────────
# Robust Dependency Loading
# ──────────────────────────────────────────────────────────────

# A. Spring Table — graceful fallback if the custom library is absent
try:
    from qt_springtable import SpringTableWidget
except ImportError:
    from PySide6.QtWidgets import QTableWidget

    class SpringTableWidget(QTableWidget):  # type: ignore[no-redef]
        """Minimal stand-in so the widget still runs without qt_springtable."""
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__()
            self.setAlternatingRowColors(kwargs.get("alternating_rows", False))
            self.setSortingEnabled(kwargs.get("enable_sorting", False))

        def configure_columns(self, config: list) -> None:  # noqa: D401
            """No-op stub."""

# B. Colour Wheel — optional richer colour picker
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
    value_type: str                     # "numeric" | "integer" | "alphabetic" | "alphanumeric"
    readonly: bool
    editable: bool
    unit: str
    value_range: tuple[float, float]
    step_size: float
    decimals: int
    items: List[str]                    # ComboBox options
    always_visible: bool                # Persist widget in cell
    orientation: Qt.Orientation         # Slider orientation
    getter: Callable[[Any], Any]
    setter: Callable[[Any, Any], None]
    default: Any
    precision: Literal["min", "secs"]   # TimeEdit precision
    with_label: bool                    # Hex label on colour buttons
    min_width: int
    max_width: int
    draggable: bool


# ──────────────────────────────────────────────────────────────
# 1. Unified Delegate
# ──────────────────────────────────────────────────────────────

class UnifiedPropertyDelegate(QStyledItemDelegate):
    """
    Axis-aware delegate handling editor creation, painting, data round-
    tripping and persistent-widget factory for all supported widget types.

    Parameters
    ----------
    is_transposed : bool
        ``False`` → property index = ``index.column()`` (standard).
        ``True``  → property index = ``index.row()``    (transposed).
    """

    # ── Construction ──────────────────────────────────────────

    def __init__(
        self,
        properties: List[PropertyDescriptor],
        parent: Optional[QWidget] = None,
        is_transposed: bool = False,
    ) -> None:
        super().__init__(parent)
        self._properties = properties
        self._is_transposed = is_transposed

        # O(1) dispatch tables — avoids long if/elif chains
        self._editor_creators: Dict[Type[QWidget], Callable] = {
            QCheckBox:      self._create_checkbox,
            QDoubleSpinBox: self._create_double_spinbox,
            QSpinBox:       self._create_spinbox,
            QLineEdit:      self._create_line_edit,
            QComboBox:      self._create_combobox,
            QSlider:        self._create_slider_wrapper,
            QTimeEdit:      self._create_time_edit,
            QDateEdit:      self._create_date_edit,
            QPushButton:    self._create_color_button,
        }

        self._editor_setters: Dict[Type[QWidget], Callable] = {
            QCheckBox:      lambda w, v, _p: w.setChecked(bool(v)),
            QDoubleSpinBox: lambda w, v, _p: w.setValue(float(v) if v is not None else 0.0),
            QSpinBox:       lambda w, v, _p: w.setValue(int(float(v)) if v is not None else 0),
            QLineEdit:      lambda w, v, _p: w.setText(str(v) if v is not None else ""),
            QComboBox:      self._set_combo_data,
            QTimeEdit:      lambda w, v, _p: w.setTime(self._to_qtime(v)),
            QDateEdit:      lambda w, v, _p: w.setDate(self._to_qdate(v)),
            QPushButton:    lambda w, v, _p: self._update_color_button_face(w, v),
        }

        self._value_extractors: Dict[Type[QWidget], Callable] = {
            QCheckBox:      lambda w: w.isChecked(),
            QDoubleSpinBox: lambda w: w.value(),
            QSpinBox:       lambda w: w.value(),
            QLineEdit:      lambda w: w.text(),
            QComboBox:      lambda w: w.currentText(),
            QTimeEdit:      lambda w: w.time(),
            QDateEdit:      lambda w: w.date(),
            QPushButton:    lambda w: w.property("color_value"),
        }

    # ── Axis helpers ──────────────────────────────────────────

    def _prop_index(self, index: QModelIndex) -> int:
        return index.row() if self._is_transposed else index.column()

    def _get_property(self, index: QModelIndex) -> PropertyDescriptor:
        if not index.isValid():
            return {}
        idx = self._prop_index(index)
        if 0 <= idx < len(self._properties):
            return self._properties[idx]
        return {}

    # ── Static value helpers ──────────────────────────────────

    @staticmethod
    def get_value(obj: Any, prop: PropertyDescriptor) -> Any:
        """
        Read the current value from *obj* for *prop*.

        Falls back to ``prop["default"]`` when the attribute is missing or
        ``None``, preventing empty display cells.
        """
        if obj is None:
            return prop.get("default")

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

        if (val is None or not found) and "default" in prop:
            return prop["default"]
        return val

    @staticmethod
    def set_value(obj: Any, prop: PropertyDescriptor, value: Any) -> None:
        """Safely push *value* into *obj*, swallowing errors to prevent crashes."""
        if obj is None:
            return
        try:
            if "setter" in prop:
                prop["setter"](obj, value)
                return
            attr = prop.get("attr")
            if not attr:
                return
            target = getattr(obj, attr, None)
            if callable(target):
                try:
                    target(value)
                except TypeError:
                    pass
            else:
                setattr(obj, attr, value)
        except Exception as exc:
            print(f"[UnifiedPropertyDelegate] Error setting value: {exc}")

    # ── Formatting ────────────────────────────────────────────

    @staticmethod
    def format_value(val: Any, prop: PropertyDescriptor) -> str:
        if val is None:
            return ""
        if isinstance(val, QTime) or prop.get("widget_type") is QTimeEdit:
            fmt = "HH:mm:ss" if prop.get("precision") == "secs" else "HH:mm"
            return UnifiedPropertyDelegate._to_qtime(val).toString(fmt)
        if isinstance(val, QDate) or prop.get("widget_type") is QDateEdit:
            return UnifiedPropertyDelegate._to_qdate(val).toString("yyyy-MM-dd")
        if isinstance(val, bool):
            return str(val)
        if isinstance(val, (float, int)):
            if "decimals" in prop:
                return f"{val:.{prop['decimals']}f}"
            if val == 0:
                return "0"
            abs_val = abs(val)
            if abs_val < 0.001 or abs_val >= 100_000:
                return f"{val:.3e}"
            text = f"{val:.3f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return text
        return str(val)

    # ── Conversion helpers ────────────────────────────────────

    @staticmethod
    def _to_qtime(val: Any) -> QTime:
        if isinstance(val, QTime):
            return val
        if isinstance(val, str):
            return QTime.fromString(val)
        return QTime.currentTime()

    @staticmethod
    def _to_qdate(val: Any) -> QDate:
        if isinstance(val, QDate):
            return val
        if isinstance(val, str):
            return QDate.fromString(val, Qt.ISODate)
        return QDate.currentDate()

    @staticmethod
    def _calculate_dynamic_limits(val: Any) -> tuple[float, float]:
        try:
            v = float(val) if val is not None else 0.0
        except (ValueError, TypeError):
            v = 0.0
        if abs(v) < 1e-9:
            return (0.0, 100.0)
        lower, upper = v * 0.05, v * 2.0
        return (min(lower, upper), max(lower, upper))

    # ── Editor factory methods (used by dispatch table) ───────

    @staticmethod
    def _create_checkbox(parent: QWidget, _prop: PropertyDescriptor, _val: Any) -> QCheckBox:
        return QCheckBox(parent)

    def _create_double_spinbox(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QDoubleSpinBox:
        w = QDoubleSpinBox(parent)
        w.setDecimals(prop.get("decimals", 2))
        if "value_range" in prop:
            w.setRange(*prop["value_range"])
        else:
            w.setRange(*self._calculate_dynamic_limits(val))
        if "step_size" in prop:
            w.setSingleStep(prop["step_size"])
        if "unit" in prop:
            w.setSuffix(f" {prop['unit']}")
        w.setValue(float(val) if val is not None else 0.0)
        return w

    def _create_spinbox(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QSpinBox:
        w = QSpinBox(parent)
        rng = prop.get("value_range") or self._calculate_dynamic_limits(val)
        w.setRange(int(rng[0]), int(rng[1]))
        if "step_size" in prop:
            w.setSingleStep(int(prop["step_size"]))
        if "unit" in prop:
            w.setSuffix(f" {prop['unit']}")
        w.setValue(int(float(val)) if val is not None else 0)
        return w

    @staticmethod
    def _create_line_edit(parent: QWidget, prop: PropertyDescriptor, val: Any) -> QLineEdit:
        w = QLineEdit(parent)
        validators: Dict[str, Callable[[], Any]] = {
            "numeric":      lambda: QDoubleValidator(w),
            "integer":      lambda: QIntValidator(w),
            "alphabetic":   lambda: QRegularExpressionValidator(QRegularExpression(r"^[a-zA-Z]*$"), w),
            "alphanumeric": lambda: QRegularExpressionValidator(QRegularExpression(r"^[a-zA-Z0-9_()-]*$"), w),
        }
        vt = prop.get("value_type")
        if vt in validators:
            w.setValidator(validators[vt]())
        w.setText(str(val) if val is not None else "")
        return w

    def _create_combobox(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QComboBox:
        w = QComboBox(parent)
        w.addItems(prop.get("items", []))
        if val is not None:
            idx = w.findText(str(val))
            if idx >= 0:
                w.setCurrentIndex(idx)
        return w

    def _create_slider_wrapper(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QWidget:
        return self._create_slider_widget(parent, prop, val, None)

    def _create_time_edit(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QTimeEdit:
        w = QTimeEdit(parent)
        w.setDisplayFormat("HH:mm:ss" if prop.get("precision") == "secs" else "HH:mm")
        w.setTime(self._to_qtime(val))
        return w

    def _create_date_edit(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QDateEdit:
        w = QDateEdit(parent)
        w.setCalendarPopup(True)
        w.setDisplayFormat("yyyy-MM-dd")
        w.setDate(self._to_qdate(val))
        return w

    def _create_color_button(self, parent: QWidget, prop: PropertyDescriptor, val: Any) -> QPushButton:
        w = QPushButton(parent)
        self._setup_color_button(w, val, None, is_editor=True, prop=prop)
        return w

    # ── Delegate overrides ────────────────────────────────────

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> Optional[QWidget]:
        prop = self._get_property(index)
        if not prop or not prop.get("editable", True):
            return None

        creator = self._editor_creators.get(prop.get("widget_type"))
        if not creator:
            return super().createEditor(parent, option, index)

        obj = index.data(Qt.UserRole)
        current_val = self.get_value(obj, prop) if obj else index.data(Qt.EditRole)
        return creator(parent, prop, current_val)

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        prop = self._get_property(index)
        if not prop:
            return
        obj = index.data(Qt.UserRole)
        value = self.get_value(obj, prop) if obj is not None else index.data(Qt.EditRole)

        # Slider containers need special handling (composite widget)
        if hasattr(editor, "slider"):
            decimals = prop.get("decimals", 0)
            multiplier = 10 ** decimals
            editor.slider.setValue(int(float(value) * multiplier) if value is not None else 0)
            return

        setter = self._editor_setters.get(type(editor))
        if setter:
            try:
                setter(editor, value, prop)
            except (ValueError, TypeError):
                pass

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex) -> None:
        prop = self._get_property(index)

        if hasattr(editor, "slider"):
            val = editor.slider.value() / (10 ** prop.get("decimals", 0))
        else:
            extractor = self._value_extractors.get(type(editor))
            val = extractor(editor) if extractor else None

        table_widget = self.parent()
        if table_widget and hasattr(table_widget, "apply_batch_edit"):
            table_widget.apply_batch_edit(index.row(), index.column(), val)
        else:
            model.setData(index, val, Qt.EditRole)

    def destroyEditor(self, editor: QWidget, index: QModelIndex) -> None:
        if index.isValid():
            parent_widget = self.parent()
            if parent_widget and hasattr(parent_widget, "_is_updating"):
                parent_widget._is_updating = True

            prop = self._get_property(index)
            val = index.data(Qt.EditRole)
            unit = prop.get("unit", "")
            formatted = self.format_value(val, prop)
            display = formatted if unit and formatted.endswith(unit) else f"{formatted} {unit}".strip()
            index.model().setData(index, display, Qt.DisplayRole)

            if parent_widget and hasattr(parent_widget, "_is_updating"):
                parent_widget._is_updating = False

        super().destroyEditor(editor, index)

    # ── Painting ──────────────────────────────────────────────

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if not index.isValid():
            return
        prop = self._get_property(index)

        if prop.get("always_visible", False):
            self._draw_empty_cell(painter, option, index)
            return

        if prop.get("widget_type") is QPushButton:
            self._paint_color_swatch(painter, option, index, prop)
            return

        super().paint(painter, option, index)

    @staticmethod
    def _draw_empty_cell(painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        opt.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter)

    @staticmethod
    def _paint_color_swatch(
        painter: QPainter, option: QStyleOptionViewItem,
        index: QModelIndex, prop: PropertyDescriptor,
    ) -> None:
        val = index.data(Qt.EditRole)
        color = QColor(val) if val else QColor(Qt.transparent)
        if not color.isValid():
            return
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

    # ── Slider helper ─────────────────────────────────────────

    def _create_slider_widget(
        self, parent: Optional[QWidget], prop: PropertyDescriptor,
        val: Any, callback: Optional[Callable],
    ) -> QWidget:
        container = QWidget(parent)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        slider = QSlider(prop.get("orientation", Qt.Horizontal))
        decimals = prop.get("decimals", 0)
        multiplier = 10 ** decimals

        logical_rng = prop.get("value_range") or self._calculate_dynamic_limits(val)
        slider.setRange(int(logical_rng[0] * multiplier), int(logical_rng[1] * multiplier))

        try:
            float_val = float(val) if val is not None else float(logical_rng[0])
        except (ValueError, TypeError):
            float_val = float(logical_rng[0])
        slider.setValue(int(float_val * multiplier))

        unit = prop.get("unit", "")
        formatted = self.format_value(val if val is not None else 0, prop)
        label = QLabel(f"{formatted} {unit}".strip())
        label.setFixedWidth(50)

        layout.addWidget(slider)
        layout.addWidget(label)
        container.slider = slider
        container.label = label

        def _on_slider_update(slider_val: int) -> None:
            logical = slider_val / multiplier
            label.setText(f"{logical:.{decimals}f} {unit}".strip())
            if callback:
                callback(logical)

        slider.sliderReleased.connect(lambda: _on_slider_update(slider.value()))
        slider.valueChanged.connect(
            lambda v: label.setText(f"{v / multiplier:.{decimals}f} {unit}".strip())
        )
        return container

    # ── Colour-button helpers ─────────────────────────────────

    def _setup_color_button(
        self, button: QPushButton, val: Any, callback: Optional[Callable],
        is_editor: bool, prop: PropertyDescriptor,
    ) -> None:
        show_label = prop.get("with_label", True)
        button.setProperty("show_label", show_label)
        self._update_color_button_face(button, val)

        def _on_click() -> None:
            initial = QColor(button.property("color_value"))
            if not initial.isValid():
                initial = QColor(Qt.white)

            selected_color: Optional[QColor] = None

            # Try the richer colour-wheel dialog if available
            if _HAS_COLORWHEEL:
                try:
                    dlg = ColorGeneratorDialog(
                        parent=button,
                        seed_color=initial.name(),
                        color_rule="Monochromatic",
                    )
                    if dlg.exec():
                        generated = dlg.get_colors()
                        if generated:
                            selected_color = generated[0]
                except Exception:
                    selected_color = None  # fall through to standard dialog

            if selected_color is None:
                selected_color = QColorDialog.getColor(initial, button, "Select Color")

            if selected_color and selected_color.isValid():
                hex_color = selected_color.name()
                self._update_color_button_face(button, hex_color)
                if is_editor:
                    self.commitData.emit(button)
                    self.closeEditor.emit(button)
                elif callback:
                    callback(hex_color)

        button.clicked.connect(_on_click)

    @staticmethod
    def _update_color_button_face(button: QPushButton, val: Any) -> None:
        c = QColor(val) if val else QColor(Qt.gray)
        if not c.isValid():
            c = QColor(Qt.gray)
        button.setProperty("color_value", c.name())
        show_label = button.property("show_label")
        if show_label is None:
            show_label = True

        brightness = c.red() * 0.299 + c.green() * 0.587 + c.blue() * 0.114
        text_color = "black" if brightness > 128 else "white"
        button.setStyleSheet(
            f"QPushButton {{ background-color: {c.name()}; color: {text_color}; "
            f"border: 1px solid #555; border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:hover {{ border: 1px solid {text_color}; }}"
        )
        button.setText(c.name() if show_label else "")

    @staticmethod
    def _set_combo_data(editor: QComboBox, value: Any, _prop: PropertyDescriptor) -> None:
        idx = editor.findText(str(value))
        if idx >= 0:
            editor.setCurrentIndex(idx)

    # ── Persistent widget factory ─────────────────────────────

    def create_persistent_widget(
        self, prop: PropertyDescriptor, val: Any, callback: Callable,
    ) -> Optional[QWidget]:
        """Create an always-visible in-cell widget with a change *callback*."""
        t = prop.get("widget_type")

        # Slider — fully custom composite
        if t is QSlider:
            return self._create_slider_widget(None, prop, val, callback)

        # Checkbox — centred in a container
        if t is QCheckBox:
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignCenter)
            cb = QCheckBox()
            cb.setChecked(bool(val))
            cb.toggled.connect(callback)
            container.input_widget = cb
            layout.addWidget(cb)
            return container

        # Types that reuse the editor factory with a signal wired to the callback
        if t in (QDoubleSpinBox, QSpinBox, QLineEdit):
            creator = self._editor_creators.get(t)
            if not creator:
                return None
            w = creator(None, prop, val)
            w.editingFinished.connect(lambda: callback(w.value() if hasattr(w, "value") else w.text()))
            return w

        if t is QComboBox:
            w = self._create_combobox(None, prop, val)
            w.currentTextChanged.connect(callback)
            return w

        if t is QTimeEdit:
            w = self._create_time_edit(None, prop, val)
            w.timeChanged.connect(callback)
            return w

        if t is QDateEdit:
            w = self._create_date_edit(None, prop, val)
            w.dateChanged.connect(callback)
            return w

        if t is QPushButton:
            w = QPushButton()
            self._setup_color_button(w, val, callback, is_editor=False, prop=prop)
            return w

        return None


# ──────────────────────────────────────────────────────────────
# 2. Unified Control Widget
# ──────────────────────────────────────────────────────────────

class UnifiedTableControlWidget(SpringTableWidget):
    """
    Combined property-table widget supporting both standard and transposed
    orientations.

    Parameters
    ----------
    transposed : bool
        ``False`` → rows = data items, columns = properties  (list view).
        ``True``  → rows = properties, columns = data items  (card view).
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        properties_list: Optional[List[PropertyDescriptor]] = None,
        item_list: Optional[List[Any]] = None,
        transposed: bool = False,
        **kwargs: Any,
    ):
        # Disable generic row drag-drop to prevent single-cell-overwrite crashes;
        # header-based reordering is enabled separately below.
        kwargs["enable_row_drag_drop"] = False
        super().__init__(parent=parent, **kwargs)

        self.properties_list: List[PropertyDescriptor] = properties_list or []
        self.item_list: List[Any] = item_list or []
        self._is_transposed: bool = transposed
        self._is_updating: bool = False

        # --- Selection ---
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)

        # --- Reordering via header drag (not cell drag) ---
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.horizontalHeader().setSectionsMovable(True)
        self.verticalHeader().setSectionsMovable(True)
        self.horizontalHeader().setHighlightSections(True)
        self.verticalHeader().setHighlightSections(True)

        # --- Delegate ---
        self._delegate = UnifiedPropertyDelegate(
            self.properties_list, self, is_transposed=transposed,
        )
        self.setItemDelegate(self._delegate)

        self.populate_table()

        self.itemChanged.connect(self.on_item_changed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ── Axis helpers ──────────────────────────────────────────

    def _prop_idx(self, row: int, col: int) -> int:
        return row if self._is_transposed else col

    def _item_idx(self, row: int, col: int) -> int:
        return col if self._is_transposed else row

    # ── Column configuration ──────────────────────────────────

    def _configure_standard_columns(self) -> None:
        config: list[dict] = []
        for prop in self.properties_list:
            col_cfg: dict[str, Any] = {"label": prop.get("label", "")}
            if "min_width" in prop:
                col_cfg["min_width"] = prop["min_width"]
            if "max_width" in prop:
                col_cfg["max_width"] = prop["max_width"]
            config.append(col_cfg)
        if hasattr(self, "configure_columns"):
            self.configure_columns(config)

    def _configure_transposed_columns(self) -> None:
        max_min = max((p.get("min_width", 0) for p in self.properties_list), default=80)
        max_min = max(max_min, 80)
        config = [{"min_width": max_min} for _ in self.item_list]
        if hasattr(self, "configure_columns"):
            self.configure_columns(config)

    # ── Item label derivation ─────────────────────────────────

    @staticmethod
    def _item_label(item: Any, fallback_idx: int) -> str:
        for attr in ("id_code", "name"):
            if hasattr(item, attr):
                return str(getattr(item, attr))
        return f"Item {fallback_idx + 1}"

    # ── Population ────────────────────────────────────────────

    def populate_table(self) -> None:
        """(Re-)populate every cell from the current item_list."""
        self.blockSignals(True)
        self.clearContents()

        if self._is_transposed:
            self.setRowCount(len(self.properties_list))
            self.setColumnCount(len(self.item_list))
            self.setVerticalHeaderLabels([p.get("label", "") for p in self.properties_list])
            self.setHorizontalHeaderLabels(
                [self._item_label(x, i) for i, x in enumerate(self.item_list)]
            )
            self._configure_transposed_columns()
            for r, prop in enumerate(self.properties_list):
                for c, obj in enumerate(self.item_list):
                    self._create_cell(r, c, obj, prop)
        else:
            self.setRowCount(len(self.item_list))
            self.setColumnCount(len(self.properties_list))
            self.setHorizontalHeaderLabels([p.get("label", "") for p in self.properties_list])
            self.setVerticalHeaderLabels(
                [self._item_label(x, i) for i, x in enumerate(self.item_list)]
            )
            self._configure_standard_columns()
            for r, obj in enumerate(self.item_list):
                for c, prop in enumerate(self.properties_list):
                    self._create_cell(r, c, obj, prop)

        self.blockSignals(False)

    def _create_cell(self, row: int, col: int, obj: Any, prop: PropertyDescriptor) -> None:
        val = UnifiedPropertyDelegate.get_value(obj, prop)
        is_editable = prop.get("editable", True)

        # Persistent widgets (sliders, combos, checkboxes, colour buttons, …)
        if prop.get("always_visible", False):
            # FIX: capture row/col by default-arg to avoid late-binding closure bug
            def _persist_cb(v: Any, _r: int = row, _c: int = col) -> None:
                self.apply_batch_edit(_r, _c, v)

            widget = self._delegate.create_persistent_widget(prop, val, _persist_cb)
            if widget:
                if not is_editable:
                    widget.setEnabled(False)
                self.setCellWidget(row, col, widget)
                item = QTableWidgetItem()
                item.setData(Qt.UserRole, obj)
                self.setItem(row, col, item)
                return

        # Standard text-display items
        unit = prop.get("unit", "")
        formatted = UnifiedPropertyDelegate.format_value(val, prop)
        display = f"{formatted} {unit}".strip()

        item = QTableWidgetItem(display)
        item.setData(Qt.EditRole, val)
        item.setData(Qt.DisplayRole, display)
        item.setData(Qt.UserRole, obj)

        if not is_editable or prop.get("readonly", False):
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)

        self.setItem(row, col, item)

    # ── Batch editing ─────────────────────────────────────────

    def apply_batch_edit(self, row: int, col: int, value: Any) -> None:
        """
        Apply *value* to the property identified by (row, col).

        If additional cells sharing the same property axis are selected,
        batch-apply to all of them.
        """
        if self._is_updating:
            return
        self._is_updating = True
        self.blockSignals(True)

        try:
            source_prop_idx = self._prop_idx(row, col)
            if source_prop_idx >= len(self.properties_list):
                return
            prop = self.properties_list[source_prop_idx]
            if not prop.get("editable", True):
                return

            # Resolve which cells to update
            targets = self._resolve_batch_targets(row, col, source_prop_idx)

            for t_row, t_col in targets:
                item_idx = self._item_idx(t_row, t_col)
                if item_idx >= len(self.item_list):
                    continue

                obj = self.item_list[item_idx]
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
                    if widget:
                        self._update_persistent_widget(widget, value, prop)
        finally:
            self.blockSignals(False)
            self._is_updating = False

    def _resolve_batch_targets(
        self, row: int, col: int, source_prop_idx: int,
    ) -> List[tuple[int, int]]:
        """
        Determine which (row, col) cells should receive the batch edit.

        Only cells sharing the same property index as the source are included.
        """
        source_index = self.model().index(row, col)
        is_selected = self.selectionModel().isSelected(source_index)

        if is_selected:
            targets: list[tuple[int, int]] = []
            for idx in self.selectionModel().selectedIndexes():
                if self._prop_idx(idx.row(), idx.column()) == source_prop_idx:
                    targets.append((idx.row(), idx.column()))
            return targets

        return [(row, col)]

    # ── Item-changed handler ──────────────────────────────────

    def on_item_changed(self, item: QTableWidgetItem) -> None:
        if not item or self._is_updating:
            return
        self._is_updating = True
        self.blockSignals(True)
        try:
            row, col = item.row(), item.column()
            pi = self._prop_idx(row, col)
            ii = self._item_idx(row, col)
            if pi >= len(self.properties_list) or ii >= len(self.item_list):
                return

            prop = self.properties_list[pi]
            obj = item.data(Qt.UserRole) or self.item_list[ii]
            val = item.data(Qt.EditRole)

            UnifiedPropertyDelegate.set_value(obj, prop, val)

            if not prop.get("always_visible", False):
                unit = prop.get("unit", "")
                formatted = UnifiedPropertyDelegate.format_value(val, prop)
                item.setData(Qt.DisplayRole, f"{formatted} {unit}".strip())
        except Exception as exc:
            print(f"[UnifiedTableControlWidget] on_item_changed error: {exc}")
        finally:
            self.blockSignals(False)
            self._is_updating = False

    # ── Persistent-widget value push ──────────────────────────

    def _update_persistent_widget(
        self, widget: QWidget, val: Any, prop: PropertyDescriptor,
    ) -> None:
        """Push a new value into an always-visible cell widget without triggering signals."""
        widget.blockSignals(True)
        try:
            decimals = prop.get("decimals", 0)
            multiplier = 10 ** decimals

            # Dynamically adjust range when no fixed range is set
            if "value_range" not in prop:
                new_min, new_max = UnifiedPropertyDelegate._calculate_dynamic_limits(val)
                if hasattr(widget, "slider"):
                    widget.slider.setRange(int(new_min * multiplier), int(new_max * multiplier))
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setRange(new_min, new_max)
                elif isinstance(widget, QSpinBox):
                    widget.setRange(int(new_min), int(new_max))

            # Update the actual value
            if hasattr(widget, "input_widget"):
                widget.input_widget.setChecked(bool(val))
            elif hasattr(widget, "slider"):
                widget.slider.setValue(int(float(val) * multiplier))
                if hasattr(widget, "label"):
                    unit = prop.get("unit", "")
                    widget.label.setText(f"{float(val):.{decimals}f} {unit}".strip())
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(val) if val is not None else 0.0)
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(float(val)) if val is not None else 0)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(val))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(val) if val is not None else "")
            elif isinstance(widget, QTimeEdit):
                widget.setTime(UnifiedPropertyDelegate._to_qtime(val))
            elif isinstance(widget, QDateEdit):
                widget.setDate(UnifiedPropertyDelegate._to_qdate(val))
            elif isinstance(widget, QPushButton):
                self._delegate._update_color_button_face(widget, val)
        finally:
            widget.blockSignals(False)

    # ── Context menu ──────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None:
            return

        row, col = item.row(), item.column()
        pi = self._prop_idx(row, col)
        if pi >= len(self.properties_list):
            return
        prop = self.properties_list[pi]

        if not prop.get("editable", True) or "default" not in prop:
            return

        menu = QMenu(self)
        label = prop.get("label", "")
        unit = prop.get("unit", "")
        default_str = f"{prop['default']}"
        if unit:
            default_str += f" {unit}"
        action = menu.addAction(f"Reset '{label}' to {default_str}")

        if menu.exec(self.viewport().mapToGlobal(pos)) == action:
            self.apply_batch_edit(row, col, prop["default"])


# ──────────────────────────────────────────────────────────────
# Demo / Example Usage
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":

    class SimEntity:
        """Mock data class for demonstration."""
        def __init__(self, name: str, mass: float, material: str) -> None:
            self.id_code = name
            self.mass = mass
            self.material = material
            self.color = "#3498db"
            self.visible = True
            self.velocity = 0.0
            self.particles = 100
            self.opacity = 1.0
            self.start_time = "00:00:00"
            self.last_updated = "2025-01-01"

        def get_momentum(self) -> float:
            return self.mass * self.velocity

        def set_momentum(self, value: float) -> None:
            try:
                m = float(self.mass)
                if m > 0:
                    self.velocity = value / m
            except (ValueError, TypeError):
                pass

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    props: List[PropertyDescriptor] = [
        {"attr": "id_code",       "label": "ID",              "widget_type": QLineEdit,      "value_type": "alphanumeric", "default": "ENT_001", "min_width": 80},
        {"attr": "notes",         "label": "Notes (Locked)",  "widget_type": QLineEdit,      "editable": False,            "default": "",        "min_width": 100},
        {"attr": "mass",          "label": "Mass",            "widget_type": QDoubleSpinBox,  "unit": "kg",  "value_range": (0.1, 1000.0), "decimals": 1, "step_size": 0.5, "default": 10.0, "min_width": 70},
        {"attr": "velocity",      "label": "Velocity",        "widget_type": QDoubleSpinBox,  "unit": "m/s", "decimals": 4, "step_size": 0.0001, "default": 0.0, "min_width": 70},
        {"attr": "particles",     "label": "Particles",       "widget_type": QSpinBox,        "unit": "cnt", "step_size": 10, "default": 100},
        {"attr": "opacity",       "label": "Opacity",         "widget_type": QSlider,         "decimals": 2, "value_range": (0.0, 1.0), "always_visible": True, "default": 1.0, "min_width": 150},
        {"attr": "limit_gauge",   "label": "Gauge (Locked)",  "widget_type": QSlider,         "decimals": 2, "always_visible": True, "editable": False, "value_range": (0.0, 1.0), "default": 0.0, "min_width": 150},
        {"attr": "material_type", "label": "Material",        "widget_type": QComboBox,       "items": ["Silicon", "Gallium", "Vacuum", "Gold"], "always_visible": True, "default": "Vacuum", "min_width": 90},
        {"attr": "is_visible",    "label": "Visible",         "widget_type": QCheckBox,       "always_visible": True, "default": True, "min_width": 60},
        {"attr": "color_primary", "label": "Color 1",         "widget_type": QPushButton,     "always_visible": True, "with_label": True,  "default": "#000000", "min_width": 80},
        {"attr": "color_accent",  "label": "Color 2",         "widget_type": QPushButton,     "always_visible": True, "with_label": False, "default": "#FFFFFF", "min_width": 50},
        {"attr": "start_time",    "label": "Time",            "widget_type": QTimeEdit,       "precision": "secs", "default": "00:00:00"},
        {"attr": "last_updated",  "label": "Date",            "widget_type": QDateEdit,       "default": "2025-01-01"},
        {"label": "Momentum",     "widget_type": QDoubleSpinBox, "unit": "kg⋅m/s",
         "getter": lambda obj: obj.get_momentum(),
         "setter": lambda obj, val: obj.set_momentum(val),
         "decimals": 2, "min_width": 100},
    ]

    data = [SimEntity(f"ENT_{i}", 10.0 + i * 5, "Si") for i in range(5)]

    win = QMainWindow()
    win.setWindowTitle("PADDOL — Unified Table Control Demo")

    tbl_standard = UnifiedTableControlWidget(
        properties_list=props, item_list=data, transposed=False,
        show_headers=True, alternating_rows=True,
    )
    tbl_transposed = UnifiedTableControlWidget(
        properties_list=props, item_list=data, transposed=True,
        show_headers=True, alternating_rows=True, alternate_color="lighter",
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