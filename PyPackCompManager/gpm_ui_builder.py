"""UI construction and settings persistence for the Global Packages dock.

Holds the dock/tab builders plus the load/save of widget state, since the
settings are simply the persisted form of the widgets defined here.

Square icon-only buttons use ``self._style_square_icon_button`` from
``CoreUIMixin`` (core_ui_helpers) rather than re-implementing the sizing.
"""

from PySide6.QtWidgets import (
    QDockWidget,
    QScrollArea,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QComboBox,
    QLabel,
    QTabWidget,
    QListWidget,
    QGroupBox,
    QCheckBox,
)
from PySide6.QtCore import Qt

from core_ui_helpers import CollapsibleGroupBox, QHLine


class GlobalPackagesUIMixin:
    """Builds the dock + tabs and loads/saves their state."""

    # ==================================================================
    # Dock assembly
    # ==================================================================
    def _build_global_packages_dock(self):
        global_dock = QDockWidget("Global Package Management", self)
        global_dock.setObjectName("globalPackagesDock")
        global_dock.setMinimumSize(340, 300)
        global_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        global_dock.setFeatures(QDockWidget.DockWidgetMovable)

        global_scroll = QScrollArea()
        global_scroll.setWidgetResizable(True)
        global_scroll.setFrameShape(QScrollArea.NoFrame)
        global_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        global_widget = QWidget()
        global_layout = QVBoxLayout(global_widget)

        global_tabs = QTabWidget()
        global_tabs.addTab(self._build_pypi_tab(), "PyPI Install")
        global_tabs.addTab(self._build_conda_tab(), "Conda Install")
        global_tabs.addTab(self._build_installed_tab(), "Installed")
        global_tabs.addTab(self._build_cuda_tab(), "CUDA")

        global_layout.addWidget(global_tabs)
        global_scroll.setWidget(global_widget)
        global_dock.setWidget(global_scroll)
        return global_dock

    # ================== TAB 1: PyPI Install / Build Wheel ==================
    def _build_pypi_tab(self):
        tab_pypi = QWidget()
        pypi_layout = QVBoxLayout(tab_pypi)

        # Package manager selector for PyPI installs
        pypi_pm_layout = QHBoxLayout()
        pypi_pm_layout.addWidget(QLabel("Package manager for PyPI:"))
        self.pypi_pm_combo = QComboBox()
        self.pypi_pm_combo.setToolTip(
            "Select the package manager to use when installing from PyPI."
        )
        self.pypi_pm_combo.addItems(["pip", "uv pip"])
        self.pypi_pm_combo.currentTextChanged.connect(self.save_current_settings)
        pypi_pm_layout.addWidget(self.pypi_pm_combo)
        pypi_pm_layout.addStretch()
        pypi_layout.addLayout(pypi_pm_layout)

        # Search box
        pypi_search_layout = QHBoxLayout()
        self.pypi_search_edit = QLineEdit()
        self.pypi_search_edit.setPlaceholderText("e.g. package_name or requirements.txt")
        self.pypi_search_edit.setToolTip(
            "Enter a package name or select a requirements file."
        )
        self.pypi_search_edit.returnPressed.connect(self.search_pypi_info)

        self.pypi_search_btn = QPushButton("🔍")
        self.pypi_search_btn.setToolTip(
            "Search for this package on PyPI (You can also press Enter)."
        )
        self.pypi_search_btn.clicked.connect(self.search_pypi_info)
        self._style_square_icon_button(self.pypi_search_btn)

        self.pypi_browse_req_btn = QPushButton("📄")
        self.pypi_browse_req_btn.setToolTip("Select a requirements file (.txt or pyproject.toml)")
        self.pypi_browse_req_btn.clicked.connect(self._browse_pypi_req_file)
        self._style_square_icon_button(self.pypi_browse_req_btn)

        pypi_search_layout.addWidget(self.pypi_search_edit)
        pypi_search_layout.addWidget(self.pypi_search_btn)
        pypi_search_layout.addWidget(self.pypi_browse_req_btn)
        pypi_layout.addLayout(pypi_search_layout)

        self.pypi_info_label = QLabel("Enter a package name to search.")
        self.pypi_info_label.setWordWrap(True)
        pypi_layout.addWidget(self.pypi_info_label)

        pypi_layout.addWidget(QHLine())

        # --- Advanced Build / CUDA Support Group (collapsible) ---
        self.build_group = CollapsibleGroupBox("Advanced Build / CUDA Configuration")
        self.build_group.setToolTip(
            "Click title to expand/collapse. Enable the checkbox inside to activate source compilation."
        )

        # Content widget inside the collapsible group
        build_content_layout = QVBoxLayout(self.build_group.content_widget)

        # Enable/disable checkbox for the advanced features
        self.build_enabled_cb = QCheckBox("Enable advanced build / CUDA support")
        self.build_enabled_cb.setToolTip(
            "When checked, packages will be compiled from source with the options below."
        )
        self.build_enabled_cb.toggled.connect(self._toggle_advanced_build_widgets)
        build_content_layout.addWidget(self.build_enabled_cb)

        # --- CMake Presets (checkboxes) ---
        self.cmake_presets_group = QGroupBox("CMake Presets")
        cmake_presets_layout = QVBoxLayout(self.cmake_presets_group)

        self.cmake_ninja_cb = QCheckBox("Force CMake to use Ninja (-G Ninja)")
        self.cmake_ninja_cb.setToolTip("Force Ninja generator instead of Visual Studio. Useful if CUDA/VS integration is missing.")
        self.cmake_cuda_cb = QCheckBox("GGML_CUDA=on (NVIDIA GPU)")
        self.cmake_cuda_cb.setToolTip("Enable CUDA support for GPU acceleration.")
        self.cmake_metal_cb = QCheckBox("GGML_METAL=on (Apple Silicon)")
        self.cmake_metal_cb.setToolTip("Enable Metal support on macOS.")
        self.cmake_vulkan_cb = QCheckBox("GGML_VULKAN=on (Vulkan GPU)")
        self.cmake_vulkan_cb.setToolTip("Enable Vulkan support.")
        self.cmake_openblas_cb = QCheckBox("GGML_OPENBLAS=on")
        self.cmake_openblas_cb.setToolTip("Use OpenBLAS for linear algebra.")
        self.cmake_clblast_cb = QCheckBox("GGML_CLBLAST=on")
        self.cmake_clblast_cb.setToolTip("Use CLBlast for OpenCL acceleration.")

        self.cmake_unsupported_compiler_cb = QCheckBox(
            "Bypass MSVC Check (-allow-unsupported-compiler)"
        )
        self.cmake_unsupported_compiler_cb.setToolTip(
            "Use this if CUDA fails to compile due to an unsupported Visual Studio version."
        )

        for cb in [
            self.cmake_ninja_cb,
            self.cmake_cuda_cb,
            self.cmake_metal_cb,
            self.cmake_vulkan_cb,
            self.cmake_openblas_cb,
            self.cmake_clblast_cb,
            self.cmake_unsupported_compiler_cb,
        ]:
            cb.toggled.connect(self._update_cmake_args_from_presets)

        cmake_presets_layout.addWidget(self.cmake_ninja_cb)
        cmake_presets_layout.addWidget(self.cmake_cuda_cb)
        cmake_presets_layout.addWidget(self.cmake_metal_cb)
        cmake_presets_layout.addWidget(self.cmake_vulkan_cb)
        cmake_presets_layout.addWidget(self.cmake_openblas_cb)
        cmake_presets_layout.addWidget(self.cmake_clblast_cb)
        cmake_presets_layout.addWidget(self.cmake_unsupported_compiler_cb)

        build_content_layout.addWidget(self.cmake_presets_group)

        # CMAKE_ARGS Input (custom)
        cmake_layout = QHBoxLayout()
        cmake_layout.addWidget(QLabel("CMAKE_ARGS:"))
        self.pypi_cmake_args_edit = QLineEdit()
        self.pypi_cmake_args_edit.setPlaceholderText(
            '-DGGML_CUDA=on -DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler"'
        )
        self.pypi_cmake_args_edit.setToolTip(
            "Additional CMake arguments (space-separated)."
        )
        self.pypi_cmake_args_edit.textChanged.connect(self.save_current_settings)
        cmake_layout.addWidget(self.pypi_cmake_args_edit)
        build_content_layout.addLayout(cmake_layout)

        # Build Flags
        self.pypi_no_cache_cb = QCheckBox("No Cache")
        self.pypi_no_cache_cb.setChecked(True)
        self.pypi_no_cache_cb.setToolTip(
            "Prevent using pre-built cached wheels (--no-cache-dir / --no-cache)."
        )

        self.pypi_force_reinstall_cb = QCheckBox("--force-reinstall")
        self.pypi_force_reinstall_cb.setChecked(True)
        self.pypi_force_reinstall_cb.setToolTip(
            "Force rebuilding the package even if it's already installed."
        )

        self.pypi_upgrade_cb = QCheckBox("--upgrade")
        self.pypi_upgrade_cb.setChecked(True)

        flags_layout = QHBoxLayout()
        flags_layout.addWidget(self.pypi_no_cache_cb)
        flags_layout.addWidget(self.pypi_force_reinstall_cb)
        flags_layout.addWidget(self.pypi_upgrade_cb)
        flags_layout.addStretch()
        build_content_layout.addLayout(flags_layout)

        pypi_layout.addWidget(self.build_group)

        self.pypi_install_btn = QPushButton("🌐 Install from PyPI")
        self._setup_button(
            self.pypi_install_btn,
            "Install this package from PyPI using the selected package manager.",
        )
        self._style_critical_button(self.pypi_install_btn, "#0277BD", "#01579B")
        self.pypi_install_btn.clicked.connect(self.install_from_pypi)

        self.pypi_build_wheel_btn = QPushButton("📦 Build Wheel")
        self._setup_button(
            self.pypi_build_wheel_btn,
            "Build a wheel (.whl) from source with the selected options.",
        )
        self._style_critical_button(self.pypi_build_wheel_btn, "#39A4D6", "#218FC3")
        self.pypi_build_wheel_btn.clicked.connect(self.build_wheel_from_pypi)

        # Enforce state strictly so another process cannot mistakenly enable it
        original_set_enabled = self.pypi_build_wheel_btn.setEnabled
        def guarded_set_enabled(enabled):
            if self.pypi_pm_combo.currentText() != "pip":
                original_set_enabled(False)
            else:
                original_set_enabled(enabled)
        self.pypi_build_wheel_btn.setEnabled = guarded_set_enabled

        self.pypi_pm_combo.currentTextChanged.connect(
            lambda text: self.pypi_build_wheel_btn.setEnabled(True)
        )
        self.pypi_build_wheel_btn.setEnabled(True)

        pypi_layout.addWidget(self.pypi_install_btn)

        pypi_layout.addWidget(QHLine())

        wheel_folder_layout = QHBoxLayout()
        wheel_folder_layout.addWidget(QLabel("Wheel output folder:"))
        self.wheel_output_edit = QLineEdit()
        self.wheel_output_edit.setPlaceholderText("Select folder...")
        self.wheel_output_edit.setToolTip(
            "Directory where the built .whl file will be saved."
        )
        wheel_browse_btn = QPushButton("📂")
        wheel_browse_btn.setToolTip("Browse for folder")
        wheel_browse_btn.clicked.connect(self._browse_wheel_output_dir)
        self._style_square_icon_button(wheel_browse_btn)
        wheel_folder_layout.addWidget(self.wheel_output_edit)
        wheel_folder_layout.addWidget(wheel_browse_btn)
        pypi_layout.addLayout(wheel_folder_layout)

        pypi_layout.addWidget(self.pypi_build_wheel_btn)

        pypi_layout.addStretch()
        return tab_pypi

    # ================== TAB 2: Conda Search & Install ==================
    def _build_conda_tab(self):
        tab_conda = QWidget()
        conda_layout = QVBoxLayout(tab_conda)

        conda_channel_layout = QHBoxLayout()
        conda_channel_layout.addWidget(QLabel("Conda channel:"))
        self.conda_channel_combo = QComboBox()
        self.conda_channel_combo.setToolTip(
            "Select the Conda channel/repository to install from."
        )
        self.conda_channel_combo.setEditable(True)
        self.conda_channel_combo.addItems(
            ["conda-forge", "defaults", "bioconda", "anaconda", "pytorch", "nvidia"]
        )
        self.conda_channel_combo.currentTextChanged.connect(self.save_current_settings)
        conda_channel_layout.addWidget(self.conda_channel_combo)
        conda_channel_layout.addStretch()
        conda_layout.addLayout(conda_channel_layout)

        conda_search_layout = QHBoxLayout()
        self.conda_search_edit = QLineEdit()
        self.conda_search_edit.setPlaceholderText("e.g. numpy or requirements.txt")
        self.conda_search_edit.setToolTip(
            "Enter a package name or select a requirements file."
        )
        self.conda_search_edit.returnPressed.connect(self.search_conda_info)

        self.conda_search_btn = QPushButton("🔍")
        self.conda_search_btn.setToolTip(
            "Search for this package on Conda (You can also press Enter)."
        )
        self.conda_search_btn.clicked.connect(self.search_conda_info)
        self._style_square_icon_button(self.conda_search_btn)

        self.conda_browse_req_btn = QPushButton("📄")
        self.conda_browse_req_btn.setToolTip("Select a Conda requirements file (.txt, .yml)")
        self.conda_browse_req_btn.clicked.connect(self._browse_conda_req_file)
        self._style_square_icon_button(self.conda_browse_req_btn)

        conda_search_layout.addWidget(self.conda_search_edit)
        conda_search_layout.addWidget(self.conda_search_btn)
        conda_search_layout.addWidget(self.conda_browse_req_btn)
        conda_layout.addLayout(conda_search_layout)

        self.conda_info_label = QLabel("Enter a package name to search via conda.")
        self.conda_info_label.setWordWrap(True)
        conda_layout.addWidget(self.conda_info_label)

        self.conda_install_btn = QPushButton("🌐 Install via Conda")
        self._setup_button(
            self.conda_install_btn,
            "Install this package using Conda (only for Conda environments).",
        )
        self._style_critical_button(self.conda_install_btn, "#00796B", "#004D40")
        self.conda_install_btn.clicked.connect(self.install_from_conda_tab)
        conda_layout.addWidget(self.conda_install_btn)

        conda_layout.addStretch()
        return tab_conda

    # ================== TAB 3: Installed Packages ==================
    def _build_installed_tab(self):
        tab_installed = QWidget()
        installed_layout = QVBoxLayout(tab_installed)

        manager_layout = QHBoxLayout()
        manager_layout.addWidget(QLabel("Package Manager (uninstall/update):"))
        self.global_pm_combo = QComboBox()
        self.global_pm_combo.setToolTip(
            "Package manager to use for uninstalling or updating packages."
        )
        self.global_pm_combo.addItems(["pip", "conda", "uv pip"])
        self.global_pm_combo.currentTextChanged.connect(self.save_current_settings)
        manager_layout.addWidget(self.global_pm_combo)
        manager_layout.addStretch()
        installed_layout.addLayout(manager_layout)


        self.refresh_installed_btn = QPushButton("🔄 Fetch Installed Packages")
        self.refresh_installed_btn.setToolTip(
            "Get a list of all installed packages in the active environment."
        )
        self.refresh_installed_btn.clicked.connect(self.refresh_installed_packages)
        installed_layout.addWidget(self.refresh_installed_btn)

        # Filter input row
        filter_layout = QHBoxLayout()
        #filter_layout.addWidget(QLabel("Filter:"))
        self.installed_filter_edit = QLineEdit()
        self.installed_filter_edit.setPlaceholderText("Filter by space‑separated terms (any match)")
        self.installed_filter_edit.setToolTip(
            "Show only packages containing any of these terms (case‑insensitive)"
        )
        self.installed_filter_edit.textChanged.connect(self._filter_installed_packages)
        filter_layout.addWidget(self.installed_filter_edit)
        installed_layout.addLayout(filter_layout)

        self.installed_list = QListWidget()
        self.installed_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.installed_list.setToolTip(
            "Click and drag or hold Ctrl/Shift to select multiple packages."
        )
        self.installed_list.itemSelectionChanged.connect(
            self._on_installed_selection_changed
        )
        installed_layout.addWidget(self.installed_list)

        selected_pkg_layout = QHBoxLayout()
        selected_pkg_layout.addWidget(QLabel("Package(s) selected:"))
        self.global_selected_pkg_edit = QLineEdit()
        self.global_selected_pkg_edit.setToolTip(
            "Space-separated list of packages (auto-filled by selection)."
        )
        self.global_selected_pkg_edit.textChanged.connect(self.save_current_settings)
        selected_pkg_layout.addWidget(self.global_selected_pkg_edit)
        installed_layout.addLayout(selected_pkg_layout)

        self.global_update_btn = QPushButton("🔄 Update Selected")
        self._setup_button(
            self.global_update_btn,
            "Update the selected package(s) to the latest version.",
        )
        self._style_critical_button(self.global_update_btn, "#FF8C00", "#E67E00")
        self.global_update_btn.clicked.connect(self.update_global_packages)
        installed_layout.addWidget(self.global_update_btn)

        self.global_uninstall_btn = QPushButton("🗑️ Uninstall Selected")
        self._setup_button(
            self.global_uninstall_btn,
            "Uninstall the selected package(s) simultaneously.",
        )
        self._style_critical_button(self.global_uninstall_btn, "#D32F2F", "#C62828")
        self.global_uninstall_btn.clicked.connect(self.uninstall_global_packages)
        installed_layout.addWidget(self.global_uninstall_btn)

        installed_layout.addStretch()
        return tab_installed

    # ================== TAB 4: CUDA & System Audit ==================
    def _build_cuda_tab(self):
        tab_cuda = QWidget()
        cuda_layout = QVBoxLayout(tab_cuda)

        # Audit Group
        self.audit_group = QGroupBox("System Audit (Check CUDA State)")
        audit_layout = QVBoxLayout(self.audit_group)

        # VCVARS configuration sub-layout
        vcvars_layout = QHBoxLayout()
        vcvars_layout.addWidget(QLabel("MSVC Env:"))
        self.vcvars_edit = QLineEdit()
        self.vcvars_edit.setPlaceholderText("Path to vcvars64.bat...")
        self.vcvars_edit.setToolTip(
            "Leave blank to auto-detect, or set your specific VS Developer Command Prompt script."
        )
        self.vcvars_edit.textChanged.connect(self.save_current_settings)

        btn_browse_vcvars = QPushButton("📂")
        btn_browse_vcvars.setToolTip("Browse for vcvars64.bat manually")
        btn_browse_vcvars.clicked.connect(self._browse_vcvars)
        self._style_square_icon_button(btn_browse_vcvars)

        self.btn_auto_vcvars = QPushButton("🔍")
        self.btn_auto_vcvars.setToolTip(
            "Search standard directories for Visual Studio's vcvars64.bat"
        )
        self.btn_auto_vcvars.clicked.connect(self._manual_auto_detect_vcvars)
        self._style_square_icon_button(self.btn_auto_vcvars)

        vcvars_layout.addWidget(self.vcvars_edit)
        vcvars_layout.addWidget(btn_browse_vcvars)
        vcvars_layout.addWidget(self.btn_auto_vcvars)
        

        # System check buttons sub-layout
        audit_btns_layout = QHBoxLayout()
        self.btn_check_smi = QPushButton("🖥️ nvidia-smi")
        self.btn_check_smi.setToolTip(
            "Check NVIDIA Driver & Max Supported CUDA Version"
        )
        self.btn_check_smi.clicked.connect(lambda: self.run_audit_command("nvidia-smi"))

        self.btn_check_nvcc = QPushButton("🛠️ nvcc --version")
        self.btn_check_nvcc.setToolTip("Check Installed CUDA Toolkit Version")
        self.btn_check_nvcc.clicked.connect(lambda: self.run_audit_command("nvcc"))

        self.btn_check_cl = QPushButton("⚙️ cl (MSVC)")
        self.btn_check_cl.setToolTip(
            "Detects and updates vcvars64.bat, then tests the C++ Compiler"
        )
        self.btn_check_cl.clicked.connect(self._on_check_cl_clicked)

        audit_btns_layout.addWidget(self.btn_check_smi)
        audit_btns_layout.addWidget(self.btn_check_nvcc)
        audit_btns_layout.addWidget(self.btn_check_cl)

        audit_layout.addLayout(vcvars_layout)
        audit_layout.addLayout(audit_btns_layout)

        cuda_layout.addWidget(self.audit_group)

        # Install Group
        self.cuda_install_group = QGroupBox("Prepare Environment")
        cuda_install_layout = QVBoxLayout(self.cuda_install_group)
        self.cuda_prep_btn = QPushButton("🛠️ Install CUDA Toolkit into Environment")
        self._setup_button(
            self.cuda_prep_btn,
            "Prep this environment for source compilation by installing the NVIDIA CUDA toolkit.",
        )
        self._style_critical_button(self.cuda_prep_btn, "#388E3C", "#2E7D32")
        self.cuda_prep_btn.clicked.connect(self.prep_cuda_environment)
        cuda_install_layout.addWidget(self.cuda_prep_btn)

        cuda_layout.addWidget(self.cuda_install_group)
        cuda_layout.addStretch()
        return tab_cuda

    # ==================================================================
    # Settings load / save (persisted widget state)
    # ==================================================================
    def _load_global_settings(self):
        for combo, key in [
            (self.global_pm_combo, "global_package_manager"),
            (self.pypi_pm_combo, "pypi_package_manager"),
        ]:
            val = self.settings.get(key, combo.itemText(0))
            idx = combo.findText(val)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

        channel = self.settings.get("conda_channel", "conda-forge")
        idx = self.conda_channel_combo.findText(channel)
        self.conda_channel_combo.blockSignals(True)
        if idx >= 0:
            self.conda_channel_combo.setCurrentIndex(idx)
        else:
            self.conda_channel_combo.setEditText(channel)
        self.conda_channel_combo.blockSignals(False)

        self.global_selected_pkg_edit.setText(
            self.settings.get("global_selected_packages", "")
        )
        self.pypi_search_edit.setText(self.settings.get("pypi_search_package", ""))
        self.conda_search_edit.setText(self.settings.get("conda_search_package", ""))

        # Advanced Build Settings
        self.build_enabled_cb.setChecked(self.settings.get("pypi_build_enabled", False))
        self.pypi_cmake_args_edit.setText(
            self.settings.get(
                "pypi_cmake_args",
                '-DGGML_CUDA=on -DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler"',
            )
        )
        self.pypi_no_cache_cb.setChecked(self.settings.get("pypi_no_cache", True))
        self.pypi_force_reinstall_cb.setChecked(
            self.settings.get("pypi_force_reinstall", True)
        )
        self.pypi_upgrade_cb.setChecked(self.settings.get("pypi_upgrade", True))

        # CMake presets
        self.cmake_ninja_cb.setChecked(self.settings.get("cmake_ninja", False))
        self.cmake_cuda_cb.setChecked(self.settings.get("cmake_cuda", False))
        self.cmake_metal_cb.setChecked(self.settings.get("cmake_metal", False))
        self.cmake_vulkan_cb.setChecked(self.settings.get("cmake_vulkan", False))
        self.cmake_openblas_cb.setChecked(self.settings.get("cmake_openblas", False))
        self.cmake_clblast_cb.setChecked(self.settings.get("cmake_clblast", False))
        self.cmake_unsupported_compiler_cb.setChecked(
            self.settings.get("cmake_unsupported_compiler", True)
        )

        # Output Directories & External Paths
        self.wheel_output_edit.setText(self.settings.get("wheel_output_dir", ""))
        self.vcvars_edit.setText(self.settings.get("vcvars_path", ""))

        # Restore collapsible group expansion state
        expanded = self.settings.get("pypi_build_expanded", True)
        self.build_group.is_expanded = expanded
        self.build_group.content_widget.setVisible(expanded)
        self.build_group._update_title()

        # Apply enabled/disabled state of advanced widgets based on checkbox
        self._toggle_advanced_build_widgets(self.build_enabled_cb.isChecked())

        # Sync the Build Wheel button's enabled state with the loaded package manager
        self.pypi_build_wheel_btn.setEnabled(True)

    def _save_global_settings(self):
        self.settings.set("global_package_manager", self.global_pm_combo.currentText())
        self.settings.set("pypi_package_manager", self.pypi_pm_combo.currentText())
        self.settings.set("conda_channel", self.conda_channel_combo.currentText())
        self.settings.set(
            "global_selected_packages", self.global_selected_pkg_edit.text().strip()
        )
        self.settings.set("pypi_search_package", self.pypi_search_edit.text().strip())
        self.settings.set("conda_search_package", self.conda_search_edit.text().strip())

        # Advanced Build Settings
        self.settings.set("pypi_build_enabled", self.build_enabled_cb.isChecked())
        self.settings.set("pypi_cmake_args", self.pypi_cmake_args_edit.text().strip())
        self.settings.set("pypi_no_cache", self.pypi_no_cache_cb.isChecked())
        self.settings.set(
            "pypi_force_reinstall", self.pypi_force_reinstall_cb.isChecked()
        )
        self.settings.set("pypi_upgrade", self.pypi_upgrade_cb.isChecked())

        # CMake presets
        self.settings.set("cmake_ninja", self.cmake_ninja_cb.isChecked())
        self.settings.set("cmake_cuda", self.cmake_cuda_cb.isChecked())
        self.settings.set("cmake_metal", self.cmake_metal_cb.isChecked())
        self.settings.set("cmake_vulkan", self.cmake_vulkan_cb.isChecked())
        self.settings.set("cmake_openblas", self.cmake_openblas_cb.isChecked())
        self.settings.set("cmake_clblast", self.cmake_clblast_cb.isChecked())
        self.settings.set(
            "cmake_unsupported_compiler", self.cmake_unsupported_compiler_cb.isChecked()
        )

        # Output Directories & External Paths
        self.settings.set("wheel_output_dir", self.wheel_output_edit.text().strip())
        self.settings.set("vcvars_path", self.vcvars_edit.text().strip())

        # Expansion state
        self.settings.set("pypi_build_expanded", self.build_group.is_expanded)

    def _browse_pypi_req_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Requirements File", "", "Requirements/Project (*.txt *.toml);;All Files (*)"
        )
        if path:
            self.pypi_search_edit.setText(path)

    def _browse_conda_req_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Conda Requirements File", "", "Requirements (*.txt *.yml *.yaml);;All Files (*)"
        )
        if path:
            self.conda_search_edit.setText(path)