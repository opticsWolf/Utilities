# -*- coding: utf-8 -*-
"""
Main application window.

Owns the GUI, wires user actions to the worker thread, and is the single
source of truth for converting widget state ↔ ScanOptions ↔ persisted config.
"""

import json
from dataclasses import fields
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QByteArray
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStatusBar,
    QTextEdit, QVBoxLayout, QWidget,
)

from .config import (
    build_config_payload, load_scan_options, save_config,
)
from .constants import HAS_MYPY, HAS_RADON, HAS_RUFF
from .external_tools import MYPY_FLAG_MAP
from .formatters import to_json, to_text
from .models import LintResult, ScanOptions
from .option_defs import (
    ANTIPATTERN_OPTIONS, LEGACY_OPTIONS, MYPY_STRICT_FLAGS, TRACK_OPTIONS,
)
from .presets import CUSTOM, apply_preset, get_preset_names
from .styles import DARK
from .widgets import FileTreeWidget, MapHighlighter
from .worker import LintWorker, ScanWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyCodeRadar — Extended Code Map & Refactoring Radar")
        self.setMinimumSize(1200, 760)

        self._root_dir:    Optional[str] = None
        self._result_text: str = ""
        self._thread:      Optional[QThread]     = None
        self._worker:      Optional[ScanWorker]  = None
        self._active_opts: Optional[ScanOptions] = None

        # widget registries (attr → widget)
        self._check_widgets: dict = {}
        self._spin_widgets:  dict = {}
        self._text_widgets:  dict = {}
        self._mypy_strict_flags: list = []   # checkboxes disabled under --strict

        # preset state
        self._suppress_dirty: bool = False   # True while we set widgets programmatically

        # Load persisted config so the UI starts pre-filled.
        self._loaded_opts, self._loaded_preset, self._loaded_cfg = load_scan_options()

        self._setup_ui()
        self._restore_window_state(self._loaded_cfg)
        self.setStyleSheet(DARK)

    # ==========================================================================
    # UI construction
    # ==========================================================================

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 8)
        root_layout.setSpacing(10)

        # ── Header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        lbl_title = QLabel("PyCodeRadar"); lbl_title.setObjectName("title")
        lbl_sub   = QLabel("AST Code Map · Wrapper Detection · Legacy Analysis · Ruff / Radon / Mypy")
        lbl_sub.setObjectName("subtitle")
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_sub)
        header.addLayout(title_col); header.addStretch()
        header.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox(); self.fmt_combo.addItems(["Text", "JSON"])
        # restore saved format (case-insensitive — "JSON".capitalize() would mismatch)
        saved_fmt = (self._loaded_cfg.get("format") or "Text").strip().lower()
        for i in range(self.fmt_combo.count()):
            if self.fmt_combo.itemText(i).lower() == saved_fmt:
                self.fmt_combo.setCurrentIndex(i); break
        header.addWidget(self.fmt_combo)
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

        self.btn_fix = QPushButton("🔧  Fix"); self.btn_fix.setObjectName("fix")
        self.btn_fix.setFixedWidth(110); self.btn_fix.setEnabled(False)
        self.btn_fix.setToolTip(
            "Run Ruff in active mode against the selected files.\n"
            "Configure what to do (apply fixes, reformat, preview-only) under\n"
            "the LINT & FIX card in the options panel.\n\n"
            "Disabled when Ruff is not installed."
        )
        self.btn_fix.clicked.connect(self._start_lint)

        self.btn_scan = QPushButton("▶  Analyse"); self.btn_scan.setObjectName("primary")
        self.btn_scan.setFixedWidth(150); self.btn_scan.setEnabled(False)
        self.btn_scan.clicked.connect(self._start_scan)

        cl.addWidget(btn_open)
        cl.addWidget(self.lbl_path, 1)
        cl.addWidget(self.btn_fix)
        cl.addWidget(self.btn_scan)
        root_layout.addWidget(card)

        # ── Progress bar ──────────────────────────────────────────────────────
        pr = QHBoxLayout()
        self.progress_bar = QProgressBar(); self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.lbl_progress = QLabel(""); self.lbl_progress.setObjectName("stat")
        self.lbl_progress.setFixedWidth(300)
        pr.addWidget(self.progress_bar); pr.addWidget(self.lbl_progress)
        root_layout.addLayout(pr)

        # ── Splitter ──────────────────────────────────────────────────────────
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        root_layout.addWidget(self.splitter, 1)

        # ── LEFT: file tree + options ─────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 6, 0); ll.setSpacing(5)

        th = QHBoxLayout()
        lf = QLabel("FILES"); lf.setObjectName("panelhead")
        self.lbl_sel_count = QLabel("—"); self.lbl_sel_count.setObjectName("selfmt")
        self.lbl_sel_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        th.addWidget(lf); th.addStretch(); th.addWidget(self.lbl_sel_count)
        ll.addLayout(th)

        brow = QHBoxLayout(); brow.setSpacing(4)
        for txt, slot in [("Select All",   self._sel_all),
                          ("Deselect All", self._sel_none),
                          ("Invert",       self._sel_invert)]:
            b = QPushButton(txt); b.setObjectName("sel"); b.setFixedHeight(24)
            b.clicked.connect(slot); brow.addWidget(b)
        brow.addStretch()
        ll.addLayout(brow)

        hint = QLabel("Shift+click for range selection"); hint.setObjectName("selfmt")
        ll.addWidget(hint)

        self.file_tree = FileTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.selection_changed.connect(self._on_tree_changed)
        ll.addWidget(self.file_tree, 1)
        ll.addWidget(self._build_options_panel())

        self.splitter.addWidget(left)

        # ── RIGHT: output ─────────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(6, 0, 0, 0); rl.setSpacing(5)

        oh = QHBoxLayout()
        lo = QLabel("OUTPUT"); lo.setObjectName("panelhead")
        oh.addWidget(lo); oh.addStretch()

        def mini_stat(label, warn=False):
            col = QVBoxLayout(); col.setSpacing(0)
            v = QLabel("—"); v.setObjectName("statwarn" if warn else "statval")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_ = QLabel(label); l_.setObjectName("selfmt")
            l_.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(v); col.addWidget(l_)
            oh.addLayout(col); oh.addSpacing(14)
            return v

        self.stat_modules = mini_stat("modules")
        self.stat_classes = mini_stat("classes")
        self.stat_funcs   = mini_stat("funcs")
        self.stat_issues  = mini_stat("⚠ issues", warn=True)
        self.stat_errors  = mini_stat("errors")

        self.btn_save = QPushButton("⬇  Save…"); self.btn_save.setObjectName("save")
        self.btn_save.setFixedWidth(100); self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_file)
        oh.addWidget(self.btn_save)
        rl.addLayout(oh)

        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.output.setPlaceholderText(
            "Analysis results will appear here…\n\n"
            "1. Open a folder  →  .py files populate the left panel\n"
            "2. Tick / untick files;  Shift+click for range selection\n"
            "3. Pick a strictness preset or tweak options below the file tree\n"
            "4. Click 'Analyse'  →  report renders here\n"
            "5. Click 'Save…'  →  export as .txt or .json"
        )
        self.highlighter = MapHighlighter(self.output.document())
        rl.addWidget(self.output, 1)

        self.splitter.addWidget(right)
        self.splitter.setSizes([320, 880])

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.status.showMessage("Ready — open a folder to begin")

        # Apply persisted ScanOptions to the freshly built widgets, then set
        # the preset combo to the matching label without dirtying it.
        self._apply_options_to_widgets(self._loaded_opts)
        self._set_preset_combo(self._loaded_preset)

    # ==========================================================================
    # Options panel
    # ==========================================================================

    def _build_options_panel(self) -> QWidget:
        defaults = ScanOptions()
        scroll   = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(460)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 4, 0, 4); vbox.setSpacing(6)

        # ── PRESET card (NEW) ─────────────────────────────────────────────────
        vbox.addWidget(self._make_preset_card())

        # ── TRACK card ────────────────────────────────────────────────────────
        track_card = self._make_option_card("TRACK  —  additional metadata")
        for attr, label, tip in TRACK_OPTIONS:
            self._add_checkbox(track_card, attr, label, tip, getattr(defaults, attr))
        vbox.addWidget(track_card)

        # ── ANTI-PATTERNS card ────────────────────────────────────────────────
        anti_card = self._make_option_card("DETECT  —  anti-patterns")
        for attr, label, tip in ANTIPATTERN_OPTIONS:
            self._add_checkbox(anti_card, attr, label, tip, getattr(defaults, attr))
        self._add_threshold_grid(anti_card, defaults)
        self._add_quick_actions(anti_card, ANTIPATTERN_OPTIONS)
        vbox.addWidget(anti_card)

        # ── LEGACY card ───────────────────────────────────────────────────────
        legacy_card = self._make_option_card("DETECT  —  legacy code patterns")
        for attr, label, tip in LEGACY_OPTIONS:
            self._add_checkbox(legacy_card, attr, label, tip, getattr(defaults, attr))
        hint_lbl = QLabel(
            "Ruff's UP ruleset also covers many legacy patterns when enabled below."
        )
        hint_lbl.setObjectName("selfmt"); hint_lbl.setWordWrap(True)
        legacy_card.layout().addWidget(hint_lbl)
        self._add_quick_actions(legacy_card, LEGACY_OPTIONS)
        vbox.addWidget(legacy_card)

        # ── EXTERNAL TOOLS card ───────────────────────────────────────────────
        vbox.addWidget(self._make_ext_card())

        # ── LINT & FIX card  (active code modification) ───────────────────────
        vbox.addWidget(self._make_lint_card(defaults))

        # ── MYPY CONFIGURATION card ───────────────────────────────────────────
        vbox.addWidget(self._make_mypy_card(defaults))

        vbox.addStretch()
        scroll.setWidget(container)
        return scroll

    # ── Preset card ───────────────────────────────────────────────────────────

    def _make_preset_card(self) -> QFrame:
        card = QFrame(); card.setObjectName("presetcard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(6)

        hdr = QLabel("STRICTNESS PRESET"); hdr.setObjectName("presethead")
        lay.addWidget(hdr)

        row = QHBoxLayout(); row.setSpacing(8)
        self.preset_combo = QComboBox(); self.preset_combo.setObjectName("preset")
        self.preset_combo.addItems(get_preset_names())
        self.preset_combo.setToolTip(
            "Lenient   — only the bugs that almost always matter.\n"
            "Standard  — sensible defaults; what most projects want.\n"
            "Strict    — full anti-pattern + legacy sweep, mypy --strict.\n"
            "Pedantic  — everything on, tightest thresholds.\n"
            "Custom    — set automatically when you change any individual option."
        )
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        row.addWidget(QLabel("Preset:"))
        row.addWidget(self.preset_combo, 1)
        lay.addLayout(row)

        info = QLabel(
            "Switching presets overwrites all options below. Manual edits "
            "automatically switch this back to “Custom”."
        )
        info.setObjectName("selfmt"); info.setWordWrap(True)
        lay.addWidget(info)

        return card

    # ── Option-card builders ──────────────────────────────────────────────────

    def _make_option_card(self, title: str) -> QFrame:
        card = QFrame(); card.setObjectName("optcard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(3)
        hdr  = QLabel(title); hdr.setObjectName("sechead")
        lay.addWidget(hdr)
        return card

    def _add_checkbox(self, card: QFrame, attr: str, label: str,
                      tooltip: str, default: bool):
        cb = QCheckBox(label)
        cb.setChecked(default); cb.setToolTip(tooltip)
        cb.toggled.connect(self._mark_custom)
        card.layout().addWidget(cb)
        self._check_widgets[attr] = cb

    def _add_threshold_grid(self, card: QFrame, defaults: ScanOptions):
        grid = QGridLayout()
        grid.setContentsMargins(0, 6, 0, 0)
        grid.setHorizontalSpacing(8); grid.setVerticalSpacing(4)

        def add_row(row, attr, label, lo, hi, default):
            lbl = QLabel(label); lbl.setObjectName("threshold")
            spin = QSpinBox(); spin.setRange(lo, hi); spin.setValue(default)
            spin.setToolTip(f"Threshold for '{attr}'")
            spin.valueChanged.connect(self._mark_custom)
            grid.addWidget(lbl, row, 0); grid.addWidget(spin, row, 1)
            self._spin_widgets[attr] = spin

        add_row(0, "long_function_threshold", "Max function lines:", 10, 500, defaults.long_function_threshold)
        add_row(1, "max_args",                "Max arguments:",       1,  30, defaults.max_args)
        add_row(2, "god_class_threshold",     "Max methods/class:",   3, 100, defaults.god_class_threshold)
        card.layout().addLayout(grid)

    def _add_quick_actions(self, card: QFrame, group: list):
        row = QHBoxLayout(); row.setContentsMargins(0, 5, 0, 0)
        for label, slot in [("All",      lambda g=group: self._toggle_group(g, True)),
                            ("None",     lambda g=group: self._toggle_group(g, False)),
                            ("Defaults", lambda g=group: self._reset_group(g, ScanOptions()))]:
            b = QPushButton(label); b.setObjectName("ghost"); b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        card.layout().addLayout(row)

    def _make_ext_card(self) -> QFrame:
        card = QFrame(); card.setObjectName("extcard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(4)
        lay.addWidget(QLabel("EXTERNAL TOOLS  —  optional deep analysis", objectName="sechead"))

        def tool_row(attr, tool_name, description, available):
            cb = QCheckBox(f"{tool_name}: {description}")
            cb.setChecked(available); cb.setEnabled(available)
            cb.toggled.connect(self._mark_custom)
            if not available:
                cb.setText(f"{tool_name}: {description}  (not installed)")
            status = QLabel("✓ found" if available else "✗ not found")
            status.setObjectName("toolfound" if available else "toolmiss")
            row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb, 1); row.addWidget(status)
            lay.addLayout(row)
            self._check_widgets[attr] = cb

        tool_row("run_ruff_analysis",  "Ruff",  "deep smells, legacy syntax (UP rules)",  HAS_RUFF)
        tool_row("run_radon_analysis", "Radon", "Maintainability Index (MI score)",        HAS_RADON)
        tool_row("run_mypy_analysis",  "Mypy",  "static type checking",                    HAS_MYPY)

        note = QLabel("Files sorted worst-to-best MI score in output when Radon is enabled.")
        note.setObjectName("selfmt"); note.setWordWrap(True)
        lay.addWidget(note)
        return card

    def _make_lint_card(self, defaults: ScanOptions) -> QFrame:
        """Active linting card — Ruff in fix/format mode, with safety rails."""
        card = QFrame(); card.setObjectName("lintcard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(4)
        lay.addWidget(QLabel("LINT & FIX  —  actively modify code", objectName="linthead"))

        warn = QLabel(
            "⚠ These actions REWRITE files. Preview mode (default) shows a "
            "diff first — uncheck it to commit changes."
        )
        warn.setObjectName("lintwarn"); warn.setWordWrap(True)
        lay.addWidget(warn)

        def _add(attr: str, label: str, tip: str, default: bool):
            cb = QCheckBox(label)
            cb.setChecked(default); cb.setToolTip(tip)
            cb.toggled.connect(self._mark_custom)
            cb.toggled.connect(self._update_fix_button_state)
            lay.addWidget(cb)
            self._check_widgets[attr] = cb

        _add("lint_apply_fixes",  "Apply Ruff auto-fixes  (ruff check --fix)",
             "Run `ruff check --fix` on the selected files.\n"
             "Removes unused imports, sorts imports, drops unreachable code, etc.",
             defaults.lint_apply_fixes)

        _add("lint_unsafe_fixes", "Include unsafe fixes  (--unsafe-fixes)",
             "Also apply rules Ruff classifies as 'unsafe'.\n"
             "These can change semantics in rare cases — review the diff first.",
             defaults.lint_unsafe_fixes)

        _add("lint_format_code",  "Reformat code  (ruff format)",
             "Run `ruff format` to reformat code (Black-compatible style).\n"
             "Combines well with --fix; both run in one click.",
             defaults.lint_format_code)

        sep = QFrame(); sep.setObjectName("divider"); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        _add("lint_preview_only", "Preview only — show diff, do not write",
             "Use ruff's `--diff` mode to display proposed changes without\n"
             "touching any files. Highly recommended before the first commit.",
             defaults.lint_preview_only)

        if not HAS_RUFF:
            note = QLabel("Ruff is not installed — install it to enable linting.")
            note.setObjectName("toolmiss"); note.setWordWrap(True)
            lay.addWidget(note)

        return card

    # ── Fix-button enable/disable logic ───────────────────────────────────────

    def _update_fix_button_state(self, *_):
        """
        The Fix button is only meaningful when Ruff exists, a folder is loaded,
        files are selected, and at least one lint action is checked.
        """
        if not hasattr(self, "btn_fix"):
            return
        any_action = (
            self._check_widgets.get("lint_apply_fixes")
            and self._check_widgets["lint_apply_fixes"].isChecked()
        ) or (
            self._check_widgets.get("lint_format_code")
            and self._check_widgets["lint_format_code"].isChecked()
        )
        files_ready = (
            self._root_dir is not None
            and len(self.file_tree.checked_files()) > 0
        )
        self.btn_fix.setEnabled(bool(HAS_RUFF and any_action and files_ready))

    def _make_mypy_card(self, defaults: ScanOptions) -> QFrame:
        card = QFrame(); card.setObjectName("mypycard")
        lay  = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10); lay.setSpacing(4)

        hdr = QLabel("MYPY  —  strictness & filters"); hdr.setObjectName("mypyhead")
        lay.addWidget(hdr)

        # ── Strict-mode master toggle ─────────────────────────────────────────
        cb_strict = QCheckBox("Strict mode  (--strict  · implies all flags below)")
        cb_strict.setChecked(defaults.mypy_strict)
        cb_strict.setToolTip(
            "Passes --strict to mypy, which enables the full set of strictness checks.\n"
            "Individual flag checkboxes are disabled while this is active — mypy will\n"
            "apply all of them regardless."
        )
        cb_strict.toggled.connect(self._mark_custom)
        self._check_widgets["mypy_strict"] = cb_strict
        lay.addWidget(cb_strict)

        sep = QFrame(); sep.setObjectName("divider"); sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        # ── Individual strictness flags ───────────────────────────────────────
        self._mypy_strict_flags = []
        for attr, flag_name, tip in MYPY_STRICT_FLAGS:
            cb = QCheckBox(flag_name)
            cb.setChecked(getattr(defaults, attr))
            cb.setToolTip(tip)
            cb.setEnabled(not defaults.mypy_strict)
            cb.toggled.connect(self._mark_custom)
            lay.addWidget(cb)
            self._check_widgets[attr] = cb
            self._mypy_strict_flags.append(cb)

        # wire master toggle ↔ individual flags enabled state
        cb_strict.toggled.connect(self._on_strict_toggled)

        sep2 = QFrame(); sep2.setObjectName("divider"); sep2.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep2)

        # ── Ignore options ────────────────────────────────────────────────────
        cb_miss = QCheckBox("--ignore-missing-imports")
        cb_miss.setChecked(defaults.mypy_ignore_missing_imports)
        cb_miss.setToolTip(
            "Suppress errors about missing stub files or missing source for imports.\n"
            "Useful for third-party packages that don't ship type information."
        )
        cb_miss.toggled.connect(self._mark_custom)
        self._check_widgets["mypy_ignore_missing_imports"] = cb_miss
        lay.addWidget(cb_miss)

        # Disable error codes row
        codes_row = QHBoxLayout(); codes_row.setSpacing(6)
        codes_lbl = QLabel("Disable codes:"); codes_lbl.setObjectName("fieldlbl")
        codes_edit = QLineEdit()
        codes_edit.setPlaceholderText("e.g.  import-untyped, no-untyped-def")
        codes_edit.setText(defaults.mypy_disable_error_codes)
        codes_edit.setToolTip(
            "Comma-separated list of mypy error codes to silence with --disable-error-code.\n"
            "Example:  import-untyped, no-untyped-def, attr-defined\n\n"
            "Full list:  mypy --show-error-codes  or  https://mypy.readthedocs.io/en/stable/error_codes.html"
        )
        codes_edit.textChanged.connect(self._mark_custom)
        codes_row.addWidget(codes_lbl); codes_row.addWidget(codes_edit, 1)
        lay.addLayout(codes_row)
        self._text_widgets["mypy_disable_error_codes"] = codes_edit

        sep3 = QFrame(); sep3.setObjectName("divider"); sep3.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep3)

        # ── Severity filter ───────────────────────────────────────────────────
        sev_row = QHBoxLayout(); sev_row.setSpacing(0)
        sev_lbl = QLabel("Show:"); sev_lbl.setObjectName("fieldlbl")
        sev_row.addWidget(sev_lbl)
        for attr, label, tip in [
            ("mypy_show_errors",   "Errors",   "Show mypy ERROR messages."),
            ("mypy_show_warnings", "Warnings", "Show mypy WARNING messages."),
            ("mypy_show_notes",    "Notes",    "Show mypy NOTE messages (informational, often verbose)."),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(getattr(defaults, attr))
            cb.setToolTip(tip)
            cb.toggled.connect(self._mark_custom)
            sev_row.addWidget(cb); sev_row.addSpacing(10)
            self._check_widgets[attr] = cb
        sev_row.addStretch()
        lay.addLayout(sev_row)

        if not HAS_MYPY:
            note = QLabel("Mypy is not installed — these settings will have no effect.")
            note.setObjectName("toolmiss"); note.setWordWrap(True)
            lay.addWidget(note)

        return card

    # ── Strict-mode wiring ────────────────────────────────────────────────────

    def _on_strict_toggled(self, checked: bool):
        for f in self._mypy_strict_flags:
            f.setEnabled(not checked)

    # ==========================================================================
    # Preset handling
    # ==========================================================================

    def _on_preset_changed(self, name: str):
        """User picked a preset from the dropdown — apply it to all widgets."""
        if self._suppress_dirty:
            return
        if name == CUSTOM:
            return   # 'Custom' is a state, not an action
        opts = apply_preset(name)
        self._apply_options_to_widgets(opts)
        self.status.showMessage(f"Applied preset: {name}")

    def _set_preset_combo(self, name: str):
        """Programmatically set the preset combo without firing dirty logic."""
        idx = self.preset_combo.findText(name)
        if idx < 0:
            idx = self.preset_combo.findText(CUSTOM)
        self._suppress_dirty = True
        try:
            self.preset_combo.setCurrentIndex(max(0, idx))
        finally:
            self._suppress_dirty = False

    def _mark_custom(self, *_args):
        """
        Any user-driven widget change → flip the preset combo to 'Custom'.

        Programmatic changes (preset application, config restore) suppress
        this via _suppress_dirty so the combo retains the active preset name.
        """
        if self._suppress_dirty:
            return
        if self.preset_combo.currentText() != CUSTOM:
            self._set_preset_combo(CUSTOM)

    # ==========================================================================
    # Widget ↔ ScanOptions plumbing
    # ==========================================================================

    def _apply_options_to_widgets(self, opts: ScanOptions):
        """Push values from a ScanOptions into all registered widgets."""
        self._suppress_dirty = True
        try:
            for attr, cb in self._check_widgets.items():
                if hasattr(opts, attr):
                    cb.setChecked(bool(getattr(opts, attr)))
            for attr, spin in self._spin_widgets.items():
                if hasattr(opts, attr):
                    spin.setValue(int(getattr(opts, attr)))
            for attr, edit in self._text_widgets.items():
                if hasattr(opts, attr):
                    edit.setText(str(getattr(opts, attr)))
            # mypy strict flags enabled state must follow the new value
            self._on_strict_toggled(opts.mypy_strict)
        finally:
            self._suppress_dirty = False

    def _current_options(self) -> ScanOptions:
        """Read all widgets back into a fresh ScanOptions instance."""
        opts = ScanOptions()
        for attr, cb in self._check_widgets.items():
            if hasattr(opts, attr): setattr(opts, attr, cb.isChecked())
        for attr, spin in self._spin_widgets.items():
            if hasattr(opts, attr): setattr(opts, attr, spin.value())
        for attr, edit in self._text_widgets.items():
            if hasattr(opts, attr): setattr(opts, attr, edit.text().strip())
        return opts

    def _toggle_group(self, group: list, value: bool):
        for attr, _, _ in group:
            if attr in self._check_widgets:
                self._check_widgets[attr].setChecked(value)

    def _reset_group(self, group: list, defaults: ScanOptions):
        for attr, _, _ in group:
            if attr in self._check_widgets:
                self._check_widgets[attr].setChecked(getattr(defaults, attr))

    # ==========================================================================
    # File tree callbacks
    # ==========================================================================

    def _sel_all(self):    self.file_tree.set_all(Qt.CheckState.Checked)
    def _sel_none(self):   self.file_tree.set_all(Qt.CheckState.Unchecked)
    def _sel_invert(self): self.file_tree.invert()

    def _on_tree_changed(self, checked: int, total: int):
        self.lbl_sel_count.setText(f"{checked} / {total} selected")
        self.btn_scan.setEnabled(checked > 0 and self._root_dir is not None)
        self._update_fix_button_state()

    # ==========================================================================
    # Folder open
    # ==========================================================================

    def _open_folder(self, *, initial: Optional[str] = None):
        start = initial or self._root_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Select Python Project Folder", start)
        if not folder: return
        self._load_folder(folder)

    def _load_folder(self, folder: str):
        self._root_dir = folder
        self.lbl_path.setText(folder if len(folder) <= 72 else "…" + folder[-69:])
        self.output.clear(); self._result_text = ""
        self.btn_save.setEnabled(False)
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs,
                  self.stat_issues, self.stat_errors):
            s.setText("—")
        self.file_tree.populate(folder)
        self.status.showMessage(f"Loaded: {folder}")

    # ==========================================================================
    # Scan
    # ==========================================================================

    def _start_scan(self):
        selected = self.file_tree.checked_files()
        if not selected:
            self.status.showMessage("No files selected."); return

        self.btn_scan.setEnabled(False); self.btn_save.setEnabled(False)
        self.output.clear()
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs,
                  self.stat_issues, self.stat_errors):
            s.setText("…")

        self._active_opts = self._current_options()
        self._thread = QThread()
        self._worker = ScanWorker(selected, self._active_opts)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

        ext_note = ""
        if self._active_opts.run_ruff_analysis  and HAS_RUFF:  ext_note += " + Ruff"
        if self._active_opts.run_radon_analysis and HAS_RADON: ext_note += " + Radon"
        if self._active_opts.run_mypy_analysis  and HAS_MYPY:
            if self._active_opts.mypy_strict:
                ext_note += " + Mypy (--strict)"
            else:
                flags_on = sum(
                    1 for attr, _ in MYPY_FLAG_MAP if getattr(self._active_opts, attr)
                )
                ext_note += f" + Mypy ({flags_on} flag{'s' if flags_on != 1 else ''})"
        self.status.showMessage(f"Scanning {len(selected)} file(s){ext_note}…")

    def _on_progress(self, current: int, total: int, name: str):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)
        self.lbl_progress.setText(f"{current}/{total}  {name}")

    def _on_finished(self, maps: list, stats: dict):
        opts = self._active_opts or ScanOptions()
        fmt  = self.fmt_combo.currentText().lower()
        if fmt == "json":
            self._result_text = json.dumps([to_json(m, opts) for m in maps], indent=2)
        else:
            self._result_text = "\n\n".join(to_text(m, opts) for m in maps)

        self.output.setPlainText(self._result_text)
        self.stat_modules.setText(str(stats["modules"]))
        self.stat_classes.setText(str(stats["classes"]))
        self.stat_funcs.setText(str(stats["functions"]))
        self.stat_issues.setText(str(stats["issues"]))
        self.stat_errors.setText(str(stats["errors"]))

        checked = len(self.file_tree.checked_files())
        self.btn_scan.setEnabled(checked > 0)
        self.btn_save.setEnabled(bool(self._result_text))
        self._update_fix_button_state()
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.lbl_progress.setText("Done")
        self.status.showMessage(
            f"Done — {stats['modules']} modules, {stats['classes']} classes, "
            f"{stats['functions']} functions"
            + (f", ⚠ {stats['issues']} issue(s)" if stats["issues"] else "")
        )

    def _on_error(self, msg: str):
        self.output.setPlainText(f"[Error]\n{msg}")
        self.btn_scan.setEnabled(len(self.file_tree.checked_files()) > 0)
        self._update_fix_button_state()
        self.status.showMessage(f"Error: {msg}")

    def _save_file(self):
        fmt = self.fmt_combo.currentText().lower()
        ext = "json" if fmt == "json" else "txt"
        default = str(Path(self._root_dir or ".") / f"radar_report.{ext}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Report", default,
            f"{'JSON' if fmt == 'json' else 'Text'} files (*.{ext});;All files (*)",
        )
        if path:
            Path(path).write_text(self._result_text, encoding="utf-8")
            self.status.showMessage(f"Saved → {path}")

    # ==========================================================================
    # Active linting / fixing
    # ==========================================================================

    def _start_lint(self):
        """Confirm (if writing) and kick off the LintWorker."""
        if not HAS_RUFF:
            QMessageBox.warning(
                self, "Ruff not installed",
                "Ruff is not installed. Install it (e.g. `pip install ruff`)\n"
                "and restart PyCodeRadar to enable active linting.",
            )
            return

        selected = self.file_tree.checked_files()
        if not selected:
            self.status.showMessage("No files selected."); return

        opts = self._current_options()
        if not opts.lint_apply_fixes and not opts.lint_format_code:
            QMessageBox.information(
                self, "Nothing to do",
                "Select at least one lint action (apply fixes or reformat code) "
                "in the LINT & FIX card.",
            )
            return

        # Confirmation when actually writing files.
        if not opts.lint_preview_only:
            actions = []
            if opts.lint_apply_fixes:
                actions.append(
                    "apply Ruff auto-fixes" +
                    (" (including unsafe)" if opts.lint_unsafe_fixes else "")
                )
            if opts.lint_format_code:
                actions.append("reformat code")

            answer = QMessageBox.question(
                self, "Confirm lint & fix",
                f"This will {' and '.join(actions)} on "
                f"{len(selected)} file(s).\n\n"
                f"Files will be REWRITTEN in place. This cannot be undone "
                f"unless you have version control.\n\n"
                f"Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.status.showMessage("Lint cancelled.")
                return

        # Disable controls while the worker runs.
        self.btn_fix.setEnabled(False)
        self.btn_scan.setEnabled(False); self.btn_save.setEnabled(False)
        self.output.clear()
        self.progress_bar.setValue(0); self.lbl_progress.setText("")
        for s in (self.stat_modules, self.stat_classes, self.stat_funcs,
                  self.stat_issues, self.stat_errors):
            s.setText("…")

        self._active_opts = opts
        self._thread = QThread()
        self._worker = LintWorker(selected, opts)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_lint_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

        verb = "Previewing" if opts.lint_preview_only else "Fixing"
        self.status.showMessage(f"{verb} {len(selected)} file(s) with Ruff…")

    def _on_lint_finished(self, result: LintResult):
        """Render the LintResult into the output pane."""
        opts = self._active_opts or ScanOptions()

        header_lines = []
        kind = "PREVIEW" if not result.applied else "APPLIED"
        header_lines.append(f"🔧 Ruff {kind} — {result.summary}")
        header_lines.append(f"   Files processed: {result.files_processed}")
        if result.applied:
            header_lines.append(f"   Files rewritten: {result.files_changed}")
            header_lines.append(f"   Fixes applied:   {result.fixes_applied}")
            if opts.lint_format_code:
                header_lines.append(f"   Files reformatted: {result.format_changed}")
        else:
            if result.fixes_applied:
                header_lines.append(f"   Would fix:       {result.fixes_applied} issue(s)")
            if result.format_changed:
                header_lines.append(f"   Would reformat:  {result.format_changed} file(s)")
        if result.errors:
            header_lines.append("")
            header_lines.append("Errors:")
            for e in result.errors:
                header_lines.append(f"   • {e}")

        body = "\n".join(header_lines)
        if result.diff:
            body += "\n\n" + ("─" * 60) + "\n" + result.diff
        elif not result.applied and not result.errors and not result.fixes_applied \
                and not result.format_changed:
            body += "\n\nNo changes would be made — code is already clean."

        self._result_text = body
        self.output.setPlainText(body)

        # Re-enable controls. Selection state may have changed during the run.
        checked = len(self.file_tree.checked_files())
        self.btn_scan.setEnabled(checked > 0)
        self.btn_save.setEnabled(bool(self._result_text))
        self._update_fix_button_state()
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.lbl_progress.setText("Done")

        # Status bar summary, plus a hint to re-analyse after fixes.
        msg = f"Lint done — {result.summary}"
        if result.applied and result.files_changed:
            msg += " — re-run Analyse to refresh the report."
        self.status.showMessage(msg)

    # ==========================================================================
    # Config persistence
    # ==========================================================================

    def _restore_window_state(self, cfg: dict):
        """Re-apply saved geometry, splitter sizes, last folder."""
        window = cfg.get("window") or {}
        geom_b64 = window.get("geometry")
        if isinstance(geom_b64, str) and geom_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geom_b64.encode("ascii")))
            except Exception as e:
                print(f"[PyCodeRadar] Could not restore window geometry: {e}")

        splitter_sizes = window.get("splitter")
        if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2:
            try:
                self.splitter.setSizes([int(x) for x in splitter_sizes])
            except (TypeError, ValueError):
                pass

        last = cfg.get("last_folder")
        if isinstance(last, str) and last and Path(last).is_dir():
            # Defer to keep startup fast on huge trees? populate() is sync; safe enough.
            self._load_folder(last)

    def _persist(self):
        """Write current widget state + window geometry to disk."""
        opts   = self._current_options()
        preset = self.preset_combo.currentText() if hasattr(self, "preset_combo") else None
        fmt    = self.fmt_combo.currentText() if hasattr(self, "fmt_combo") else None

        try:
            geom_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
        except Exception:
            geom_b64 = None

        try:
            sizes = self.splitter.sizes()
        except Exception:
            sizes = None

        payload = build_config_payload(
            opts,
            preset=preset,
            fmt=fmt,
            last_folder=self._root_dir,
            geometry_b64=geom_b64,
            splitter_sizes=sizes,
        )
        save_config(payload)

    def closeEvent(self, event):
        """Persist on every close — including window-manager quits."""
        try:
            self._persist()
        except Exception as e:
            print(f"[PyCodeRadar] Could not persist config on close: {e}")
        super().closeEvent(event)
