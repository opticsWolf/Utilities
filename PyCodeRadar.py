# -*- coding: utf-8 -*-
"""
Extended PyCodeMap & Refactoring Radar
Integrates AST parsing with Ruff, Radon, and Mypy for deep code strategy.
"""

# ==========================================
# 1. MODULES & GLOBALS
# ==========================================
import ast
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QTextEdit, QProgressBar,
    QFrame, QSplitter, QStatusBar, QComboBox, QCheckBox, QSpinBox,
    QSizePolicy, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
    QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QPalette

# Check for external tools
HAS_RUFF = shutil.which("ruff") is not None
HAS_RADON = shutil.which("radon") is not None
HAS_MYPY = shutil.which("mypy") is not None

# stdlib detection
try:
    _STDLIB_MODULES = set(sys.stdlib_module_names)
except AttributeError:
    _STDLIB_MODULES = set()

EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", "env", ".git", "node_modules",
                "dist", "build", ".mypy_cache", ".pytest_cache"}


# ==========================================
# 2. DATA CLASSES (MODELS)
# ==========================================

@dataclass
class ImportInfo:
    raw: str
    local_name: str
    lineno: int
    from_module: Optional[str] = None
    is_wildcard: bool = False

@dataclass
class FunctionInfo:
    name: str
    lineno: int
    args: list
    decorators: list
    docstring: Optional[str]
    calls: list = field(default_factory=list)
    is_async: bool = False
    line_end: Optional[int] = None
    num_lines: int = 0
    complexity: int = 1
    annotations: dict = field(default_factory=dict)
    return_type: Optional[str] = None
    exceptions_raised: list = field(default_factory=list)
    num_args: int = 0

@dataclass
class ClassInfo:
    name: str
    lineno: int
    bases: list
    docstring: Optional[str]
    methods: list = field(default_factory=list)
    line_end: Optional[int] = None
    num_lines: int = 0

@dataclass
class AntiPattern:
    category: str
    message: str
    lineno: int

@dataclass
class RuffIssue:
    code: str
    message: str
    row: int

@dataclass
class MypyIssue:
    line: int
    severity: str
    message: str

@dataclass
class ModuleMap:
    path: str
    docstring: Optional[str]
    imports: list
    functions: list
    classes: list
    globals: list
    anti_patterns: list = field(default_factory=list)
    todos: list = field(default_factory=list)
    import_categories: dict = field(default_factory=dict)
    # Extended External Data
    ruff_issues: list = field(default_factory=list)
    mypy_issues: list = field(default_factory=list)
    mi_score: Optional[float] = None
    mi_rank: Optional[str] = None

@dataclass
class ScanOptions:
    # Tracking
    include_calls: bool = True
    track_line_counts: bool = True
    track_complexity: bool = True
    track_return_types: bool = True
    track_annotations: bool = False
    track_exceptions: bool = False
    track_import_categories: bool = False
    track_todos: bool = True
    # Anti-patterns
    detect_wildcard: bool = True
    detect_duplicate_imports: bool = True
    detect_unused_imports: bool = False
    detect_mutable_defaults: bool = True
    detect_bare_except: bool = True
    detect_long_functions: bool = True
    detect_too_many_args: bool = True
    detect_god_classes: bool = True
    detect_print: bool = False
    detect_exec_eval: bool = True
    # Extended Tools
    run_ruff_analysis: bool = HAS_RUFF
    run_radon_analysis: bool = HAS_RADON
    run_mypy_analysis: bool = HAS_MYPY
    # Thresholds
    long_function_threshold: int = 50
    max_args: int = 5
    god_class_threshold: int = 15


# ==========================================
# 3. BACKEND: HELPER METHODS
# ==========================================

def _categorize_imports(imports: list) -> dict:
    stdlib, third, local = [], [], []
    for imp in imports:
        if imp.from_module and imp.from_module.startswith('.'):
            local.append(imp.raw)
            continue
        top = (imp.from_module or imp.local_name or imp.raw).split('.')[0].split(' ')[0]
        if not top:
            local.append(imp.raw)
        elif top in _STDLIB_MODULES:
            stdlib.append(imp.raw)
        else:
            third.append(imp.raw)
    return {"stdlib": stdlib, "third_party": third, "local": local}

