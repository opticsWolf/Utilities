# -*- coding: utf-8 -*-
"""Qt stylesheet — kept in its own module so MainWindow doesn't drown in CSS."""

DARK = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
    font-size: 13px;
}
QLabel#title    { font-size: 20px; font-weight: 700; color: #f8fafc; letter-spacing: 0.5px; }
QLabel#subtitle { color: #64748b; font-size: 12px; }

/* ── Buttons ── */
QPushButton {
    background-color: #1e293b; color: #e2e8f0;
    border: 1px solid #334155; border-radius: 6px;
    padding: 6px 14px; font-size: 12px;
}
QPushButton:hover    { background-color: #273549; border-color: #4f7ec0; }
QPushButton:pressed  { background-color: #172033; }
QPushButton:disabled { color: #475569; border-color: #1e293b; }

QPushButton#primary {
    background-color: #1d4ed8; border-color: #2563eb;
    color: #fff; font-weight: 600;
}
QPushButton#primary:hover    { background-color: #2563eb; }
QPushButton#primary:pressed  { background-color: #1e40af; }
QPushButton#primary:disabled { background-color: #1e3a5f; color: #6b7280; }

QPushButton#save {
    background-color: #065f46; border-color: #059669;
    color: #ecfdf5; font-weight: 600;
}
QPushButton#save:hover    { background-color: #047857; }
QPushButton#save:disabled { background-color: #1a2e28; color: #6b7280; }

QPushButton#fix {
    background-color: #7c2d12; border-color: #c2410c;
    color: #fef3c7; font-weight: 600;
}
QPushButton#fix:hover    { background-color: #9a3412; }
QPushButton#fix:pressed  { background-color: #6b1d0a; }
QPushButton#fix:disabled { background-color: #2a1810; color: #6b7280; border-color: #3a1f15; }

QPushButton#sel {
    padding: 3px 10px; font-size: 11px;
    background-color: #141a25; border-color: #1e293b;
}
QPushButton#sel:hover { background-color: #1e293b; border-color: #334155; }

QPushButton#ghost {
    background-color: transparent; border: 1px solid #334155;
    color: #94a3b8; padding: 3px 8px; font-size: 11px;
}
QPushButton#ghost:hover { color: #e2e8f0; border-color: #4f7ec0; }

/* ── Text / Output ── */
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
    font-size: 12px; alternate-background-color: #0d1320;
    show-decoration-selected: 0; outline: none;
}
QTreeWidget::item       { padding: 3px 4px; border-radius: 3px; }
QTreeWidget::item:hover { background-color: #182030; }
QTreeWidget::branch     { background: transparent; }

/* ── Progress ── */
QProgressBar {
    background-color: #1e293b; border: none;
    border-radius: 4px; height: 6px; color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #7c3aed);
    border-radius: 4px;
}

/* ── Combo / checkbox / spinbox ── */
QComboBox {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 5px; padding: 5px 10px; color: #e2e8f0; min-width: 80px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #1e293b; border: 1px solid #334155;
    selection-background-color: #1d4ed8;
}

QComboBox#preset {
    background-color: #1a2540; border: 1px solid #2563eb;
    color: #f8fafc; font-weight: 600; min-width: 110px;
}
QComboBox#preset:hover { border-color: #3b82f6; }

QCheckBox { spacing: 6px; color: #cbd5e1; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #475569; border-radius: 3px;
    background-color: #1e293b;
}
QCheckBox::indicator:checked { background-color: #2563eb; border-color: #2563eb; }
QCheckBox:disabled { color: #475569; }

QSpinBox {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 4px; padding: 2px 6px;
    color: #e2e8f0; font-size: 12px; min-width: 52px;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #273549; border: none; width: 14px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background-color: #2563eb; }

QLineEdit {
    background-color: #1e293b; border: 1px solid #334155;
    border-radius: 4px; padding: 3px 7px;
    color: #e2e8f0; font-size: 12px;
    selection-background-color: #1d4ed8;
}
QLineEdit:focus    { border-color: #2563eb; }
QLineEdit:disabled { color: #475569; background-color: #141a25; }

/* ── Structural frames ── */
QFrame#card     { background-color: #141a25; border: 1px solid #1e293b; border-radius: 8px; }
QFrame#optcard  { background-color: #111722; border: 1px solid #1e293b; border-radius: 8px; }
QFrame#extcard  { background-color: #0e1a14; border: 1px solid #1a3025; border-radius: 8px; }
QFrame#mypycard { background-color: #0e1520; border: 1px solid #1a2a40; border-radius: 8px; }
QFrame#presetcard { background-color: #161f33; border: 1px solid #2c3e60; border-radius: 8px; }
QFrame#lintcard { background-color: #1c1208; border: 1px solid #3a2410; border-radius: 8px; }
QFrame#divider  { background-color: #1e293b; max-height: 1px; }

/* ── Scroll area ── */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ── Labels ── */
QLabel#stat       { color: #94a3b8; font-size: 12px; }
QLabel#statval    { color: #38bdf8; font-size: 14px; font-weight: 700; }
QLabel#statwarn   { color: #fb923c; font-size: 14px; font-weight: 700; }
QLabel#selfmt     { color: #64748b; font-size: 11px; }
QLabel#panelhead  { color: #475569; font-size: 10px; font-weight: 700; letter-spacing: 1.2px; }
QLabel#sechead    { color: #94a3b8; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
QLabel#mypyhead   { color: #7dd3fc; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
QLabel#presethead { color: #93c5fd; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
QLabel#linthead   { color: #fbbf24; font-size: 10px; font-weight: 700; letter-spacing: 0.8px; }
QLabel#lintwarn   { color: #fbbf24; font-size: 11px; }
QLabel#threshold  { color: #64748b; font-size: 11px; }
QLabel#fieldlbl   { color: #64748b; font-size: 11px; min-width: 110px; }
QLabel#toolfound  { color: #34d399; font-size: 11px; }
QLabel#toolmiss   { color: #f87171; font-size: 11px; }

QStatusBar {
    background-color: #0a0d14; color: #475569;
    border-top: 1px solid #1e293b; font-size: 11px;
}
QSplitter::handle:horizontal { background-color: #1e293b; width: 3px; }
"""
