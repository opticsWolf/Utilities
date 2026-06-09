import os
import sys
import json
from PySide6.QtWidgets import (
    QDockWidget,
    QScrollArea,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QRadioButton,  # added for console mode selection
    QLabel,
    QPlainTextEdit,
    QFileDialog,
    QMessageBox,
    QSpinBox,
    QListWidget,
    QInputDialog,
)
from PySide6.QtCore import Qt
from core_ui_helpers import CollapsibleGroupBox


class NuitkaMixin:
    """Manages the Nuitka compilation commands, settings, and config generation."""

    def _build_nuitka_dock(self):
        nuitka_dock = QDockWidget("Nuitka Compiler", self)
        nuitka_dock.setObjectName("nuitkaDock")
        nuitka_dock.setMinimumSize(400, 450)
        nuitka_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        nuitka_dock.setFeatures(QDockWidget.DockWidgetMovable)

        nuitka_scroll = QScrollArea()
        nuitka_scroll.setWidgetResizable(True)
        nuitka_scroll.setFrameShape(QScrollArea.NoFrame)
        nuitka_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        nuitka_widget = QWidget()
        nuitka_layout = QVBoxLayout(nuitka_widget)

        nuitka_tabs = QTabWidget()

        # ====================== Tab 1: Compile / Run ======================
        run_tab = QWidget()
        run_layout = QVBoxLayout(run_tab)

        # --- Paths & Targets ---
        paths_group = QGroupBox("Paths && Targets")
        paths_layout = QFormLayout(paths_group)

        self.nuitka_entry_edit = QLineEdit()
        self.nuitka_entry_edit.setPlaceholderText("main.py")
        self.nuitka_entry_edit.setToolTip(
            "The main Python script execution starts from. This is the entry point file Nuitka will compile."
        )
        entry_layout = QHBoxLayout()
        entry_layout.addWidget(self.nuitka_entry_edit)
        entry_browse_btn = QPushButton("📄")
        entry_browse_btn.setToolTip(
            "Browse the filesystem to select your main entry Python script."
        )
        entry_browse_btn.clicked.connect(self._browse_entry_script)
        self._style_square_icon_button(entry_browse_btn)
        entry_layout.addWidget(entry_browse_btn)
        paths_layout.addRow("Entry Script:", entry_layout)

        self.nuitka_output_edit = QLineEdit()
        self.nuitka_output_edit.setPlaceholderText("build_out")
        self.nuitka_output_edit.setToolTip(
            "(--output-dir)\nDirectory where Nuitka will store intermediate build C++ files and final compiled binaries."
        )
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.nuitka_output_edit)
        out_browse_btn = QPushButton("📂")
        out_browse_btn.setToolTip(
            "Browse the filesystem to select or create your compilation output directory."
        )
        out_browse_btn.clicked.connect(self._browse_output_dir)
        self._style_square_icon_button(out_browse_btn)
        out_layout.addWidget(out_browse_btn)
        paths_layout.addRow("Output Dir:", out_layout)

        run_layout.addWidget(paths_group)

        # --- Build Modes ---
        modes_group = QGroupBox("Build Modes")
        modes_layout = QVBoxLayout(modes_group)

        self.nuitka_standalone_cb = QCheckBox("--standalone")
        self.nuitka_standalone_cb.setToolTip(
            "Enable standalone mode. This builds an output folder containing the executable along with all required dynamic libraries (.dll/.so/.dylib) so it can run on other machines without a Python installation."
        )

        self.nuitka_onefile_cb = QCheckBox("--onefile")
        self.nuitka_onefile_cb.setToolTip(
            "Enable onefile mode. Packs the standalone distribution into a single executable file. It unpacks itself to a temporary directory at runtime."
        )

        # --- Console Mode Options (new) ---
        self.nuitka_console_cb = QCheckBox("Override Windows Console Mode")
        self.nuitka_console_cb.setToolTip("Enable to explicitly set the Windows console behavior.")

        self.console_radio_layout = QHBoxLayout()
        self.console_radio_layout.setContentsMargins(20, 0, 0, 0)  # indent radio buttons

        self.console_disable_rb = QRadioButton("Disable")
        self.console_disable_rb.setToolTip("Disable the console window (Ideal for GUI apps).")
        self.console_disable_rb.setChecked(True)  # default when enabled

        self.console_force_rb = QRadioButton("Force")
        self.console_force_rb.setToolTip("Force the console window to appear.")

        self.console_attach_rb = QRadioButton("Attach")
        self.console_attach_rb.setToolTip("Attach to an existing console if available.")

        self.console_radio_layout.addWidget(self.console_disable_rb)
        self.console_radio_layout.addWidget(self.console_force_rb)
        self.console_radio_layout.addWidget(self.console_attach_rb)
        self.console_radio_layout.addStretch()

        # Connect checkbox to enable/disable radio buttons
        self.nuitka_console_cb.toggled.connect(
            lambda checked: [
                rb.setEnabled(checked)
                for rb in (
                    self.console_disable_rb,
                    self.console_force_rb,
                    self.console_attach_rb,
                )
            ]
        )
        # Initially disabled because checkbox is off
        self.nuitka_console_cb.setChecked(False)
        for rb in (self.console_disable_rb, self.console_force_rb, self.console_attach_rb):
            rb.setEnabled(False)

        modes_layout.addWidget(self.nuitka_standalone_cb)
        modes_layout.addWidget(self.nuitka_onefile_cb)
        modes_layout.addWidget(self.nuitka_console_cb)
        modes_layout.addLayout(self.console_radio_layout)

        run_layout.addWidget(modes_group)

        # --- Data (collapsible) ---
        self.deps_group = self._create_collapsible_group("Include Data")
        deps_layout = QVBoxLayout(self.deps_group.content_widget)

        # ---- Include Data Directories (--include-data-dir) ----
        data_dir_label = QLabel("Include Directories:")
        data_dir_label.setToolTip(
            "(--include-data-dir=source=destination)\nRecursively copies whole asset folders into your build deployment. Source must be a local folder path, and destination must be a relative path inside the distribution folder."
        )
        deps_layout.addWidget(data_dir_label)

        self.data_dirs_list = QListWidget()
        self.data_dirs_list.setMaximumHeight(100)
        self.data_dirs_list.setToolTip(
            "List of folders to be copied into the final build destination layout."
        )
        deps_layout.addWidget(self.data_dirs_list)

        data_dir_buttons = QHBoxLayout()
        add_dir_folder_btn = QPushButton("📁")
        add_dir_folder_btn.setToolTip(
            "Browse and choose a directory folder to copy completely into the build package."
        )
        add_dir_folder_btn.clicked.connect(self._add_data_dir_folder)

        add_dir_custom_btn = QPushButton("✏️")
        add_dir_custom_btn.setToolTip(
            "Manually type a raw string source=destination entry for folder inclusion rules."
        )
        add_dir_custom_btn.clicked.connect(self._add_data_dir_custom)

        remove_dir_btn = QPushButton("🗑️")
        remove_dir_btn.setToolTip(
            "Remove the currently selected item from the directory inclusion list."
        )
        remove_dir_btn.clicked.connect(
            lambda: self._remove_list_item(self.data_dirs_list)
        )

        for btn in (add_dir_folder_btn, add_dir_custom_btn, remove_dir_btn):
            self._style_square_icon_button(btn)
        data_dir_buttons.addWidget(add_dir_folder_btn)
        data_dir_buttons.addWidget(add_dir_custom_btn)
        data_dir_buttons.addWidget(remove_dir_btn)
        data_dir_buttons.addStretch()
        deps_layout.addLayout(data_dir_buttons)

        self.nuitka_auto_map_dirs_cb = QCheckBox("Auto‑map source folder → destination")
        self.nuitka_auto_map_dirs_cb.setToolTip(
            "When checked, choosing a folder automatically assumes its folder name as the relative destination directory inside the build layout, skipping the manual dialog prompt."
        )
        deps_layout.addWidget(self.nuitka_auto_map_dirs_cb)

        # ---- Include Data Files (--include-data-files) ----
        data_file_label = QLabel("Include Files:")
        data_file_label.setToolTip(
            "(--include-data-files=source=destination)\nCopies individual pattern assets (e.g., config.json, image.png) into your build distribution workspace layout."
        )
        deps_layout.addWidget(data_file_label)

        self.data_files_list = QListWidget()
        self.data_files_list.setMaximumHeight(100)
        self.data_files_list.setToolTip(
            "List of standalone non-python files to be bundled with the final executable package."
        )
        deps_layout.addWidget(self.data_files_list)

        data_file_buttons = QHBoxLayout()
        add_file_btn = QPushButton("📄")
        add_file_btn.setToolTip(
            "Browse and choose an individual file to copy into the build folder."
        )
        add_file_btn.clicked.connect(self._add_data_file)

        add_file_custom_btn = QPushButton("✏️")
        add_file_custom_btn.setToolTip(
            "Manually type a raw pattern entry string source=destination entry for single file inclusion rules."
        )
        add_file_custom_btn.clicked.connect(self._add_data_file_custom)

        remove_file_btn = QPushButton("🗑️")
        remove_file_btn.setToolTip(
            "Remove the currently selected file item from the file inclusion list."
        )
        remove_file_btn.clicked.connect(
            lambda: self._remove_list_item(self.data_files_list)
        )

        for btn in (add_file_btn, add_file_custom_btn, remove_file_btn):
            self._style_square_icon_button(btn)
        data_file_buttons.addWidget(add_file_btn)
        data_file_buttons.addWidget(add_file_custom_btn)
        data_file_buttons.addWidget(remove_file_btn)
        data_file_buttons.addStretch()
        deps_layout.addLayout(data_file_buttons)

        self.nuitka_auto_map_files_cb = QCheckBox("Auto‑map source file → destination")
        self.nuitka_auto_map_files_cb.setToolTip(
            "When checked, choosing a file automatically assumes its exact filename as the destination layout name inside the build distribution layout, skipping manual dialog prompting."
        )
        deps_layout.addWidget(self.nuitka_auto_map_files_cb)

        run_layout.addWidget(self.deps_group)

        # --- Icon & Advanced Options (collapsible) ---
        self.advanced_group = self._create_collapsible_group("Icon && Advanced Options")
        advanced_layout = QFormLayout(self.advanced_group.content_widget)

        self.nuitka_icon_edit = QLineEdit()
        self.nuitka_icon_edit.setPlaceholderText("app.ico / app.icns")
        self.nuitka_icon_edit.setToolTip(
            "Path to application executable icon file. Uses .ico on Windows setups and .icns for macOS apps package bundles."
        )
        icon_layout = QHBoxLayout()
        icon_layout.addWidget(self.nuitka_icon_edit)
        icon_browse_btn = QPushButton("📄")
        icon_browse_btn.setToolTip(
            "Browse filesystem for .ico or .icns branding application icons."
        )
        icon_browse_btn.clicked.connect(self._browse_icon_file)
        self._style_square_icon_button(icon_browse_btn)
        icon_layout.addWidget(icon_browse_btn)
        advanced_layout.addRow("Icon File:", icon_layout)

        # ---- Plugins Textbox (Moved here) ----
        self.nuitka_enable_plugin_edit = QLineEdit()
        self.nuitka_enable_plugin_edit.setPlaceholderText(
            "anti-bloat, numpy, matplotlib"
        )
        self.nuitka_enable_plugin_edit.setToolTip(
            "(--enable-plugin)\n"
            "Activates specialized Nuitka compilation hooks and code-generation recipes "
            "required by complex frameworks (e.g., numpy, anti-bloat, matplotlib) to handle "
            "implicit binary assets, plugins, or post-processing hooks."
        )
        advanced_layout.addRow("Plugins:", self.nuitka_enable_plugin_edit)

        # ---- Include Packages ----
        self.nuitka_include_packages_edit = QLineEdit()
        self.nuitka_include_packages_edit.setPlaceholderText("requests pandas")
        self.nuitka_include_packages_edit.setToolTip(
            "(--include-package)\n"
            "Forces Nuitka to copy and compile an entire Python package directory structure. "
            "Use this when Nuitka's static analysis misses dependencies (e.g., dynamic imports via importlib)."
        )
        advanced_layout.addRow("Include Packages:", self.nuitka_include_packages_edit)

        # ---- Include Modules ----
        self.nuitka_include_modules_edit = QLineEdit()
        self.nuitka_include_modules_edit.setPlaceholderText("module1 module2")
        self.nuitka_include_modules_edit.setToolTip(
            "(--include-module)\n"
            "Forces Nuitka to look up and compile specific single Python modules (.py files) "
            "by their namespace, bypassing static dependency detection."
        )
        advanced_layout.addRow("Include Modules:", self.nuitka_include_modules_edit)

        # ---- Exclude Packages (new) ----
        self.nuitka_exclude_packages_edit = QLineEdit()
        self.nuitka_exclude_packages_edit.setPlaceholderText("package_to_exclude")
        self.nuitka_exclude_packages_edit.setToolTip(
            "(--exclude-package)\nExclude a whole package from being included in the compilation."
        )
        advanced_layout.addRow("Exclude Packages:", self.nuitka_exclude_packages_edit)

        # ---- Exclude Modules (new) ----
        self.nuitka_exclude_modules_edit = QLineEdit()
        self.nuitka_exclude_modules_edit.setPlaceholderText("module_to_exclude")
        self.nuitka_exclude_modules_edit.setToolTip(
            "(--exclude-module)\nExclude a specific module from being included."
        )
        advanced_layout.addRow("Exclude Modules:", self.nuitka_exclude_modules_edit)

        self.nuitka_uac_admin_cb = QCheckBox("--windows-uac-admin")
        self.nuitka_uac_admin_cb.setToolTip(
            "Forces the compiled execution binary to request elevated Windows User Account Control (UAC) administrator privileges upon startup execution (Windows Only)."
        )
        advanced_layout.addRow("Admin Rights (Windows):", self.nuitka_uac_admin_cb)

        self.nuitka_jobs_spin = QSpinBox()
        self.nuitka_jobs_spin.setRange(1, 32)
        self.nuitka_jobs_spin.setValue(0)
        self.nuitka_jobs_spin.setSpecialValueText("Auto")
        self.nuitka_jobs_spin.setToolTip(
            "(--jobs)\nSpecifies the number of concurrent parallel compiler threads/CPU cores to use for compiling C++ files. 'Auto' optimizes resource detection automatically."
        )
        advanced_layout.addRow("Parallel Jobs:", self.nuitka_jobs_spin)

        self.nuitka_auto_plugin_pyside6_cb = QCheckBox("Auto-enable PySide6 plugin")
        self.nuitka_auto_plugin_pyside6_cb.setToolTip(
            "Appends '--enable-plugin=pyside6' automatically to guarantee Qt GUI component hooks function properly without explicit manual text entry declarations."
        )
        self.nuitka_auto_plugin_pyside6_cb.setChecked(True)
        advanced_layout.addRow("", self.nuitka_auto_plugin_pyside6_cb)

        self.nuitka_no_dependency_walker_cb = QCheckBox("Skip Dependency Walker")
        self.nuitka_no_dependency_walker_cb.setToolTip(
            "(--no-dependency-walker)\nSpeeds up build orchestration on Windows machines by skipping deep recursive Dependency Walker scans, using fast internal detection instead."
        )
        self.nuitka_no_dependency_walker_cb.setChecked(True)
        advanced_layout.addRow("", self.nuitka_no_dependency_walker_cb)

        run_layout.addWidget(self.advanced_group)

        # --- Collapsible Additional Flags Group ---
        self.extra_flags_group = self._create_collapsible_group(
            "Additional Nuitka Flags"
        )
        flags_layout = QVBoxLayout(self.extra_flags_group.content_widget)

        self.nuitka_follow_imports_cb = QCheckBox("--follow-imports")
        self.nuitka_follow_imports_cb.setToolTip(
            "Tells Nuitka to step into and trace all linked Python source file imports to compile them completely into C levels."
        )

        self.nuitka_lto_cb = QCheckBox("--lto=auto")
        self.nuitka_lto_cb.setToolTip(
            "Enables Link Time Optimization (LTO) in C++ compilers. Produces faster, smaller final execution binaries but results in noticeably longer compile times."
        )

        self.nuitka_deployment_cb = QCheckBox("--deployment")
        self.nuitka_deployment_cb.setToolTip(
            "Disables diagnostic/safeguard wrappers. Optimizes binaries for production delivery while disabling runtime compilation warnings."
        )

        self.nuitka_low_memory_cb = QCheckBox("--low-memory")
        self.nuitka_low_memory_cb.setToolTip(
            "Instructs the C++ internal compiler to optimize and restrict RAM utilization, avoiding host machine freezing during multi-core compiler tasks."
        )

        self.nuitka_no_pyi_cb = QCheckBox("--no-pyi-file")
        self.nuitka_no_pyi_cb.setToolTip(
            "Tells Nuitka to ignore .pyi interface typing stub file definitions when tracing packages dependencies."
        )

        self.nuitka_experimental_cb = QCheckBox("--experimental")
        self.nuitka_experimental_cb.setToolTip(
            "Activates pre-release features or unstable compilation logic patches embedded within your installed Nuitka core version."
        )

        for cb in (
            self.nuitka_follow_imports_cb,
            self.nuitka_lto_cb,
            self.nuitka_deployment_cb,
            self.nuitka_low_memory_cb,
            self.nuitka_no_pyi_cb,
            self.nuitka_experimental_cb,
        ):
            flags_layout.addWidget(cb)

        run_layout.addWidget(self.extra_flags_group)

        # --- Extra Args & Run Button ---
        extra_layout = QHBoxLayout()
        extra_label = QLabel("Extra args:")
        extra_label.setToolTip(
            "Provide any advanced raw Nuitka CLI parameters not exposed through this graphical pane interface."
        )
        extra_layout.addWidget(extra_label)
        self.nuitka_extra_edit = QLineEdit()
        self.nuitka_extra_edit.setToolTip(
            "Space-separated CLI string parameters (e.g. --plugin-enable=tk-inter --show-scons)."
        )
        extra_layout.addWidget(self.nuitka_extra_edit)
        run_layout.addLayout(extra_layout)

        self.run_nuitka_btn = QPushButton("🚀 Run Nuitka Compiler")
        self._setup_button(
            self.run_nuitka_btn,
            "Start compiling the target project using the selected parameter flags.",
        )
        self._style_critical_button(self.run_nuitka_btn, "#2E7D32", "#1B5E20")
        self.run_nuitka_btn.clicked.connect(self.run_nuitka)
        run_layout.addWidget(self.run_nuitka_btn)
        run_layout.addStretch()

        # ====================== Tab 2: Config / Settings ======================
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)

        preview_label = QLabel("Command Preview:")
        preview_label.setToolTip(
            "Live terminal-formatted output preview of the command string built by your option toggles."
        )
        config_layout.addWidget(preview_label)

        self.nuitka_cmd_preview = QPlainTextEdit()
        self.nuitka_cmd_preview.setReadOnly(True)
        self.nuitka_cmd_preview.setToolTip(
            "Copyable system execution payload display reflecting live GUI parameter switches."
        )
        self.nuitka_cmd_preview.setStyleSheet(
            "font-family: monospace; background-color: #1e1e1e; color: #d4d4d4;"
        )
        config_layout.addWidget(self.nuitka_cmd_preview)

        self.export_settings_btn = QPushButton("💾 Export Nuitka Settings (.json)")
        self.export_settings_btn.setToolTip(
            "Export the current configuration parameters configured in this UI pane into a portable .json config file."
        )
        self.export_settings_btn.clicked.connect(self.export_nuitka_settings)
        config_layout.addWidget(self.export_settings_btn)

        self.load_settings_btn = QPushButton("📄 Load Nuitka Settings")
        self.load_settings_btn.setToolTip(
            "Load and re-apply configuration selections directly into this panel from an exported Nuitka JSON parameters profile file."
        )
        self.load_settings_btn.clicked.connect(self.load_nuitka_settings)
        config_layout.addWidget(self.load_settings_btn)

        nuitka_tabs.addTab(run_tab, "Compile")
        nuitka_tabs.addTab(config_tab, "Config / Settings")
        nuitka_tabs.currentChanged.connect(self._update_nuitka_preview)

        self._connect_nuitka_signals()
        nuitka_layout.addWidget(nuitka_tabs)

        nuitka_scroll.setWidget(nuitka_widget)
        nuitka_dock.setWidget(nuitka_scroll)
        return nuitka_dock

    # ---------- Helper Methods ----------
    def _browse_entry_script(self):
        start_dir = (
            self.folder_edit.text().strip()
            if hasattr(self, "folder_edit")
            else os.getcwd()
        )
        if not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Entry Script", start_dir, "Python Files (*.py)"
        )
        if file_path:
            self.nuitka_entry_edit.setText(file_path)

    def _browse_output_dir(self):
        start_dir = (
            self.folder_edit.text().strip()
            if hasattr(self, "folder_edit")
            else os.getcwd()
        )
        if not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", start_dir
        )
        if dir_path:
            self.nuitka_output_edit.setText(dir_path)

    def _browse_icon_file(self):
        start_dir = (
            self.folder_edit.text().strip()
            if hasattr(self, "folder_edit")
            else os.getcwd()
        )
        if not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        filter_str = (
            "Icon Files (*.ico *.icns);;All Files (*)"
            if sys.platform == "win32"
            else "Icon Files (*.icns *.ico);;All Files (*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Icon File", start_dir, filter_str
        )
        if file_path:
            self.nuitka_icon_edit.setText(file_path)

    def _create_collapsible_group(self, title):
        """Create a collapsible group box using the native title area."""
        return CollapsibleGroupBox(title)

    # ----- Data directories helpers -----
    def _add_data_dir_folder(self):
        src = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if not src:
            return
        if self.nuitka_auto_map_dirs_cb.isChecked():
            dest = os.path.basename(src.rstrip("/\\"))
            self.data_dirs_list.addItem(f"{src}={dest}")
        else:
            dest, ok = QInputDialog.getText(
                self, "Destination", "Destination path (relative to output):"
            )
            if not ok or not dest.strip():
                dest = os.path.basename(src.rstrip("/\\"))
            self.data_dirs_list.addItem(f"{src}={dest}")

    def _add_data_dir_custom(self):
        text, ok = QInputDialog.getText(
            self, "Custom Data Dir Entry", "Enter source=destination"
        )
        if ok and text.strip():
            self.data_dirs_list.addItem(text.strip())

    # ----- Data files helpers -----
    def _add_data_file(self):
        src = QFileDialog.getOpenFileName(self, "Select File to Include")[0]
        if not src:
            return
        if self.nuitka_auto_map_files_cb.isChecked():
            dest = os.path.basename(src)
            self.data_files_list.addItem(f"{src}={dest}")
        else:
            dest, ok = QInputDialog.getText(
                self, "Destination", "Destination path (relative to output):"
            )
            if not ok or not dest.strip():
                dest = os.path.basename(src)
            self.data_files_list.addItem(f"{src}={dest}")

    def _add_data_file_custom(self):
        text, ok = QInputDialog.getText(
            self, "Custom Data File Entry", "Enter source=destination"
        )
        if ok and text.strip():
            self.data_files_list.addItem(text.strip())

    def _remove_list_item(self, list_widget):
        row = list_widget.currentRow()
        if row >= 0:
            list_widget.takeItem(row)

    def _connect_nuitka_signals(self):
        edits = [
            self.nuitka_entry_edit,
            self.nuitka_output_edit,
            self.nuitka_enable_plugin_edit,
            self.nuitka_extra_edit,
            self.nuitka_icon_edit,
            self.nuitka_include_packages_edit,
            self.nuitka_include_modules_edit,
            self.nuitka_exclude_packages_edit,   # new
            self.nuitka_exclude_modules_edit,    # new
        ]
        for edit in edits:
            edit.textChanged.connect(self._update_nuitka_preview)

        cbs = [
            self.nuitka_standalone_cb,
            self.nuitka_onefile_cb,
            self.nuitka_console_cb,           # added
            self.console_disable_rb,          # added
            self.console_force_rb,            # added
            self.console_attach_rb,           # added
            self.nuitka_uac_admin_cb,
            self.nuitka_auto_plugin_pyside6_cb,
            self.nuitka_no_dependency_walker_cb,
            self.nuitka_follow_imports_cb,
            self.nuitka_lto_cb,
            self.nuitka_deployment_cb,
            self.nuitka_low_memory_cb,
            self.nuitka_no_pyi_cb,
            self.nuitka_experimental_cb,
            self.nuitka_auto_map_dirs_cb,
            self.nuitka_auto_map_files_cb,
        ]
        for cb in cbs:
            cb.clicked.connect(self._update_nuitka_preview)

        # Data directories list changes
        self.data_dirs_list.model().dataChanged.connect(self._update_nuitka_preview)
        self.data_dirs_list.model().rowsInserted.connect(self._update_nuitka_preview)
        self.data_dirs_list.model().rowsRemoved.connect(self._update_nuitka_preview)

        # Data files list changes
        self.data_files_list.model().dataChanged.connect(self._update_nuitka_preview)
        self.data_files_list.model().rowsInserted.connect(self._update_nuitka_preview)
        self.data_files_list.model().rowsRemoved.connect(self._update_nuitka_preview)

        self.nuitka_jobs_spin.valueChanged.connect(self._update_nuitka_preview)

    # ---------- Settings Load / Save (internal persistent dictionary framework) ----------
    def _load_nuitka_settings(self):
        self.nuitka_entry_edit.setText(self.settings.get("nuitka_entry", "main.py"))
        self.nuitka_output_edit.setText(self.settings.get("nuitka_output", ""))
        self.nuitka_standalone_cb.setChecked(
            self.settings.get("nuitka_standalone", False)
        )
        self.nuitka_onefile_cb.setChecked(self.settings.get("nuitka_onefile", False))

        # Load console override state
        self.nuitka_console_cb.setChecked(self.settings.get("nuitka_console_override", False))
        mode = self.settings.get("nuitka_console_mode", "disable")
        if mode == "disable":
            self.console_disable_rb.setChecked(True)
        elif mode == "force":
            self.console_force_rb.setChecked(True)
        else:
            self.console_attach_rb.setChecked(True)

        # Data directories
        data_dirs = self.settings.get("nuitka_include_data_dirs", [])
        self.data_dirs_list.clear()
        if isinstance(data_dirs, str):
            data_dirs = data_dirs.split()
        for entry in data_dirs:
            if entry.strip():
                self.data_dirs_list.addItem(entry.strip())

        # Data files
        data_files = self.settings.get("nuitka_include_data_files", [])
        self.data_files_list.clear()
        if isinstance(data_files, str):
            data_files = data_files.split()
        for entry in data_files:
            if entry.strip():
                self.data_files_list.addItem(entry.strip())

        self.nuitka_enable_plugin_edit.setText(
            self.settings.get("nuitka_enable_plugin", "")
        )
        self.nuitka_extra_edit.setText(self.settings.get("nuitka_extra", ""))
        self.nuitka_icon_edit.setText(self.settings.get("nuitka_icon", ""))
        self.nuitka_include_packages_edit.setText(
            self.settings.get("nuitka_include_packages", "")
        )
        self.nuitka_include_modules_edit.setText(
            self.settings.get("nuitka_include_modules", "")
        )
        # New exclude fields
        self.nuitka_exclude_packages_edit.setText(
            self.settings.get("nuitka_exclude_packages", "")
        )
        self.nuitka_exclude_modules_edit.setText(
            self.settings.get("nuitka_exclude_modules", "")
        )
        self.nuitka_uac_admin_cb.setChecked(
            self.settings.get("nuitka_uac_admin", False)
        )
        self.nuitka_jobs_spin.setValue(self.settings.get("nuitka_jobs", 0))
        self.nuitka_auto_plugin_pyside6_cb.setChecked(
            self.settings.get("nuitka_auto_plugin_pyside6", True)
        )
        self.nuitka_no_dependency_walker_cb.setChecked(
            self.settings.get("nuitka_no_dependency_walker", True)
        )

        self.nuitka_follow_imports_cb.setChecked(
            self.settings.get("nuitka_follow_imports", False)
        )
        self.nuitka_lto_cb.setChecked(self.settings.get("nuitka_lto", False))
        self.nuitka_deployment_cb.setChecked(
            self.settings.get("nuitka_deployment", False)
        )
        self.nuitka_low_memory_cb.setChecked(
            self.settings.get("nuitka_low_memory", False)
        )
        self.nuitka_no_pyi_cb.setChecked(self.settings.get("nuitka_no_pyi", False))
        self.nuitka_experimental_cb.setChecked(
            self.settings.get("nuitka_experimental", False)
        )

        # Correctly load auto-map checkbox states internally
        self.nuitka_auto_map_dirs_cb.setChecked(
            self.settings.get("nuitka_auto_map_dirs", False)
        )
        self.nuitka_auto_map_files_cb.setChecked(
            self.settings.get("nuitka_auto_map_files", False)
        )

        self._update_nuitka_preview()

    def _save_nuitka_settings(self):
        self.settings.set("nuitka_entry", self.nuitka_entry_edit.text().strip())
        self.settings.set("nuitka_output", self.nuitka_output_edit.text().strip())
        self.settings.set("nuitka_standalone", self.nuitka_standalone_cb.isChecked())
        self.settings.set("nuitka_onefile", self.nuitka_onefile_cb.isChecked())

        # Save console override state
        self.settings.set("nuitka_console_override", self.nuitka_console_cb.isChecked())
        if self.console_disable_rb.isChecked():
            mode = "disable"
        elif self.console_force_rb.isChecked():
            mode = "force"
        else:
            mode = "attach"
        self.settings.set("nuitka_console_mode", mode)

        # Save data directories as list
        data_dirs = [
            self.data_dirs_list.item(i).text()
            for i in range(self.data_dirs_list.count())
        ]
        self.settings.set("nuitka_include_data_dirs", data_dirs)

        # Save data files as list
        data_files = [
            self.data_files_list.item(i).text()
            for i in range(self.data_files_list.count())
        ]
        self.settings.set("nuitka_include_data_files", data_files)

        self.settings.set(
            "nuitka_enable_plugin", self.nuitka_enable_plugin_edit.text().strip()
        )
        self.settings.set("nuitka_extra", self.nuitka_extra_edit.text().strip())
        self.settings.set("nuitka_icon", self.nuitka_icon_edit.text().strip())
        self.settings.set(
            "nuitka_include_packages", self.nuitka_include_packages_edit.text().strip()
        )
        self.settings.set(
            "nuitka_include_modules", self.nuitka_include_modules_edit.text().strip()
        )
        # New exclude fields
        self.settings.set(
            "nuitka_exclude_packages", self.nuitka_exclude_packages_edit.text().strip()
        )
        self.settings.set(
            "nuitka_exclude_modules", self.nuitka_exclude_modules_edit.text().strip()
        )
        self.settings.set("nuitka_uac_admin", self.nuitka_uac_admin_cb.isChecked())
        self.settings.set("nuitka_jobs", self.nuitka_jobs_spin.value())
        self.settings.set(
            "nuitka_auto_plugin_pyside6", self.nuitka_auto_plugin_pyside6_cb.isChecked()
        )
        self.settings.set(
            "nuitka_no_dependency_walker",
            self.nuitka_no_dependency_walker_cb.isChecked(),
        )

        self.settings.set(
            "nuitka_follow_imports", self.nuitka_follow_imports_cb.isChecked()
        )
        self.settings.set("nuitka_lto", self.nuitka_lto_cb.isChecked())
        self.settings.set("nuitka_deployment", self.nuitka_deployment_cb.isChecked())
        self.settings.set("nuitka_low_memory", self.nuitka_low_memory_cb.isChecked())
        self.settings.set("nuitka_no_pyi", self.nuitka_no_pyi_cb.isChecked())
        self.settings.set(
            "nuitka_experimental", self.nuitka_experimental_cb.isChecked()
        )

        # Correctly save auto-map checkbox states internally
        self.settings.set(
            "nuitka_auto_map_dirs", self.nuitka_auto_map_dirs_cb.isChecked()
        )
        self.settings.set(
            "nuitka_auto_map_files", self.nuitka_auto_map_files_cb.isChecked()
        )

    # ---------- Command Generation & Preview ----------
    def _generate_nuitka_args(self):
        args = ["-m", "nuitka"]

        if self.nuitka_standalone_cb.isChecked():
            args.append("--standalone")
        if self.nuitka_onefile_cb.isChecked():
            args.append("--onefile")

        # Console mode handling
        if self.nuitka_console_cb.isChecked():
            if self.console_disable_rb.isChecked():
                args.append("--windows-console-mode=disable")
                if sys.platform == "darwin":
                    args.append("--macos-disable-console")
            elif self.console_force_rb.isChecked():
                args.append("--windows-console-mode=force")
            elif self.console_attach_rb.isChecked():
                args.append("--windows-console-mode=attach")

        out_dir = self.nuitka_output_edit.text().strip()
        if out_dir:
            args.append(f"--output-dir={out_dir}")

        plugins = self.nuitka_enable_plugin_edit.text().strip()
        if plugins:
            cleaned = ",".join(p.strip() for p in plugins.split(",") if p.strip())
            args.append(f"--enable-plugin={cleaned}")

        if self.nuitka_auto_plugin_pyside6_cb.isChecked() and "pyside6" not in args:
            args.append("--enable-plugin=pyside6")

        if self.nuitka_no_dependency_walker_cb.isChecked():
            args.append("--no-dependency-walker")

        # Include data directories
        for i in range(self.data_dirs_list.count()):
            item = self.data_dirs_list.item(i).text().strip()
            if item:
                args.append(f"--include-data-dir={item}")

        # Include data files
        for i in range(self.data_files_list.count()):
            item = self.data_files_list.item(i).text().strip()
            if item:
                args.append(f"--include-data-files={item}")

        icon_path = self.nuitka_icon_edit.text().strip()
        if icon_path:
            if sys.platform == "win32":
                args.append(f"--windows-icon-from-ico={icon_path}")
            elif sys.platform == "darwin":
                args.append(f"--macos-app-icon={icon_path}")

        for pkg in self.nuitka_include_packages_edit.text().strip().split():
            if pkg:
                args.append(f"--include-package={pkg}")
        for mod in self.nuitka_include_modules_edit.text().strip().split():
            if mod:
                args.append(f"--include-module={mod}")

        # New exclude flags
        for pkg in self.nuitka_exclude_packages_edit.text().strip().split():
            if pkg:
                args.append(f"--exclude-package={pkg}")
        for mod in self.nuitka_exclude_modules_edit.text().strip().split():
            if mod:
                args.append(f"--exclude-module={mod}")

        if self.nuitka_uac_admin_cb.isChecked() and sys.platform == "win32":
            args.append("--windows-uac-admin")

        jobs = self.nuitka_jobs_spin.value()
        if jobs > 0:
            args.append(f"--jobs={jobs}")

        if self.nuitka_follow_imports_cb.isChecked():
            args.append("--follow-imports")
        if self.nuitka_lto_cb.isChecked():
            args.append("--lto=auto")
        if self.nuitka_deployment_cb.isChecked():
            args.append("--deployment")
        if self.nuitka_low_memory_cb.isChecked():
            args.append("--low-memory")
        if self.nuitka_no_pyi_cb.isChecked():
            args.append("--no-pyi-file")
        if self.nuitka_experimental_cb.isChecked():
            args.append("--experimental")

        extra = self.nuitka_extra_edit.text().strip()
        if extra:
            args.extend(extra.split())

        entry = self.nuitka_entry_edit.text().strip()
        if entry:
            args.append(entry)

        return args

    def _update_nuitka_preview(self):
        args = self._generate_nuitka_args()
        self.nuitka_cmd_preview.setPlainText("python \\\n    " + " \\\n    ".join(args))

    # ---------- Public Run ----------
    def run_nuitka(self):
        self.save_current_settings()
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            QMessageBox.warning(
                self,
                "Invalid Workspace",
                "Please select a valid project directory first.",
            )
            return
        if not self.nuitka_entry_edit.text().strip():
            QMessageBox.warning(
                self,
                "Missing Entry Script",
                "Please define a target script (e.g., main.py).",
            )
            return

        args = self._generate_nuitka_args()
        program, resolved_args, env_data = self._build_env_command("python", args)
        if program:
            self.run_command(
                program, resolved_args, project_folder, "Nuitka Compilation", env_data
            )

    # ---------- JSON Export / Import ----------
    def export_nuitka_settings(self):
        self.save_current_settings()
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            QMessageBox.warning(
                self,
                "Invalid Workspace",
                "Please select a valid project directory first.",
            )
            return

        default_path = os.path.join(project_folder, "nuitka_settings.json")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Nuitka Settings", default_path, "JSON Files (*.json)"
        )
        if not save_path:
            return

        data = {
            "entry": self.nuitka_entry_edit.text().strip(),
            "output_dir": self.nuitka_output_edit.text().strip(),
            "standalone": self.nuitka_standalone_cb.isChecked(),
            "onefile": self.nuitka_onefile_cb.isChecked(),
            "console_override": self.nuitka_console_cb.isChecked(),
            "console_mode": (
                "disable" if self.console_disable_rb.isChecked() else
                "force" if self.console_force_rb.isChecked() else
                "attach"
            ),
            "include_data_dirs": [
                self.data_dirs_list.item(i).text()
                for i in range(self.data_dirs_list.count())
            ],
            "include_data_files": [
                self.data_files_list.item(i).text()
                for i in range(self.data_files_list.count())
            ],
            "enable_plugin": self.nuitka_enable_plugin_edit.text().strip(),
            "extra_args": self.nuitka_extra_edit.text().strip(),
            "icon": self.nuitka_icon_edit.text().strip(),
            "include_packages": self.nuitka_include_packages_edit.text().strip(),
            "include_modules": self.nuitka_include_modules_edit.text().strip(),
            "exclude_packages": self.nuitka_exclude_packages_edit.text().strip(),
            "exclude_modules": self.nuitka_exclude_modules_edit.text().strip(),
            "uac_admin": self.nuitka_uac_admin_cb.isChecked(),
            "jobs": self.nuitka_jobs_spin.value(),
            "auto_plugin_pyside6": self.nuitka_auto_plugin_pyside6_cb.isChecked(),
            "no_dependency_walker": self.nuitka_no_dependency_walker_cb.isChecked(),
            "follow_imports": self.nuitka_follow_imports_cb.isChecked(),
            "lto": self.nuitka_lto_cb.isChecked(),
            "deployment": self.nuitka_deployment_cb.isChecked(),
            "low_memory": self.nuitka_low_memory_cb.isChecked(),
            "no_pyi": self.nuitka_no_pyi_cb.isChecked(),
            "experimental": self.nuitka_experimental_cb.isChecked(),
            "auto_map_dirs": self.nuitka_auto_map_dirs_cb.isChecked(),
            "auto_map_files": self.nuitka_auto_map_files_cb.isChecked(),
        }
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            QMessageBox.information(self, "Success", f"Settings saved to:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def load_nuitka_settings(self):
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            QMessageBox.warning(
                self,
                "Invalid Workspace",
                "Please select a valid project directory first.",
            )
            return

        load_path, _ = QFileDialog.getOpenFileName(
            self, "Load Nuitka Settings", project_folder, "JSON Files (*.json)"
        )
        if not load_path:
            return

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.nuitka_entry_edit.setText(data.get("entry", ""))
            self.nuitka_output_edit.setText(data.get("output_dir", ""))
            self.nuitka_standalone_cb.setChecked(data.get("standalone", False))
            self.nuitka_onefile_cb.setChecked(data.get("onefile", False))

            # Load console settings
            self.nuitka_console_cb.setChecked(data.get("console_override", False))
            mode = data.get("console_mode", "disable")
            if mode == "disable":
                self.console_disable_rb.setChecked(True)
            elif mode == "force":
                self.console_force_rb.setChecked(True)
            else:
                self.console_attach_rb.setChecked(True)

            self.data_dirs_list.clear()
            for entry in data.get("include_data_dirs", []):
                self.data_dirs_list.addItem(entry)
            self.data_files_list.clear()
            for entry in data.get("include_data_files", []):
                self.data_files_list.addItem(entry)

            self.nuitka_enable_plugin_edit.setText(data.get("enable_plugin", ""))
            self.nuitka_extra_edit.setText(data.get("extra_args", ""))
            self.nuitka_icon_edit.setText(data.get("icon", ""))
            self.nuitka_include_packages_edit.setText(data.get("include_packages", ""))
            self.nuitka_include_modules_edit.setText(data.get("include_modules", ""))
            # New exclude fields
            self.nuitka_exclude_packages_edit.setText(data.get("exclude_packages", ""))
            self.nuitka_exclude_modules_edit.setText(data.get("exclude_modules", ""))
            self.nuitka_uac_admin_cb.setChecked(data.get("uac_admin", False))
            self.nuitka_jobs_spin.setValue(data.get("jobs", 0))
            self.nuitka_auto_plugin_pyside6_cb.setChecked(
                data.get("auto_plugin_pyside6", True)
            )
            self.nuitka_no_dependency_walker_cb.setChecked(
                data.get("no_dependency_walker", True)
            )

            self.nuitka_follow_imports_cb.setChecked(data.get("follow_imports", False))
            self.nuitka_lto_cb.setChecked(data.get("lto", False))
            self.nuitka_deployment_cb.setChecked(data.get("deployment", False))
            self.nuitka_low_memory_cb.setChecked(data.get("low_memory", False))
            self.nuitka_no_pyi_cb.setChecked(data.get("no_pyi", False))
            self.nuitka_experimental_cb.setChecked(data.get("experimental", False))

            # Fully loaded state synchronization for auto-map configs
            self.nuitka_auto_map_dirs_cb.setChecked(data.get("auto_map_dirs", False))
            self.nuitka_auto_map_files_cb.setChecked(data.get("auto_map_files", False))

            self._update_nuitka_preview()
            QMessageBox.information(
                self, "Success", f"Settings loaded from:\n{load_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load: {e}")