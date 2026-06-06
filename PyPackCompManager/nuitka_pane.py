import os
import sys
import json
from PySide6.QtWidgets import (QDockWidget, QScrollArea, QWidget, QVBoxLayout,
                               QHBoxLayout, QFormLayout, QTabWidget,
                               QGroupBox, QLineEdit, QPushButton,
                               QComboBox, QCheckBox, QLabel, QPlainTextEdit,
                               QFileDialog, QMessageBox, QSpinBox)
from PySide6.QtCore import Qt

class NuitkaMixin:
    """Manages the Nuitka compilation commands, settings, and config generation."""

    def _build_nuitka_dock(self):
        nuitka_dock = QDockWidget("Nuitka Compiler", self)
        nuitka_dock.setObjectName("nuitkaDock")   # For restoreState()
        nuitka_dock.setMinimumSize(400, 450)
        nuitka_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        nuitka_dock.setFeatures(QDockWidget.DockWidgetMovable)

        nuitka_scroll = QScrollArea()
        nuitka_scroll.setWidgetResizable(True)
        nuitka_scroll.setFrameShape(QScrollArea.NoFrame)
        nuitka_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        nuitka_widget = QWidget()
        nuitka_layout = QVBoxLayout(nuitka_widget)

        # ---- Tab Widget for Compilation and Config ----
        nuitka_tabs = QTabWidget()

        # ==========================================
        # ---------- Tab 1: Compile / Run ----------
        # ==========================================
        run_tab = QWidget()
        run_layout = QVBoxLayout(run_tab)

        # --- General Paths Group (with selectors) ---
        paths_group = QGroupBox("Paths & Targets")
        paths_layout = QFormLayout(paths_group)

        # Entry script with browse button
        self.nuitka_entry_edit = QLineEdit()
        self.nuitka_entry_edit.setPlaceholderText("main.py")
        self.nuitka_entry_edit.setToolTip("The main entry point script to compile.")
        entry_layout = QHBoxLayout()
        entry_layout.addWidget(self.nuitka_entry_edit)
        entry_browse_btn = QPushButton("📄")
        entry_browse_btn.setToolTip("Browse for Python script")
        entry_browse_btn.clicked.connect(self._browse_entry_script)
        self._style_square_icon_button(entry_browse_btn)
        entry_layout.addWidget(entry_browse_btn)
        paths_layout.addRow("Entry Script:", entry_layout)

        # Output directory with browse button
        self.nuitka_output_edit = QLineEdit()
        self.nuitka_output_edit.setPlaceholderText("build_out")
        self.nuitka_output_edit.setToolTip("Directory where the compiled files will be placed (--output-dir).")
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.nuitka_output_edit)
        out_browse_btn = QPushButton("📂")
        out_browse_btn.setToolTip("Select output directory")
        out_browse_btn.clicked.connect(self._browse_output_dir)
        self._style_square_icon_button(out_browse_btn)
        out_layout.addWidget(out_browse_btn)
        paths_layout.addRow("Output Dir:", out_layout)

        run_layout.addWidget(paths_group)

        # --- Build Modes Group ---
        modes_group = QGroupBox("Build Modes")
        modes_layout = QVBoxLayout(modes_group)

        self.nuitka_standalone_cb = QCheckBox("--standalone")
        self.nuitka_standalone_cb.setToolTip("Create a standalone folder containing the executable and all dependencies.")
        self.nuitka_onefile_cb = QCheckBox("--onefile")
        self.nuitka_onefile_cb.setToolTip("Create a single executable file (implies --standalone).")
        self.nuitka_disable_console_cb = QCheckBox("--disable-console")
        self.nuitka_disable_console_cb.setToolTip("Hide the console window (Useful for GUI apps on Windows).")

        modes_layout.addWidget(self.nuitka_standalone_cb)
        modes_layout.addWidget(self.nuitka_onefile_cb)
        modes_layout.addWidget(self.nuitka_disable_console_cb)

        run_layout.addWidget(modes_group)

        # --- Dependencies & Plugins Group ---
        deps_group = QGroupBox("Data & Plugins")
        deps_layout = QFormLayout(deps_group)

        self.nuitka_include_data_edit = QLineEdit()
        self.nuitka_include_data_edit.setPlaceholderText("src_dir=dest_dir")
        self.nuitka_include_data_edit.setToolTip("Include data directories (--include-data-dir). Separate multiple with spaces.")
        deps_layout.addRow("Include Data:", self.nuitka_include_data_edit)

        self.nuitka_enable_plugin_edit = QLineEdit()
        self.nuitka_enable_plugin_edit.setPlaceholderText("pyside6, anti-bloat")
        self.nuitka_enable_plugin_edit.setToolTip("Comma separated list of plugins to enable (--enable-plugin=...).")
        deps_layout.addRow("Plugins:", self.nuitka_enable_plugin_edit)

        run_layout.addWidget(deps_group)

        # --- Icon & Advanced Options ---
        advanced_group = QGroupBox("Icon & Advanced Options")
        advanced_layout = QFormLayout(advanced_group)

        # Icon file (Windows .ico, macOS .icns)
        self.nuitka_icon_edit = QLineEdit()
        self.nuitka_icon_edit.setPlaceholderText("app.ico (Windows) or app.icns (macOS)")
        self.nuitka_icon_edit.setToolTip("Icon file for the executable. On Windows: .ico, on macOS: .icns")
        icon_layout = QHBoxLayout()
        icon_layout.addWidget(self.nuitka_icon_edit)
        icon_browse_btn = QPushButton("📄")
        icon_browse_btn.setToolTip("Select icon file")
        icon_browse_btn.clicked.connect(self._browse_icon_file)
        self._style_square_icon_button(icon_browse_btn)
        icon_layout.addWidget(icon_browse_btn)
        advanced_layout.addRow("Icon File:", icon_layout)

        # Include packages
        self.nuitka_include_packages_edit = QLineEdit()
        self.nuitka_include_packages_edit.setPlaceholderText("requests pandas")
        self.nuitka_include_packages_edit.setToolTip("Additional packages to include (space separated). Use --include-package.")
        advanced_layout.addRow("Include Packages:", self.nuitka_include_packages_edit)

        # Include modules
        self.nuitka_include_modules_edit = QLineEdit()
        self.nuitka_include_modules_edit.setPlaceholderText("module1 module2")
        self.nuitka_include_modules_edit.setToolTip("Additional modules to include (space separated). Use --include-module.")
        advanced_layout.addRow("Include Modules:", self.nuitka_include_modules_edit)

        # Windows UAC admin
        self.nuitka_uac_admin_cb = QCheckBox("--windows-uac-admin")
        self.nuitka_uac_admin_cb.setToolTip("Request administrator privileges on Windows (UAC).")
        advanced_layout.addRow("Admin Rights (Windows):", self.nuitka_uac_admin_cb)

        # Parallel jobs
        self.nuitka_jobs_spin = QSpinBox()
        self.nuitka_jobs_spin.setRange(1, 32)
        self.nuitka_jobs_spin.setValue(0)  # 0 means auto-detected by Nuitka (no --jobs)
        self.nuitka_jobs_spin.setSpecialValueText("Auto")
        self.nuitka_jobs_spin.setToolTip("Number of parallel compile jobs (--jobs). Auto uses all cores.")
        advanced_layout.addRow("Parallel Jobs:", self.nuitka_jobs_spin)

        # ----- NEW OPTIONS -----
        self.nuitka_auto_plugin_pyside6_cb = QCheckBox("Auto-enable PySide6 plugin (--enable-plugin=pyside6)")
        self.nuitka_auto_plugin_pyside6_cb.setToolTip(
            "Automatically add the PySide6 plugin for standalone support and Qt plugins."
        )
        self.nuitka_auto_plugin_pyside6_cb.setChecked(True)
        advanced_layout.addRow("", self.nuitka_auto_plugin_pyside6_cb)

        self.nuitka_no_dependency_walker_cb = QCheckBox("Skip Dependency Walker (--no-dependency-walker)")
        self.nuitka_no_dependency_walker_cb.setToolTip(
            "Do not download/use Dependency Walker; avoids interactive prompt."
        )
        self.nuitka_no_dependency_walker_cb.setChecked(True)
        advanced_layout.addRow("", self.nuitka_no_dependency_walker_cb)

        run_layout.addWidget(advanced_group)

        # --- Extra Args & Run ---
        extra_layout = QHBoxLayout()
        extra_layout.addWidget(QLabel("Extra args:"))
        self.nuitka_extra_edit = QLineEdit()
        self.nuitka_extra_edit.setToolTip("Any additional arguments to pass to Nuitka.")
        extra_layout.addWidget(self.nuitka_extra_edit)
        run_layout.addLayout(extra_layout)

        self.run_nuitka_btn = QPushButton("🚀 Run Nuitka Compiler")
        self._setup_button(self.run_nuitka_btn, "Start compiling the Python script using Nuitka.")
        self._style_critical_button(self.run_nuitka_btn, "#2E7D32", "#1B5E20")
        self.run_nuitka_btn.clicked.connect(self.run_nuitka)
        run_layout.addWidget(self.run_nuitka_btn)

        run_layout.addStretch()

        # ============================================
        # ---------- Tab 2: Config / Settings ----------
        # ============================================
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)

        preview_label = QLabel("<b>Command Preview:</b>")
        config_layout.addWidget(preview_label)

        self.nuitka_cmd_preview = QPlainTextEdit()
        self.nuitka_cmd_preview.setReadOnly(True)
        self.nuitka_cmd_preview.setStyleSheet("font-family: monospace; background-color: #1e1e1e; color: #d4d4d4;")
        config_layout.addWidget(self.nuitka_cmd_preview)

        # Export settings (JSON) button
        self.export_settings_btn = QPushButton("💾 Export Nuitka Settings (.json)")
        self._setup_button(self.export_settings_btn, "Save all current Nuitka compiler settings to a JSON file.")
        self.export_settings_btn.clicked.connect(self.export_nuitka_settings)
        config_layout.addWidget(self.export_settings_btn)

        # Load settings button
        self.load_settings_btn = QPushButton("📄 Load Nuitka Settings")
        self._setup_button(self.load_settings_btn, "Load a Nuitka settings JSON file.")
        self.load_settings_btn.clicked.connect(self.load_nuitka_settings)
        config_layout.addWidget(self.load_settings_btn)

        nuitka_tabs.addTab(run_tab, "Compile")
        nuitka_tabs.addTab(config_tab, "Config / Settings")
        nuitka_tabs.currentChanged.connect(self._update_nuitka_preview)

        # Connect changes to live update preview
        self._connect_nuitka_signals()

        nuitka_layout.addWidget(nuitka_tabs)

        nuitka_scroll.setWidget(nuitka_widget)
        nuitka_dock.setWidget(nuitka_scroll)
        return nuitka_dock

    # ----- Browse helper methods -----
    def _browse_entry_script(self):
        start_dir = self.folder_edit.text().strip() if hasattr(self, 'folder_edit') else ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Entry Script", start_dir, "Python Files (*.py);;All Files (*)")
        if file_path:
            self.nuitka_entry_edit.setText(file_path)

    def _browse_output_dir(self):
        start_dir = self.folder_edit.text().strip() if hasattr(self, 'folder_edit') else ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", start_dir)
        if dir_path:
            self.nuitka_output_edit.setText(dir_path)

    def _browse_icon_file(self):
        start_dir = self.folder_edit.text().strip() if hasattr(self, 'folder_edit') else ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        filter_str = "Icon Files (*.ico *.icns);;All Files (*)" if sys.platform == 'win32' else "Icon Files (*.icns *.ico);;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Icon File", start_dir, filter_str)
        if file_path:
            self.nuitka_icon_edit.setText(file_path)

    def _connect_nuitka_signals(self):
        """Bind form changes to update the live preview."""
        edits = [self.nuitka_entry_edit, self.nuitka_output_edit, self.nuitka_include_data_edit,
                 self.nuitka_enable_plugin_edit, self.nuitka_extra_edit, self.nuitka_icon_edit,
                 self.nuitka_include_packages_edit, self.nuitka_include_modules_edit]
        for edit in edits:
            edit.textChanged.connect(self._update_nuitka_preview)

        cbs = [self.nuitka_standalone_cb, self.nuitka_onefile_cb, self.nuitka_disable_console_cb,
               self.nuitka_uac_admin_cb, self.nuitka_auto_plugin_pyside6_cb,
               self.nuitka_no_dependency_walker_cb]
        for cb in cbs:
            cb.clicked.connect(self._update_nuitka_preview)

        self.nuitka_jobs_spin.valueChanged.connect(self._update_nuitka_preview)

    def _load_nuitka_settings(self):
        self.nuitka_entry_edit.setText(self.settings.get("nuitka_entry", "main.py"))
        self.nuitka_output_edit.setText(self.settings.get("nuitka_output", ""))
        self.nuitka_standalone_cb.setChecked(self.settings.get("nuitka_standalone", False))
        self.nuitka_onefile_cb.setChecked(self.settings.get("nuitka_onefile", False))
        self.nuitka_disable_console_cb.setChecked(self.settings.get("nuitka_disable_console", False))
        self.nuitka_include_data_edit.setText(self.settings.get("nuitka_include_data", ""))
        self.nuitka_enable_plugin_edit.setText(self.settings.get("nuitka_enable_plugin", ""))
        self.nuitka_extra_edit.setText(self.settings.get("nuitka_extra", ""))
        self.nuitka_icon_edit.setText(self.settings.get("nuitka_icon", ""))
        self.nuitka_include_packages_edit.setText(self.settings.get("nuitka_include_packages", ""))
        self.nuitka_include_modules_edit.setText(self.settings.get("nuitka_include_modules", ""))
        self.nuitka_uac_admin_cb.setChecked(self.settings.get("nuitka_uac_admin", False))
        jobs = self.settings.get("nuitka_jobs", 0)
        self.nuitka_jobs_spin.setValue(jobs if jobs is not None else 0)
        # New settings
        self.nuitka_auto_plugin_pyside6_cb.setChecked(self.settings.get("nuitka_auto_plugin_pyside6", True))
        self.nuitka_no_dependency_walker_cb.setChecked(self.settings.get("nuitka_no_dependency_walker", True))
        self._update_nuitka_preview()

    def _save_nuitka_settings(self):
        self.settings.set("nuitka_entry", self.nuitka_entry_edit.text().strip())
        self.settings.set("nuitka_output", self.nuitka_output_edit.text().strip())
        self.settings.set("nuitka_standalone", self.nuitka_standalone_cb.isChecked())
        self.settings.set("nuitka_onefile", self.nuitka_onefile_cb.isChecked())
        self.settings.set("nuitka_disable_console", self.nuitka_disable_console_cb.isChecked())
        self.settings.set("nuitka_include_data", self.nuitka_include_data_edit.text().strip())
        self.settings.set("nuitka_enable_plugin", self.nuitka_enable_plugin_edit.text().strip())
        self.settings.set("nuitka_extra", self.nuitka_extra_edit.text().strip())
        self.settings.set("nuitka_icon", self.nuitka_icon_edit.text().strip())
        self.settings.set("nuitka_include_packages", self.nuitka_include_packages_edit.text().strip())
        self.settings.set("nuitka_include_modules", self.nuitka_include_modules_edit.text().strip())
        self.settings.set("nuitka_uac_admin", self.nuitka_uac_admin_cb.isChecked())
        self.settings.set("nuitka_jobs", self.nuitka_jobs_spin.value())
        self.settings.set("nuitka_auto_plugin_pyside6", self.nuitka_auto_plugin_pyside6_cb.isChecked())
        self.settings.set("nuitka_no_dependency_walker", self.nuitka_no_dependency_walker_cb.isChecked())

    def _generate_nuitka_args(self):
        """Generates the list of arguments for the nuitka command based on UI state."""
        args = ["-m", "nuitka"]

        if self.nuitka_standalone_cb.isChecked():
            args.append("--standalone")
        if self.nuitka_onefile_cb.isChecked():
            args.append("--onefile")
        if self.nuitka_disable_console_cb.isChecked():
            args.append("--disable-console")

        out_dir = self.nuitka_output_edit.text().strip()
        if out_dir:
            args.append(f"--output-dir={out_dir}")

        # User-specified plugins (manual)
        plugins = self.nuitka_enable_plugin_edit.text().strip()
        if plugins:
            cleaned_plugins = ",".join([p.strip() for p in plugins.split(",") if p.strip()])
            args.append(f"--enable-plugin={cleaned_plugins}")

        # Auto-enable PySide6 plugin
        if self.nuitka_auto_plugin_pyside6_cb.isChecked():
            # Avoid duplicate if user already typed it
            if "pyside6" not in args:
                args.append("--enable-plugin=pyside6")

        # Skip Dependency Walker
        if self.nuitka_no_dependency_walker_cb.isChecked():
            args.append("--no-dependency-walker")

        data_dirs = self.nuitka_include_data_edit.text().strip()
        if data_dirs:
            for d in data_dirs.split():
                args.append(f"--include-data-dir={d}")

        # Advanced options
        icon_path = self.nuitka_icon_edit.text().strip()
        if icon_path:
            if sys.platform == 'win32':
                args.append(f"--windows-icon-from-ico={icon_path}")
            elif sys.platform == 'darwin':
                args.append(f"--macos-app-icon={icon_path}")
            # Linux: no standard icon argument, skip

        include_packages = self.nuitka_include_packages_edit.text().strip()
        if include_packages:
            for pkg in include_packages.split():
                args.append(f"--include-package={pkg}")

        include_modules = self.nuitka_include_modules_edit.text().strip()
        if include_modules:
            for mod in include_modules.split():
                args.append(f"--include-module={mod}")

        if self.nuitka_uac_admin_cb.isChecked() and sys.platform == 'win32':
            args.append("--windows-uac-admin")

        jobs = self.nuitka_jobs_spin.value()
        if jobs > 0:
            args.append(f"--jobs={jobs}")

        extra = self.nuitka_extra_edit.text().strip()
        if extra:
            args.extend(extra.split())

        entry = self.nuitka_entry_edit.text().strip()
        if entry:
            args.append(entry)

        return args

    def _update_nuitka_preview(self):
        """Updates the read-only preview of the command."""
        args = self._generate_nuitka_args()
        formatted_cmd = "python \\\n    " + " \\\n    ".join(args)
        self.nuitka_cmd_preview.setPlainText(formatted_cmd)

    def run_nuitka(self):
        self.save_current_settings()
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            QMessageBox.warning(self, "Invalid Workspace", "Please select a valid project directory first.")
            return

        entry_script = self.nuitka_entry_edit.text().strip()
        if not entry_script:
            QMessageBox.warning(self, "Missing Entry Script", "Please define a target script (e.g., main.py).")
            return

        args = self._generate_nuitka_args()
        program, resolved_args, env_data = self._build_env_command("python", args)
        if program:
            self.run_command(program, resolved_args, project_folder, "Nuitka Compilation", env_data)

    def export_nuitka_settings(self):
        """Save current Nuitka settings to a JSON file."""
        self.save_current_settings()
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            QMessageBox.warning(self, "Invalid Workspace", "Please select a valid project directory first.")
            return

        default_path = os.path.join(project_folder, "nuitka_settings.json")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Nuitka Settings", default_path, "JSON Files (*.json);;All Files (*)"
        )

        if save_path:
            settings_data = {
                "entry": self.nuitka_entry_edit.text().strip(),
                "output_dir": self.nuitka_output_edit.text().strip(),
                "standalone": self.nuitka_standalone_cb.isChecked(),
                "onefile": self.nuitka_onefile_cb.isChecked(),
                "disable_console": self.nuitka_disable_console_cb.isChecked(),
                "include_data": self.nuitka_include_data_edit.text().strip(),
                "enable_plugin": self.nuitka_enable_plugin_edit.text().strip(),
                "extra_args": self.nuitka_extra_edit.text().strip(),
                "icon": self.nuitka_icon_edit.text().strip(),
                "include_packages": self.nuitka_include_packages_edit.text().strip(),
                "include_modules": self.nuitka_include_modules_edit.text().strip(),
                "uac_admin": self.nuitka_uac_admin_cb.isChecked(),
                "jobs": self.nuitka_jobs_spin.value(),
                "auto_plugin_pyside6": self.nuitka_auto_plugin_pyside6_cb.isChecked(),
                "no_dependency_walker": self.nuitka_no_dependency_walker_cb.isChecked()
            }
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    json.dump(settings_data, f, indent=4)
                QMessageBox.information(self, "Success", f"Nuitka settings saved to:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to write settings file:\n{str(e)}")

    def load_nuitka_settings(self):
        """Load Nuitka settings from a JSON file and update the UI."""
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            QMessageBox.warning(self, "Invalid Workspace", "Please select a valid project directory first.")
            return

        load_path, _ = QFileDialog.getOpenFileName(
            self, "Load Nuitka Settings", project_folder, "JSON Files (*.json);;All Files (*)"
        )
        if not load_path:
            return

        try:
            with open(load_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.nuitka_entry_edit.setText(data.get("entry", ""))
            self.nuitka_output_edit.setText(data.get("output_dir", ""))
            self.nuitka_standalone_cb.setChecked(data.get("standalone", False))
            self.nuitka_onefile_cb.setChecked(data.get("onefile", False))
            self.nuitka_disable_console_cb.setChecked(data.get("disable_console", False))
            self.nuitka_include_data_edit.setText(data.get("include_data", ""))
            self.nuitka_enable_plugin_edit.setText(data.get("enable_plugin", ""))
            self.nuitka_extra_edit.setText(data.get("extra_args", ""))
            self.nuitka_icon_edit.setText(data.get("icon", ""))
            self.nuitka_include_packages_edit.setText(data.get("include_packages", ""))
            self.nuitka_include_modules_edit.setText(data.get("include_modules", ""))
            self.nuitka_uac_admin_cb.setChecked(data.get("uac_admin", False))
            self.nuitka_jobs_spin.setValue(data.get("jobs", 0))
            self.nuitka_auto_plugin_pyside6_cb.setChecked(data.get("auto_plugin_pyside6", True))
            self.nuitka_no_dependency_walker_cb.setChecked(data.get("no_dependency_walker", True))
            self._update_nuitka_preview()
            QMessageBox.information(self, "Success", f"Settings loaded from:\n{load_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load settings:\n{str(e)}")