"""
Main UV project management mixin (UI building, command execution, settings).
"""

import os
import re
import subprocess
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtWidgets import (
    QDockWidget, QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QGroupBox, QLineEdit, QPushButton, QCheckBox,
    QComboBox, QLabel, QPlainTextEdit, QTabWidget, QMessageBox, QFileDialog,
    QProgressDialog, QDialog, QSizePolicy
)

# Helper imports (assumed available in the parent application)
from core_ui_helpers import CollapsibleGroupBox, QHLine

# Local imports from the uv_project package
from .scanner import DependencyScannerThread
from .dialogs import DependencyUpdateDialog

# For pyproject.toml parsing
try:
    import tomllib
except ImportError:
    tomllib = None


class UvProjectMixin:
    """Mixin providing a UV project management dock panel with auto‑dependency detection."""

    # ------------------------------------------------------------------
    # Main dock builder
    # ------------------------------------------------------------------
    def _build_uv_project_dock(self):
        dock = QDockWidget("UV Project Manager", self)
        dock.setObjectName("uvProjectDock")
        dock.setMinimumSize(460, 520)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetMovable)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)

        tabs = QTabWidget()

        # ---- Tab 1: Project & Dependencies ----
        proj_tab = QWidget()
        proj_layout = QVBoxLayout(proj_tab)
        proj_layout.addWidget(self._build_project_info_group())
        proj_layout.addWidget(self._build_python_and_env_group())  # Combined group
        proj_layout.addWidget(self._build_dependencies_group())
        proj_layout.addStretch()
        tabs.addTab(proj_tab, "Project && Dependencies")

        # ---- Tab 2: Run & Publish ----
        exec_tab = QWidget()
        exec_layout = QVBoxLayout(exec_tab)
        exec_layout.addWidget(self._build_run_group())
        exec_layout.addWidget(self._build_build_group())
        exec_layout.addWidget(self._build_publish_group())
        exec_layout.addStretch()
        tabs.addTab(exec_tab, "Run && Publish")

        layout.addWidget(tabs)
        scroll.setWidget(container)
        dock.setWidget(scroll)

        QTimer.singleShot(100, self._refresh_uv_info)
        QTimer.singleShot(150, self._check_uv_version)
        return dock

    # ------------------------------------------------------------------
    # UI Group Builders
    # ------------------------------------------------------------------
    def _build_project_info_group(self):
        group = QGroupBox("Project Info")
        form = QFormLayout(group)

        # Folder selection row: QLineEdit + two picker buttons
        path_row = QHBoxLayout()
        self.uv_project_folder_edit = QLineEdit()
        self.uv_project_folder_edit.setPlaceholderText("Select or enter project folder path")
        self.uv_project_folder_edit.setToolTip(
            "Root folder of the UV project (must contain pyproject.toml).\n"
            "You can type a path or use the buttons to browse."
        )
        self.uv_project_folder_edit.textChanged.connect(self._refresh_uv_info)
        path_row.addWidget(self.uv_project_folder_edit, 1)

        btn_browse_folder = QPushButton("📁")
        btn_browse_folder.setFixedWidth(30)
        self._setup_button(btn_browse_folder, "Browse for project folder")
        self._style_square_icon_button(btn_browse_folder)
        btn_browse_folder.clicked.connect(self._browse_project_folder)
        path_row.addWidget(btn_browse_folder)

        btn_browse_file = QPushButton("📄")
        btn_browse_file.setFixedWidth(30)
        self._setup_button(btn_browse_file, "Select pyproject.toml file")
        self._style_square_icon_button(btn_browse_file)
        btn_browse_file.clicked.connect(self._browse_pyproject_file)
        path_row.addWidget(btn_browse_file)

        form.addRow("Project Folder:", path_row)

        # ---- Grid for UV Project, UV Version and refresh button ----
        grid_layout = QGridLayout()
        # Row 0
        grid_layout.addWidget(QLabel("UV Project:"), 0, 0)
        self.uv_project_detected_label = QLabel("Unknown")
        self.uv_project_detected_label.setWordWrap(True)
        self.uv_project_detected_label.setToolTip("Indicates whether a pyproject.toml exists in the selected folder.")
        grid_layout.addWidget(self.uv_project_detected_label, 0, 1)

        btn_refresh = QPushButton("🔄")
        self._setup_button(btn_refresh, "Refresh project status, dependencies, console scripts, and Python version pin.")
        self._style_square_icon_button(btn_refresh)
        btn_refresh.clicked.connect(self._refresh_uv_info)
        grid_layout.addWidget(btn_refresh, 0, 2)

        # Row 1
        grid_layout.addWidget(QLabel("UV Version:"), 1, 0)
        self.uv_version_label = QLabel("Checking...")
        self.uv_version_label.setWordWrap(True)
        self.uv_version_label.setToolTip("Version of the UV tool found on the system.")
        grid_layout.addWidget(self.uv_version_label, 1, 1)
        # Column 2 of row 1 is left empty

        form.addRow(grid_layout)

        form.addRow(QHLine())

        # Project name row: line edit only
        self.uv_init_name_edit = QLineEdit()
        self.uv_init_name_edit.setPlaceholderText("(optional) subdirectory name")
        self.uv_init_name_edit.setToolTip(
            "If provided, creates a new subdirectory with this name inside the project folder and initializes UV there."
        )
        form.addRow("Project Name:", self.uv_init_name_edit)

        # Initialize button placed below
        btn_init = QPushButton("📁 Initialize UV Project")
        self._setup_button(btn_init, "Run 'uv init' in the active project directory.")
        self._style_critical_button(btn_init, "#0277BD", "#01579B")
        btn_init.clicked.connect(self._uv_init_project)
        form.addRow(btn_init)

        return group

    def _build_python_and_env_group(self):
        """Combined collapsible group for Python version management and environment sync/lock."""
        group = CollapsibleGroupBox("Python && Environment")
        group.setToolTip("Manage Python version, lock dependencies, sync the virtual environment, and export requirements.txt.")

        layout = QVBoxLayout(group.content_widget)

        # ---- Python version row with label and two square buttons ----
        version_row = QHBoxLayout()
        version_label = QLabel("Version:")
        version_label.setToolTip("Python version to pin (e.g., 3.12)")
        version_row.addWidget(version_label)

        self.uv_py_version_edit = QLineEdit()
        self.uv_py_version_edit.setPlaceholderText("e.g., 3.12, 3.13")
        self.uv_py_version_edit.setToolTip(
            "Pin a specific Python version for this project.\n"
            "Use 'Apply' to run 'uv python pin <version>'.\n"
            "Use 'Detect' to get the current environment's Python version and pin it."
        )
        version_row.addWidget(self.uv_py_version_edit, 1)

        # Apply button (🐍)
        btn_apply_py = QPushButton("🐍")
        btn_apply_py.setFixedWidth(30)
        self._setup_button(btn_apply_py, "Apply the entered Python version (uv python pin).")
        self._style_square_icon_button(btn_apply_py)
        btn_apply_py.clicked.connect(self._uv_set_python_version)
        version_row.addWidget(btn_apply_py)

        # Detect from environment button (🔍)
        btn_detect_py = QPushButton("🔍")
        btn_detect_py.setFixedWidth(30)
        self._setup_button(btn_detect_py, "Detect Python version from the current environment and pin it.")
        self._style_square_icon_button(btn_detect_py)
        btn_detect_py.clicked.connect(self._uv_sync_python_version_from_env)
        version_row.addWidget(btn_detect_py)

        layout.addLayout(version_row)

        # ---- Environment Sync, Lock, and Export (all horizontal) ----
        env_row = QHBoxLayout()

        btn_lock = QPushButton("🔒 Lock Dependencies")
        self._setup_button(btn_lock, "Generate or update uv.lock based on pyproject.toml (uv lock).")
        btn_lock.clicked.connect(self._uv_lock)
        env_row.addWidget(btn_lock)

        btn_sync = QPushButton("⚡ Sync Environment")
        self._setup_button(btn_sync, "Install all packages from the lockfile into the virtual environment (uv sync).")
        btn_sync.clicked.connect(self._uv_sync)
        env_row.addWidget(btn_sync)

        # Export requirements as a square icon button (smaller, tooltip)
        btn_export = QPushButton("📄")
        btn_export.setFixedWidth(30)
        self._setup_button(btn_export, "Export the current lockfile to requirements.txt format using 'uv export'.")
        self._style_square_icon_button(btn_export)
        btn_export.clicked.connect(self._uv_export_requirements)
        env_row.addWidget(btn_export)

        layout.addLayout(env_row)

        return group

    def _build_dependencies_group(self):
        group = CollapsibleGroupBox("Dependency Management")
        group.setToolTip("Add, remove, or upgrade packages.")
        layout = QVBoxLayout(group.content_widget)

        # ---- Auto‑detect section (button at the very top, checkbox below) ----
        # Button with search icon, teal color, extensive tooltip
        btn_auto_detect = QPushButton("🔍 Auto‑detect imports")
        btn_auto_detect.setToolTip(
            "Scan all Python files in the project, detect third‑party import statements, and suggest adding missing packages to pyproject.toml.\n\n"
            "Process:\n"
            "• AST parsing extracts imported module names\n"
            "• Standard library modules are automatically filtered out\n"
            "• Imports are mapped to PyPI package names (with common overrides)\n"
            "• Installed and latest versions are checked using your project's Python interpreter and PyPI API\n"
            "• A dialog shows detected packages where you can select which ones to add, choose version constraints, and mark as dev dependencies."
        )
        self._style_critical_button(btn_auto_detect, "#00897B", "#00695C")  # teal, not pink/red/blue
        btn_auto_detect.clicked.connect(self._auto_detect_and_sync_dependencies)
        layout.addWidget(btn_auto_detect)

        # Checkbox directly below, no extra indentation (matches build_tools_pane style)
        self.dev_detect_checkbox = QCheckBox("Detect dev dependencies (tests/, conftest.py, *_test.py)")
        self.dev_detect_checkbox.setToolTip(
            "When enabled, imports found inside 'tests/' folders, 'conftest.py', or '*_test.py' files will be marked as development dependencies in the detection dialog."
        )
        layout.addWidget(self.dev_detect_checkbox)

        layout.addWidget(QHLine())

        # Add row
        add_row = QHBoxLayout()
        self.uv_add_name_edit = QLineEdit()
        self.uv_add_name_edit.setPlaceholderText("package1 package2 ...")
        self.uv_add_name_edit.setToolTip("One or more package names (space separated).")
        add_row.addWidget(self.uv_add_name_edit)

        self.uv_add_version_edit = QLineEdit()
        self.uv_add_version_edit.setPlaceholderText(">=1.0.0 (opt)")
        self.uv_add_version_edit.setToolTip("Version specifier applied to all listed packages.")
        self.uv_add_version_edit.setMaximumWidth(100)
        add_row.addWidget(self.uv_add_version_edit)

        self.uv_add_dev_cb = QCheckBox("Dev")
        self.uv_add_dev_cb.setToolTip("Add to dev dependencies (--dev).")
        add_row.addWidget(self.uv_add_dev_cb)

        btn_add = QPushButton("➕")
        self._setup_button(btn_add, "Add packages (uv add)")
        self._style_square_icon_button(btn_add)
        btn_add.clicked.connect(self._uv_add_dependency)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        # Upgrade row
        upgrade_row = QHBoxLayout()
        self.uv_upgrade_edit = QLineEdit()
        self.uv_upgrade_edit.setPlaceholderText("package to upgrade")
        self.uv_upgrade_edit.setToolTip("Upgrade a single package to the latest version.")
        upgrade_row.addWidget(self.uv_upgrade_edit)

        btn_upgrade = QPushButton("⬆️")
        self._setup_button(btn_upgrade, "Upgrade package (uv add --upgrade)")
        self._style_square_icon_button(btn_upgrade)
        btn_upgrade.clicked.connect(self._uv_upgrade_dependency)
        upgrade_row.addWidget(btn_upgrade)
        layout.addLayout(upgrade_row)

        # Remove row
        remove_row = QHBoxLayout()
        self.uv_remove_edit = QLineEdit()
        self.uv_remove_edit.setPlaceholderText("package to remove")
        self.uv_remove_edit.setToolTip("Package name to remove from dependencies.")
        remove_row.addWidget(self.uv_remove_edit)

        btn_remove = QPushButton("🗑️")
        self._setup_button(btn_remove, "Remove package (uv remove)")
        self._style_square_icon_button(btn_remove)
        btn_remove.clicked.connect(self._uv_remove_dependency)
        remove_row.addWidget(btn_remove)
        layout.addLayout(remove_row)

        layout.addWidget(QHLine())

        self.uv_deps_list = QPlainTextEdit()
        self.uv_deps_list.setReadOnly(True)
        self.uv_deps_list.setMaximumHeight(120)
        self.uv_deps_list.setToolTip("Dependencies from pyproject.toml.")
        layout.addWidget(self.uv_deps_list)

        return group

    def _build_run_group(self):
        group = CollapsibleGroupBox("Run Project")
        group.setToolTip("Execute scripts or console commands using 'uv run'.")
        layout = QVBoxLayout(group.content_widget)

        # Script row: line edit + file picker + run button
        script_row = QHBoxLayout()
        self.uv_run_script_edit = QLineEdit()
        self.uv_run_script_edit.setPlaceholderText("main.py or script name")
        self.uv_run_script_edit.setToolTip("Entry point passed to 'uv run'.")
        script_row.addWidget(self.uv_run_script_edit)

        # File picker button (📄)
        btn_file_picker = QPushButton("📄")
        btn_file_picker.setFixedWidth(30)
        self._setup_button(btn_file_picker, "Select a Python script file")
        self._style_square_icon_button(btn_file_picker)
        btn_file_picker.clicked.connect(self._browse_script_file)
        script_row.addWidget(btn_file_picker)

        # Run button (▶️)
        btn_run = QPushButton("▶️")
        self._setup_button(btn_run, "Execute 'uv run <script>' (interactive)")
        self._style_square_icon_button(btn_run)
        btn_run.clicked.connect(self._uv_run_script)
        script_row.addWidget(btn_run)
        layout.addLayout(script_row)

        # Console scripts label and text edit (expanding)
        layout.addWidget(QLabel("Console scripts from [project.scripts]:"))
        self.uv_console_scripts_list = QPlainTextEdit()
        self.uv_console_scripts_list.setReadOnly(True)
        # Remove fixed maximum height to allow vertical expansion
        self.uv_console_scripts_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.uv_console_scripts_list, 1)  # give stretch factor

        return group

    def _build_build_group(self):
        group = CollapsibleGroupBox("Build Distributions")
        form = QFormLayout(group.content_widget)

        build_row = QHBoxLayout()
        self.uv_build_type = QComboBox()
        self.uv_build_type.addItems(["Both (sdist + wheel)", "Source only (--sdist)", "Wheel only (--wheel)"])
        self.uv_build_type.setToolTip("Choose distribution formats.")
        self.uv_build_type.currentIndexChanged.connect(lambda: self.save_current_settings())
        build_row.addWidget(QLabel("Type:"))
        build_row.addWidget(self.uv_build_type)

        self.uv_build_output_dir = QLineEdit()
        self.uv_build_output_dir.setPlaceholderText("dist (default)")
        self.uv_build_output_dir.setToolTip("Output directory for built distributions.")
        self.uv_build_output_dir.textChanged.connect(lambda: self.save_current_settings())
        build_row.addWidget(QLabel("Out:"))
        build_row.addWidget(self.uv_build_output_dir)
        form.addRow(build_row)

        btn_build = QPushButton("📦 Build Distribution")  # package icon
        self._setup_button(btn_build, "Run 'uv build'")
        self._style_critical_button(btn_build, "#2E7D32", "#1B5E20")  # keep green
        btn_build.clicked.connect(self._uv_build)
        form.addRow(btn_build)

        return group

    def _build_publish_group(self):
        group = CollapsibleGroupBox("Publish to PyPI / TestPyPI")
        form = QFormLayout(group.content_widget)

        self.uv_publish_index_combo = QComboBox()
        self.uv_publish_index_combo.addItems(["PyPI (official)", "TestPyPI", "Custom Index"])
        self.uv_publish_index_combo.setToolTip("Target package index.")
        self.uv_publish_index_combo.currentTextChanged.connect(self._on_publish_index_changed)
        self.uv_publish_index_combo.currentTextChanged.connect(lambda: self.save_current_settings())
        form.addRow("Index:", self.uv_publish_index_combo)

        self.uv_publish_custom_index_edit = QLineEdit()
        self.uv_publish_custom_index_edit.setPlaceholderText("https://my.pypi.org/legacy/")
        self.uv_publish_custom_index_edit.setEnabled(False)
        self.uv_publish_custom_index_edit.setToolTip("Custom --publish-url when 'Custom Index' is selected.")
        self.uv_publish_custom_index_edit.textChanged.connect(lambda: self.save_current_settings())
        form.addRow("Custom URL:", self.uv_publish_custom_index_edit)

        self.uv_publish_token_edit = QLineEdit()
        self.uv_publish_token_edit.setEchoMode(QLineEdit.Password)
        self.uv_publish_token_edit.setPlaceholderText("pypi-xxxxxxxx (optional)")
        self.uv_publish_token_edit.setToolTip("API token for the selected index.")
        self.uv_publish_token_edit.textChanged.connect(lambda: self.save_current_settings())
        form.addRow("API Token:", self.uv_publish_token_edit)

        btn_publish = QPushButton("🌐 Publish Package")  # globe wiregrid icon
        self._setup_button(btn_publish, "Upload built distributions using 'uv publish'.")
        # Use blue tone (not red)
        self._style_critical_button(btn_publish, "#1976D2", "#1565C0")
        btn_publish.clicked.connect(self._uv_publish)
        form.addRow(btn_publish)

        return group

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------
    def _get_uv_project_folder(self) -> str:
        """Return the current project folder from the QLineEdit."""
        if hasattr(self, "uv_project_folder_edit"):
            path = self.uv_project_folder_edit.text().strip()
            if path and os.path.isdir(path):
                return path
        return ""

    def _is_uv_project(self, folder: str) -> bool:
        return bool(folder and os.path.isfile(os.path.join(folder, "pyproject.toml")))

    def _refresh_uv_info(self):
        folder = self._get_uv_project_folder()
        is_uv = self._is_uv_project(folder)
        self.uv_project_detected_label.setText(
            "Yes (pyproject.toml exists)" if is_uv else "No (not a UV project)"
        )
        if is_uv:
            self._load_pyproject_dependencies(folder)
            self._update_console_scripts_display(folder)
        else:
            self.uv_deps_list.setPlainText("No project folder selected or pyproject.toml not found.")
            self.uv_console_scripts_list.setPlainText("No project folder selected or pyproject.toml not found.")

        py_ver_file = os.path.join(folder, ".python-version") if folder else ""
        if folder and os.path.isfile(py_ver_file):
            try:
                with open(py_ver_file, "r", encoding="utf-8") as f:
                    self.uv_py_version_edit.setText(f.read().strip())
            except Exception:
                self.uv_py_version_edit.clear()
        else:
            self.uv_py_version_edit.clear()

    def _check_uv_version(self):
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
            )
            if result.returncode == 0 and result.stdout:
                self.uv_version_label.setText(result.stdout.strip())
            else:
                self.uv_version_label.setText("UV not found or error")
        except Exception as e:
            self.uv_version_label.setText(f"UV not found: {e}")

    def _load_pyproject_dependencies(self, folder: str):
        if tomllib is None:
            self.uv_deps_list.setPlainText("tomllib not available (Python <3.11).")
            return
        pyproject_path = os.path.join(folder, "pyproject.toml")
        if not os.path.isfile(pyproject_path):
            self.uv_deps_list.setPlainText("pyproject.toml not found.")
            return
        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            deps = data.get("project", {}).get("dependencies", [])
            dev_group = data.get("dependency-groups", {}).get("dev", [])
            text = "Dependencies:\n" + "\n".join(f"  {d}" for d in deps)
            text += "\n\nDev dependencies:\n" + "\n".join(f"  {d}" for d in dev_group)
            self.uv_deps_list.setPlainText(text)
        except Exception as e:
            self.uv_deps_list.setPlainText(f"Error reading pyproject.toml: {e}")

    def _update_console_scripts_display(self, folder: str):
        if tomllib is None or not folder:
            self.uv_console_scripts_list.setPlainText("tomllib not available or no folder.")
            return
        pyproject_path = os.path.join(folder, "pyproject.toml")
        if not os.path.isfile(pyproject_path):
            self.uv_console_scripts_list.setPlainText("pyproject.toml not found.")
            return
        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            scripts = data.get("project", {}).get("scripts", {})
            if not scripts:
                self.uv_console_scripts_list.setPlainText("No console scripts defined.")
            else:
                lines = [f"{name} -> {ref}" for name, ref in scripts.items()]
                self.uv_console_scripts_list.setPlainText("\n".join(lines))
        except Exception as e:
            self.uv_console_scripts_list.setPlainText(f"Error: {e}")

    def _on_publish_index_changed(self, text: str):
        self.uv_publish_custom_index_edit.setEnabled(text == "Custom Index")

    def _schedule_refresh(self, delay_ms: int = 1500):
        QTimer.singleShot(delay_ms, self._refresh_uv_info)

    # ------------------------------------------------------------------
    # Command Execution
    # ------------------------------------------------------------------
    def _run_uv_command(self, args: list, command_name: str, folder: str = "", interactive: bool = False):
        target = folder or self._get_uv_project_folder()
        if not target:
            QMessageBox.warning(self, "No Project Folder",
                                "Please select a valid project folder in the UV Project Manager pane.")
            return
        self.save_current_settings()
        self.run_command(
            program="uv",
            args=args,
            working_dir=target,
            command_name=command_name,
            env_data={"type": "system"},
            refresh_packages=False,
            require_msvc=False,
            interactive=interactive,
        )

    def _browse_project_folder(self):
        current_dir = self._get_uv_project_folder() or os.getcwd()
        selected_dir = QFileDialog.getExistingDirectory(self, "Select Project Root Folder", current_dir)
        if selected_dir:
            self.uv_project_folder_edit.setText(selected_dir)
            self._refresh_uv_info()
            self.save_current_settings()

    def _browse_pyproject_file(self):
        current_dir = self._get_uv_project_folder() or os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select pyproject.toml File", current_dir, "TOML Files (pyproject.toml)"
        )
        if file_path:
            parent_dir = os.path.dirname(file_path)
            self.uv_project_folder_edit.setText(parent_dir)
            self._refresh_uv_info()
            self.save_current_settings()

    def _browse_script_file(self):
        """Open a file dialog to select a Python script and set it in the run line edit."""
        current_dir = self._get_uv_project_folder() or os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Python Script", current_dir, "Python Files (*.py)"
        )
        if file_path:
            # Store relative path if possible, otherwise absolute
            rel_path = os.path.relpath(file_path, self._get_uv_project_folder())
            if not rel_path.startswith(".."):
                self.uv_run_script_edit.setText(rel_path)
            else:
                self.uv_run_script_edit.setText(file_path)

    # ------------------------------------------------------------------
    # UV command handlers
    # ------------------------------------------------------------------
    def _uv_init_project(self):
        folder = self._get_uv_project_folder()
        if not folder:
            return
        name = self.uv_init_name_edit.text().strip()
        args = ["init"]
        if name:
            args.append(name)
        reply = QMessageBox.question(
            self, "Confirm Initialization",
            f"Initialize a new UV project in:\n{folder}\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._run_uv_command(args, "uv init", folder=folder)
            self._schedule_refresh(2000)

    def _uv_set_python_version(self):
        folder = self._get_uv_project_folder()
        if not folder:
            return
        version = self.uv_py_version_edit.text().strip()
        if not version:
            pyver_file = os.path.join(folder, ".python-version")
            if os.path.exists(pyver_file):
                try:
                    os.remove(pyver_file)
                    QMessageBox.information(self, "Python Version", "Python version pin removed.")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not remove .python-version: {e}")
            else:
                QMessageBox.information(self, "Python Version", "No version pin to remove.")
            self._refresh_uv_info()
            return
        self._run_uv_command(["python", "pin", version], "uv python pin", folder=folder)
        self._schedule_refresh(1500)

    def _uv_sync_python_version_from_env(self):
        """Detect Python version from the current environment and pin it."""
        folder = self._get_uv_project_folder()
        if not folder:
            return

        try:
            result = subprocess.run(
                ["uv", "run", "python", "--version"],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
            )
            if result.returncode == 0 and result.stdout:
                version_line = result.stdout.strip()
                match = re.search(r"(\d+\.\d+)", version_line)
                if match:
                    detected_version = match.group(1)
                    self.uv_py_version_edit.setText(detected_version)
                    self._run_uv_command(["python", "pin", detected_version], "uv python pin", folder=folder)
                    self._schedule_refresh(1500)
                else:
                    QMessageBox.warning(self, "Version Detection", f"Could not parse version from: {version_line}")
            else:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                QMessageBox.warning(self, "Version Detection",
                                    f"Failed to get Python version from environment.\n{error_msg}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to run uv run python --version: {e}")

    def _uv_add_dependency(self):
        packages = self.uv_add_name_edit.text().strip().split()
        if not packages:
            QMessageBox.warning(self, "Missing Packages", "Please enter at least one package name.")
            return
        version = self.uv_add_version_edit.text().strip()
        if version:
            packages = [f"{p}{version}" for p in packages]
        args = ["add"]
        if self.uv_add_dev_cb.isChecked():
            args.append("--dev")
        args.extend(packages)
        self._run_uv_command(args, "uv add")
        self.uv_add_name_edit.clear()
        self.uv_add_version_edit.clear()
        self._schedule_refresh()

    def _uv_remove_dependency(self):
        packages = self.uv_remove_edit.text().strip().split()
        if not packages:
            QMessageBox.warning(self, "Missing Packages", "Please enter at least one package name.")
            return
        self._run_uv_command(["remove"] + packages, "uv remove")
        self.uv_remove_edit.clear()
        self._schedule_refresh()

    def _uv_upgrade_dependency(self):
        pkg = self.uv_upgrade_edit.text().strip()
        if not pkg:
            QMessageBox.warning(self, "Missing Package", "Please enter a package name to upgrade.")
            return
        self._run_uv_command(["add", "--upgrade", pkg], "uv upgrade")
        self.uv_upgrade_edit.clear()
        self._schedule_refresh()

    def _uv_lock(self):
        self._run_uv_command(["lock"], "uv lock")

    def _uv_sync(self):
        self._run_uv_command(["sync"], "uv sync")

    def _uv_run_script(self):
        script = self.uv_run_script_edit.text().strip()
        if not script:
            QMessageBox.warning(self, "Missing Script", "Please enter a script or main.py to run.")
            return
        self._run_uv_command(["run", script], "uv run", interactive=True)

    def _uv_build(self):
        args = ["build"]
        typ = self.uv_build_type.currentText()
        if "Source only" in typ:
            args.append("--sdist")
        elif "Wheel only" in typ:
            args.append("--wheel")
        out_dir = self.uv_build_output_dir.text().strip()
        if out_dir:
            args.extend(["--out-dir", out_dir])
        self._run_uv_command(args, "uv build")

    def _uv_publish(self):
        folder = self._get_uv_project_folder()
        if not folder:
            return
        args = ["publish"]
        index_text = self.uv_publish_index_combo.currentText()
        custom_url = self.uv_publish_custom_index_edit.text().strip()

        if index_text == "TestPyPI":
            args.extend(["--publish-url", "https://test.pypi.org/legacy/"])
        elif index_text == "Custom Index":
            if not custom_url:
                QMessageBox.warning(self, "Missing URL", "Please enter a custom publish URL.")
                return
            args.extend(["--publish-url", custom_url])

        token = self.uv_publish_token_edit.text().strip()
        if token:
            args.extend(["--token", token])

        msg = f"Publish to {index_text}?"
        if index_text == "Custom Index" and custom_url:
            msg += f"\n(URL: {custom_url})"
        if QMessageBox.question(self, "Confirm Publish", msg,
                               QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._run_uv_command(args, "uv publish", folder=folder)

    def _uv_export_requirements(self):
        """Export dependencies from uv.lock to requirements.txt (standard pip format)."""
        folder = self._get_uv_project_folder()
        if not folder:
            QMessageBox.warning(self, "No Project Folder", "Please select a valid project folder first.")
            return

        requirements_path = os.path.join(folder, "requirements.txt")
        try:
            result = subprocess.run(
                ["uv", "export", "--format", "requirements-txt"],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
            )
            if result.returncode == 0 and result.stdout:
                with open(requirements_path, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                QMessageBox.information(self, "Export Successful",
                                        f"requirements.txt has been created at:\n{requirements_path}")
            else:
                error = result.stderr.strip() if result.stderr else "Unknown error"
                QMessageBox.warning(self, "Export Failed", f"uv export failed:\n{error}")
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Timeout", "uv export took too long and was cancelled.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to run uv export: {e}")

    # ------------------------------------------------------------------
    # Auto‑detect dependencies (AST + PyPI + dev detection)
    # ------------------------------------------------------------------
    def _auto_detect_and_sync_dependencies(self):
        """Launch the scanner thread, show progress, then the dialog, and finally apply selected updates."""
        project_folder = self._get_uv_project_folder()
        if not project_folder:
            QMessageBox.warning(self, "No Project Folder", "Please select a valid UV project folder first.")
            return

        # Get Python interpreter from the workspace environment (if available)
        python_exe = None
        if hasattr(self, 'get_selected_env_data'):
            env_data = self.get_selected_env_data()
            if env_data:
                if env_data.get('type') == 'conda':
                    # For conda, we need the actual python inside the environment
                    # Build path from environment path
                    env_path = env_data.get('path')
                    if env_path:
                        if os.name == 'nt':
                            python_exe = os.path.join(env_path, 'python.exe')
                        else:
                            python_exe = os.path.join(env_path, 'bin', 'python')
                elif env_data.get('type') == 'venv':
                    env_path = env_data.get('path')
                    if env_path:
                        if os.name == 'nt':
                            python_exe = os.path.join(env_path, 'Scripts', 'python.exe')
                        else:
                            python_exe = os.path.join(env_path, 'bin', 'python')
                # If the built path doesn't exist, fallback to looking for .venv

        # Fallback: try to find .venv in project folder
        if not python_exe or not os.path.isfile(python_exe):
            venv_python = os.path.join(project_folder, ".venv", "Scripts", "python.exe") if os.name == 'nt' else os.path.join(project_folder, ".venv", "bin", "python")
            if os.path.isfile(venv_python):
                python_exe = venv_python
            else:
                # Last resort: use system python (may not reflect project env)
                python_exe = sys.executable
                QMessageBox.warning(self, "Python Interpreter",
                                    "Could not locate a project‑specific Python interpreter.\n"
                                    "Will use the system Python for version queries – results may be inaccurate.\n"
                                    "Please sync the environment or select one in the Workspace dock.")

        # Progress dialog
        progress = QProgressDialog("Starting dependency scan...", "Cancel", 0, 0, self)
        progress.setWindowTitle("Scanning Imports")
        progress.setModal(True)
        progress.setCancelButton(None)
        progress.show()

        detect_dev = self.dev_detect_checkbox.isChecked()
        self.scanner_thread = DependencyScannerThread(project_folder, python_exe, detect_dev)
        self.scanner_thread.progress.connect(progress.setLabelText)
        self.scanner_thread.finished.connect(lambda result: self._on_scan_finished(result, progress))
        self.scanner_thread.start()

    def _on_scan_finished(self, result, progress_dialog):
        progress_dialog.close()
        if not result:
            QMessageBox.information(self, "No Imports", "No third‑party imports were detected in the project files.")
            return

        dialog = DependencyUpdateDialog(result, self)
        if dialog.exec() == QDialog.Accepted:
            selected = dialog.get_selected()
            if not selected:
                return

            for pkg_name, constraint_choice, is_dev in selected:
                self._add_or_update_dependency(pkg_name, constraint_choice, result.get(pkg_name, {}), is_dev)
            self._schedule_refresh(1500)

    def _add_or_update_dependency(self, pkg_name, constraint_choice, info, is_dev=False):
        """Run uv add with appropriate version specifier and --dev if needed."""
        installed = info.get('installed')
        latest = info.get('latest')

        # Build the uv add command base
        base_cmd = ["add"]
        if is_dev:
            base_cmd.append("--dev")

        if constraint_choice == "Keep as is (no change)":
            if not installed:
                self._run_uv_command(base_cmd + [pkg_name], f"add {pkg_name}" + (" (dev)" if is_dev else ""))
            return
        elif constraint_choice == ">= latest" and latest:
            spec = f"{pkg_name}>={latest}"
        elif constraint_choice == "== latest" and latest:
            spec = f"{pkg_name}=={latest}"
        elif constraint_choice == "Keep existing constraint (if any)":
            if not installed:
                self._run_uv_command(base_cmd + [pkg_name], f"add {pkg_name}" + (" (dev)" if is_dev else ""))
            return
        else:
            spec = pkg_name

        self._run_uv_command(base_cmd + [spec], f"add {spec}" + (" (dev)" if is_dev else ""))

    # ------------------------------------------------------------------
    # Settings Persistence
    # ------------------------------------------------------------------
    def _load_uv_settings(self):
        if not hasattr(self, "settings") or self.settings is None:
            return

        if hasattr(self, "uv_publish_token_edit"):
            self.uv_publish_token_edit.setText(self.settings.get("uv_publish_token", ""))

        idx = self.settings.get("uv_publish_index", "PyPI (official)")
        if hasattr(self, "uv_publish_index_combo"):
            cidx = self.uv_publish_index_combo.findText(idx)
            if cidx >= 0:
                self.uv_publish_index_combo.setCurrentIndex(cidx)
            self._on_publish_index_changed(idx)

        if hasattr(self, "uv_publish_custom_index_edit"):
            self.uv_publish_custom_index_edit.setText(self.settings.get("uv_publish_custom_url", ""))

        build_type_idx = int(self.settings.get("uv_build_type_index", 0))
        if hasattr(self, "uv_build_type") and 0 <= build_type_idx < self.uv_build_type.count():
            self.uv_build_type.setCurrentIndex(build_type_idx)

        if hasattr(self, "uv_build_output_dir"):
            self.uv_build_output_dir.setText(self.settings.get("uv_build_output_dir", ""))

        saved_folder = self.settings.get("uv_project_folder", "")
        if saved_folder and hasattr(self, "uv_project_folder_edit"):
            self.uv_project_folder_edit.setText(saved_folder)

        # Load dev‑detect checkbox state
        if hasattr(self, "dev_detect_checkbox"):
            self.dev_detect_checkbox.setChecked(self.settings.get("uv_dev_detect_enabled", False))

    def _save_uv_settings(self):
        if not hasattr(self, "settings") or self.settings is None:
            return

        if hasattr(self, "uv_publish_token_edit"):
            self.settings.set("uv_publish_token", self.uv_publish_token_edit.text().strip())
        if hasattr(self, "uv_publish_index_combo"):
            self.settings.set("uv_publish_index", self.uv_publish_index_combo.currentText())
        if hasattr(self, "uv_publish_custom_index_edit"):
            self.settings.set("uv_publish_custom_url", self.uv_publish_custom_index_edit.text().strip())
        if hasattr(self, "uv_build_type"):
            self.settings.set("uv_build_type_index", self.uv_build_type.currentIndex())
        if hasattr(self, "uv_build_output_dir"):
            self.settings.set("uv_build_output_dir", self.uv_build_output_dir.text().strip())
        if hasattr(self, "uv_project_folder_edit"):
            self.settings.set("uv_project_folder", self.uv_project_folder_edit.text().strip())
        if hasattr(self, "dev_detect_checkbox"):
            self.settings.set("uv_dev_detect_enabled", self.dev_detect_checkbox.isChecked())