_COMPLEXITY_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Assert, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

def _cyclomatic_complexity(node: ast.AST) -> int:
    score = 1
    for sub in ast.walk(node):
        if isinstance(sub, _COMPLEXITY_NODES): score += 1
        elif isinstance(sub, ast.BoolOp): score += max(0, len(sub.values) - 1)
        elif isinstance(sub, ast.Try): score += len(sub.handlers)
        elif hasattr(ast, "Match") and isinstance(sub, ast.Match): score += len(sub.cases)
        if isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in sub.generators: score += len(gen.ifs)
    return score

def _is_mutable_default(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.List): return "list"
    if isinstance(node, ast.Dict): return "dict"
    if isinstance(node, ast.Set): return "set"
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in {"list", "dict", "set"} and not node.args and not node.keywords:
            return name + "()"
    return None


# ==========================================
# 4. BACKEND: AST PARSER
# ==========================================

class CodeMapVisitor(ast.NodeVisitor):
    def __init__(self, opts: ScanOptions):
        self.opts = opts
        self.imports = []
        self.functions = []
        self.classes = []
        self.globals = []
        self.anti_patterns = []
        self._current_class = None
        self._func_depth = 0

    def visit_Import(self, node):
        for alias in node.names:
            local = alias.asname or alias.name.split('.')[0]
            raw = f"{alias.name} as {alias.asname}" if alias.asname else alias.name
            self.imports.append(ImportInfo(raw=raw, local_name=local, lineno=node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        src = f"{'.' * (node.level or 0)}{module}"
        for alias in node.names:
            if alias.name == "*":
                self.imports.append(ImportInfo(raw=f"from {src} import *", local_name="*", lineno=node.lineno, from_module=src, is_wildcard=True))
                if self.opts.detect_wildcard:
                    self.anti_patterns.append(AntiPattern("wildcard-import", f"wildcard import: from {src} import *", node.lineno))
            else:
                local = alias.asname or alias.name
                name_part = f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                self.imports.append(ImportInfo(raw=f"from {src} import {name_part}", local_name=local, lineno=node.lineno, from_module=src))
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        line_end = getattr(node, "end_lineno", None)
        cls = ClassInfo(
            name=node.name, lineno=node.lineno,
            bases=[ast.unparse(b) for b in node.bases],
            docstring=ast.get_docstring(node),
            line_end=line_end,
            num_lines=(line_end - node.lineno + 1) if line_end else 0,
        )
        prev = self._current_class
        self._current_class = cls
        self.generic_visit(node)
        self._current_class = prev
        self.classes.append(cls)

        if self.opts.detect_god_classes and len(cls.methods) >= self.opts.god_class_threshold:
            self.anti_patterns.append(AntiPattern("god-class", f"god class '{cls.name}' with {len(cls.methods)} methods (>= {self.opts.god_class_threshold})", cls.lineno))

    def _visit_func(self, node):
        line_end = getattr(node, "end_lineno", None)
        fn = FunctionInfo(
            name=node.name, lineno=node.lineno,
            args=[a.arg for a in node.args.args],
            decorators=[ast.unparse(d) for d in node.decorator_list],
            docstring=ast.get_docstring(node),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            line_end=line_end, num_lines=(line_end - node.lineno + 1) if line_end else 0,
            complexity=_cyclomatic_complexity(node) if self.opts.track_complexity else 1,
            num_args=len(node.args.args),
        )
        
        if self.opts.track_return_types and node.returns:
            try: fn.return_type = ast.unparse(node.returns)
            except Exception: pass

        if self._current_class: self._current_class.methods.append(fn)
        else: self.functions.append(fn)

        self._check_func_antipatterns(node, fn)

        self._func_depth += 1
        try: self.generic_visit(node)
        finally: self._func_depth -= 1

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def _check_func_antipatterns(self, node, fn: FunctionInfo):
        if self.opts.detect_mutable_defaults:
            defaults = node.args.defaults or []
            pos_args = node.args.args
            offset = len(pos_args) - len(defaults)
            for i, d in enumerate(defaults):
                if kind := _is_mutable_default(d):
                    arg_name = pos_args[offset + i].arg if (offset + i) < len(pos_args) else "?"
                    self.anti_patterns.append(AntiPattern("mutable-default", f"mutable default ({kind}) for arg '{arg_name}'", node.lineno))
        if self.opts.detect_too_many_args and fn.num_args > self.opts.max_args:
            self.anti_patterns.append(AntiPattern("too-many-args", f"'{fn.name}' has {fn.num_args} args (> {self.opts.max_args})", node.lineno))
        if self.opts.detect_long_functions and fn.num_lines > self.opts.long_function_threshold:
            self.anti_patterns.append(AntiPattern("long-function", f"'{fn.name}' is {fn.num_lines} lines (> {self.opts.long_function_threshold})", node.lineno))

    def visit_ExceptHandler(self, node):
        if self.opts.detect_bare_except and node.type is None:
            self.anti_patterns.append(AntiPattern("bare-except", "bare `except:` clause", node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in {"exec", "eval"} and self.opts.detect_exec_eval:
                self.anti_patterns.append(AntiPattern("exec-eval", f"use of `{node.func.id}()`", node.lineno))
            elif node.func.id == "print" and self.opts.detect_print:
                self.anti_patterns.append(AntiPattern("print-statement", "`print()` call", node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node):
        if self._current_class is None and self._func_depth == 0:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.globals.append(target.id)
        self.generic_visit(node)

def build_module_map(filepath: str, opts: ScanOptions) -> ModuleMap:
    source = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(source)
    visitor = CodeMapVisitor(opts)
    visitor.visit(tree)

    todos = []
    if opts.track_todos:
        for i, line in enumerate(source.splitlines(), 1):
            if m := re.search(r'#\s*(TODO|FIXME|XXX|HACK|NOTE)\b[:\s]?(.*)', line, re.IGNORECASE):
                todos.append((i, f"{m.group(1).upper()}: {m.group(2).strip()}"))

    return ModuleMap(
        path=filepath, docstring=ast.get_docstring(tree),
        imports=visitor.imports, functions=visitor.functions, classes=visitor.classes,
        globals=visitor.globals, anti_patterns=visitor.anti_patterns, todos=todos,
        import_categories=_categorize_imports(visitor.imports) if opts.track_import_categories else {}
    )


# ==========================================
# 5. BACKEND: EXTERNAL TOOLS (RUFF / RADON / MYPY)
# ==========================================

def run_external_analysis(files: List[str], opts: ScanOptions) -> Dict[str, dict]:
    """Runs Ruff, Radon, and Mypy on selected files in chunks."""
    results = defaultdict(lambda: {"ruff": [], "mi_score": None, "mi_rank": None, "mypy": []})
    
    chunk_size = 50
    file_chunks = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]
    
    # Regex to parse Mypy output: filepath:line:[column:] severity: message
    mypy_regex = re.compile(r'^(.*?):(\d+):(?:(\d+):)?\s*(error|warning|note):\s*(.*)$')

    for chunk in file_chunks:
        # 1. RUFF
        if opts.run_ruff_analysis and HAS_RUFF:
            cmd = ["ruff", "check", "--output-format=json", "--select=E,F,B,UP,C90,PLR,PLC,RUF"] + chunk
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.stdout.strip():
                    ruff_data = json.loads(res.stdout)
                    for item in ruff_data:
                        fp = str(Path(item.get("filename", "")).resolve())
                        results[fp]["ruff"].append(RuffIssue(
                            code=item.get("code", ""),
                            message=item.get("message", ""),
                            row=item.get("location", {}).get("row", 0)
                        ))
            except Exception as e:
                print(f"Ruff integration failed on chunk: {e}")

        # 2. RADON
        if opts.run_radon_analysis and HAS_RADON:
            cmd = ["radon", "mi", "-s", "-j"] + chunk
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.stdout.strip():
                    radon_data = json.loads(res.stdout)
                    for fp, data in radon_data.items():
                        abs_fp = str(Path(fp).resolve())
                        results[abs_fp]["mi_score"] = data.get("mi")
                        results[abs_fp]["mi_rank"] = data.get("rank")
            except Exception as e:
                print(f"Radon integration failed on chunk: {e}")
                
        # 3. MYPY
        if opts.run_mypy_analysis and HAS_MYPY:
            cmd = ["mypy", "--no-error-summary", "--hide-error-context", "--show-error-codes"] + chunk
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                for line in res.stdout.splitlines():
                    match = mypy_regex.match(line)
                    if match:
                        fp_str, ln_str, _col_str, sev_str, msg_str = match.groups()
                        abs_fp = str(Path(fp_str).resolve())
                        results[abs_fp]["mypy"].append(MypyIssue(
                            line=int(ln_str),
                            severity=sev_str.upper(),
                            message=msg_str
                        ))
            except Exception as e:
                print(f"Mypy integration failed on chunk: {e}")

    return results


# ==========================================
# 6. BACKEND: FORMATTERS
# ==========================================

def to_text(m: ModuleMap, opts: ScanOptions) -> str:
    mi_str = f"  [MI: {m.mi_score:.1f} ({m.mi_rank})]" if m.mi_score is not None else ""
    lines = [f"## Module: {m.path}{mi_str}"]
    if m.docstring: lines.append(f'  Purpose: {m.docstring.splitlines()[0]}')

    if m.import_categories:
        for label, key in (("stdlib", "stdlib"), ("third-party", "third_party"), ("local", "local")):
            if bucket := m.import_categories.get(key):
                lines.append(f"  Imports [{label}]: {', '.join(bucket)}")
    elif m.imports:
        lines.append(f"  Imports: {', '.join(i.raw for i in m.imports)}")

    if m.globals: lines.append(f"  Globals: {', '.join(m.globals)}")

    if m.anti_patterns:
        lines.append(f"\n  ⚠ AST Anti-patterns ({len(m.anti_patterns)}):")
        for ap in m.anti_patterns:
            lines.append(f"    ⚠ [line {ap.lineno}] {ap.category}: {ap.message}")

    if m.ruff_issues:
        lines.append(f"\n  🛑 Deep Smells & Legacy (Ruff - {len(m.ruff_issues)}):")
        for r in m.ruff_issues:
            lines.append(f"    🛑 [line {r.row}] [{r.code}] {r.message}")
            
    if m.mypy_issues:
        lines.append(f"\n  🛡️ Type Checking Issues (Mypy - {len(m.mypy_issues)}):")
        for mypy in m.mypy_issues:
            lines.append(f"    🛡️ [line {mypy.line}] {mypy.severity}: {mypy.message}")

    if m.todos:
        lines.append(f"\n  ✎ TODO markers ({len(m.todos)}):")
        for ln, text in m.todos: lines.append(f"    ✎ [line {ln}] {text}")

    for cls in m.classes:
        lines.append(f"\n  class {cls.name}({', '.join(cls.bases)})  [line {cls.lineno}]")
        for fn in cls.methods:
            sig = f"({', '.join(fn.args)})" + (f" -> {fn.return_type}" if opts.track_return_types and fn.return_type else "")
            lines.append(f"    {'async ' if fn.is_async else ''}def {fn.name}{sig}  (cc={fn.complexity}, {fn.num_lines}L)")

    for fn in m.functions:
        sig = f"({', '.join(fn.args)})" + (f" -> {fn.return_type}" if opts.track_return_types and fn.return_type else "")
        lines.append(f"\n  {'async ' if fn.is_async else ''}def {fn.name}{sig}  [line {fn.lineno}]  (cc={fn.complexity}, {fn.num_lines}L)")

    return "\n".join(lines)


# ==========================================
# 7. FRONTEND: CORE WIDGETS
# ==========================================

class FileTreeWidget(QTreeWidget):
    selection_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_clicked_leaf = None
        self._updating = False
        self.itemChanged.connect(self._on_item_changed)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    def populate(self, root_dir: str):
        self._updating = True
        self.clear()
        self._last_clicked_leaf = None
        root = Path(root_dir)

        all_files = sorted([p for p in root.rglob("*.py") if not any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts)])
        dir_items = {}

        for fp in all_files:
            rel = fp.relative_to(root)
            parent_item = self.invisibleRootItem()
            accumulated = root
            for part in rel.parts[:-1]:
                accumulated = accumulated / part
                if accumulated not in dir_items:
                    folder_item = QTreeWidgetItem(parent_item, [part])
                    folder_item.setFlags(folder_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                    folder_item.setCheckState(0, Qt.CheckState.Checked)
                    folder_item.setData(0, Qt.ItemDataRole.UserRole, None)
                    dir_items[accumulated] = folder_item
                parent_item = dir_items[accumulated]

            leaf = QTreeWidgetItem(parent_item, [fp.name])
            leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.CheckState.Checked)
            leaf.setData(0, Qt.ItemDataRole.UserRole, str(fp))

        self.expandAll()
        self._updating = False
        self._emit_counts()

    def checked_files(self) -> list:
        out = []
        def _collect(p):
            for i in range(p.childCount()):
                child = p.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole):
                    if child.checkState(0) == Qt.CheckState.Checked: out.append(child.data(0, Qt.ItemDataRole.UserRole))
                else: _collect(child)
        _collect(self.invisibleRootItem())
        return out

    def _on_item_changed(self, item, col):
        if not self._updating: self._emit_counts()

    def _emit_counts(self):
        leaves = []
        def _collect_leaves(p):
            for i in range(p.childCount()):
                child = p.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole): leaves.append(child)
                else: _collect_leaves(child)
        _collect_leaves(self.invisibleRootItem())
        checked = sum(1 for it in leaves if it.checkState(0) == Qt.CheckState.Checked)
        self.selection_changed.emit(checked, len(leaves))

class MapHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules, self._block_rules = [], []

        def rule(pattern, color, bold=False, whole_line=False, bg=None):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold: fmt.setFontWeight(QFont.Weight.Bold)
            if bg: fmt.setBackground(QColor(bg))
            if whole_line: self._block_rules.append((re.compile(pattern), fmt))
            else: self._rules.append((re.compile(pattern), fmt))

        rule(r"^\s*⚠.*", "#fca5a5", bold=True, whole_line=True, bg="#3f1d1d")
        rule(r"^\s*🛑.*", "#ef4444", bold=True, whole_line=True, bg="#450a0a") # Ruff errors
        rule(r"^\s*🛡️.*", "#60a5fa", bold=True, whole_line=True, bg="#1e3a8a") # Mypy errors
        rule(r"^\s*✎.*", "#fcd34d", whole_line=True, bg="#2e2512")
        rule(r"^## Module:.*", "#7dd3fc", bold=True)
        rule(r"\[MI: [0-9.]+ \([A-F]\)\]", "#10b981", bold=True) # MI Score
        rule(r"\bclass\s+\w+", "#f9a8d4", bold=True)
        rule(r"\b(?:async\s+)?def\s+\w+", "#86efac")
        rule(r"\[line \d+\]", "#6b7280")
        rule(r"\bcc=\d+", "#fdba74")

    def highlightBlock(self, text):
        for pattern, fmt in self._block_rules:
            if pattern.match(text):
                self.setFormat(0, len(text), fmt)
                return
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ==========================================
# 8. FRONTEND: WORKER THREAD
# ==========================================

class ScanWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(list, dict)
    error = Signal(str)

    def __init__(self, files: list, opts: ScanOptions):
        super().__init__()
        self.files = files
        self.opts = opts

    def run(self):
        try:
            total = len(self.files)
            maps = []
            stats = {"modules": 0, "classes": 0, "functions": 0, "anti_patterns": 0, "errors": 0}

            # 1. Run External Analysis first
            self.progress.emit(0, total, "Running external analysis (Ruff/Radon/Mypy)...")
            ext_results = run_external_analysis(self.files, self.opts)

            # 2. Run AST Analysis & Merge
            for i, fp in enumerate(self.files):
                self.progress.emit(i + 1, total, Path(fp).name)
                try:
                    m = build_module_map(fp, self.opts)
                    
                    # Merge external data
                    abs_fp = str(Path(fp).resolve())
                    if abs_fp in ext_results:
                        m.ruff_issues = ext_results[abs_fp]["ruff"]
                        m.mypy_issues = ext_results[abs_fp]["mypy"]
                        m.mi_score = ext_results[abs_fp]["mi_score"]
                        m.mi_rank = ext_results[abs_fp]["mi_rank"]

                    maps.append(m)
                    stats["modules"] += 1
                    stats["classes"] += len(m.classes)
                    stats["functions"] += len(m.functions) + sum(len(c.methods) for c in m.classes)
                    stats["anti_patterns"] += len(m.anti_patterns) + len(m.ruff_issues) + len(m.mypy_issues)
                except SyntaxError:
                    stats["errors"] += 1

            # Sort maps so worst MI score is at the top
            maps.sort(key=lambda x: x.mi_score if x.mi_score is not None else 999)
            self.finished.emit(maps, stats)
        except Exception as e:
            self.error.emit(str(e))


# ==========================================
# 9. FRONTEND: MAIN WINDOW
# ==========================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Extended Python Code Map & Reviewer")
        self.setMinimumSize(1200, 800)
        self._root_dir, self._result_text = None, ""
        self._worker, self._thread = None, None
        self._check_widgets, self._spin_widgets = {}, {}
        self._setup_ui()
        self.setStyleSheet(self._get_stylesheet())

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # Folder picker
        card = QFrame(); card.setObjectName("card")
        cl = QHBoxLayout(card)
        btn_open = QPushButton("⊞ Open Folder…"); btn_open.clicked.connect(self._open_folder)
        self.lbl_path = QLabel("No folder selected")
        self.btn_scan = QPushButton("▶ Generate Map"); self.btn_scan.setObjectName("primary"); self.btn_scan.clicked.connect(self._start_scan)
        cl.addWidget(btn_open); cl.addWidget(self.lbl_path, 1); cl.addWidget(self.btn_scan)
        root_layout.addWidget(card)

        # Progress
        self.progress_bar = QProgressBar(); self.progress_bar.setFixedHeight(6); self.progress_bar.setTextVisible(False)
        self.lbl_progress = QLabel("")
        pr = QHBoxLayout(); pr.addWidget(self.progress_bar); pr.addWidget(self.lbl_progress); root_layout.addLayout(pr)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        # LEFT PANEL
        left = QWidget(); ll = QVBoxLayout(left)
        self.lbl_sel_count = QLabel("—")
        th = QHBoxLayout(); th.addWidget(QLabel("FILES")); th.addStretch(); th.addWidget(self.lbl_sel_count); ll.addLayout(th)
        self.file_tree = FileTreeWidget(); self.file_tree.selection_changed.connect(self._on_tree_changed); ll.addWidget(self.file_tree, 1)
        ll.addWidget(self._build_options_panel())
        splitter.addWidget(left)

        # RIGHT PANEL
        right = QWidget(); rl = QVBoxLayout(right)
        self.btn_save = QPushButton("⬇ Save Report"); self.btn_save.clicked.connect(self._save_file)
        oh = QHBoxLayout(); oh.addWidget(QLabel("OUTPUT")); oh.addStretch(); oh.addWidget(self.btn_save); rl.addLayout(oh)
        
        self.output = QTextEdit(); self.output.setReadOnly(True)
        self.highlighter = MapHighlighter(self.output.document())
        rl.addWidget(self.output, 1)
        splitter.addWidget(right)
        splitter.setSizes([350, 850])

    def _build_options_panel(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFixedHeight(340)
        vbox = QVBoxLayout(container := QWidget())
        defaults = ScanOptions()

        def add_card(title, opts_list):
            card = QFrame(); card.setObjectName("optcard"); lay = QVBoxLayout(card)
            lay.addWidget(QLabel(title, objectName="sechead"))
            for attr, label in opts_list:
                cb = QCheckBox(label); cb.setChecked(getattr(defaults, attr)); lay.addWidget(cb)
                self._check_widgets[attr] = cb
            return card

        vbox.addWidget(add_card("AST TRACKING", [
            ("track_complexity", "Complexity (cc)"), ("track_return_types", "Return types"), ("track_todos", "TODO markers")
        ]))
        
        vbox.addWidget(add_card("AST ANTI-PATTERNS", [
            ("detect_wildcard", "Wildcard imports"), ("detect_mutable_defaults", "Mutable defaults"),
            ("detect_long_functions", "Long functions"), ("detect_god_classes", "God classes")
        ]))

        # External Tools Card
        ext_card = QFrame(); ext_card.setObjectName("optcard"); ext_lay = QVBoxLayout(ext_card)
        ext_lay.addWidget(QLabel("EXTERNAL REFACTORING TOOLS", objectName="sechead"))
        
        cb_ruff = QCheckBox("Ruff: Deep smells & legacy syntax")
        cb_ruff.setChecked(HAS_RUFF); cb_ruff.setEnabled(HAS_RUFF)
        if not HAS_RUFF: cb_ruff.setText("Ruff (Not installed)")
        self._check_widgets["run_ruff_analysis"] = cb_ruff; ext_lay.addWidget(cb_ruff)

        cb_radon = QCheckBox("Radon: Maintainability Index (MI)")
        cb_radon.setChecked(HAS_RADON); cb_radon.setEnabled(HAS_RADON)
        if not HAS_RADON: cb_radon.setText("Radon (Not installed)")
        self._check_widgets["run_radon_analysis"] = cb_radon; ext_lay.addWidget(cb_radon)
        
        cb_mypy = QCheckBox("Mypy: Static type checking")
        cb_mypy.setChecked(HAS_MYPY); cb_mypy.setEnabled(HAS_MYPY)
        if not HAS_MYPY: cb_mypy.setText("Mypy (Not installed)")
        self._check_widgets["run_mypy_analysis"] = cb_mypy; ext_lay.addWidget(cb_mypy)
        
        vbox.addWidget(ext_card)
        vbox.addStretch(); scroll.setWidget(container)
        return scroll

    def _current_options(self):
        opts = ScanOptions()
        for attr, cb in self._check_widgets.items(): setattr(opts, attr, cb.isChecked())
        return opts

    def _on_tree_changed(self, checked, total):
        self.lbl_sel_count.setText(f"{checked}/{total}")
        self.btn_scan.setEnabled(checked > 0)

    def _open_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Folder", str(Path.home())):
            self._root_dir = folder
            self.lbl_path.setText(folder)
            self.file_tree.populate(folder)

    def _start_scan(self):
        files = self.file_tree.checked_files()
        if not files: return
        self.btn_scan.setEnabled(False)
        self.output.clear()
        
        self._thread = QThread()
        self._worker = ScanWorker(files, self._current_options())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda c, t, n: self.progress_bar.setValue(c))
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, maps, stats):
        opts = self._current_options()
        self._result_text = "\n\n".join(to_text(m, opts) for m in maps)
        self.output.setPlainText(self._result_text)
        self.btn_scan.setEnabled(True)

    def _save_file(self):
        if path := QFileDialog.getSaveFileName(self, "Save", "report.txt", "Text (*.txt)")[0]:
            Path(path).write_text(self._result_text, encoding="utf-8")

    def _get_stylesheet(self):
        return """
        QMainWindow, QWidget { background-color: #0f1117; color: #e2e8f0; font-family: system-ui; font-size: 13px; }
        QPushButton { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 6px; }
        QPushButton#primary { background-color: #1d4ed8; border-color: #2563eb; color: #fff; font-weight: bold; }
        QTextEdit { background-color: #0a0d14; border: 1px solid #1e293b; font-family: monospace; }
        QTreeWidget { background-color: #0a0d14; border: 1px solid #1e293b; }
        QFrame#card, QFrame#optcard { background-color: #141a25; border: 1px solid #1e293b; border-radius: 6px; }
        QLabel#sechead { color: #94a3b8; font-size: 10px; font-weight: bold; letter-spacing: 1px; }
        """

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow(); win.show()
    sys.exit(app.exec())
