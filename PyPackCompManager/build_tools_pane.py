import os
from PySide6.QtWidgets import (QDockWidget, QScrollArea, QWidget, QVBoxLayout, 
                               QHBoxLayout, QFormLayout, QTabWidget,
                               QGroupBox, QLineEdit, QPushButton, 
                               QComboBox, QCheckBox, QLabel)
from PySide6.QtCore import Qt


class BuildToolsMixin:
    """Manages the Cargo and Maturin compilation commands and CPU targeting."""

    # CPU presets
    CPU_PRESETS = {
        "x86": ["(none)", "native", "x86-64-v2", "x86-64-v3", "x86-64-v4"],
        "arm": ["(none)", "native", "apple-m1", "apple-m2", "apple-m3", "cortex-a72", "cortex-a53"],
        "generic": ["(none)", "native"]
    }

    def _build_tools_dock(self):
        build_dock = QDockWidget("Rust Build Tools", self)
        build_dock.setObjectName("buildToolsDock")   # For restoreState()
        build_dock.setMinimumSize(350, 300)
        build_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        build_dock.setFeatures(QDockWidget.DockWidgetMovable)
    
        build_scroll = QScrollArea()
        build_scroll.setWidgetResizable(True)
        build_scroll.setFrameShape(QScrollArea.NoFrame)
        build_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    
        build_widget = QWidget()
        build_layout = QVBoxLayout(build_widget)
    
        # ---- Common Architecture & CPU Group ----
        arch_cpu_group = QGroupBox("Architecture")
        arch_cpu_layout = QFormLayout(arch_cpu_group)
    
        self.maturin_target_combo = QComboBox()
        self.maturin_target_combo.setEditable(True)
        self.maturin_target_combo.setToolTip("The system architecture to compile for (e.g., x86_64, aarch64).")
        self.maturin_target_combo.addItems([
            "(default)", "x86_64", "aarch64", "armv7", "universal2-apple-darwin",
            "x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"
        ])
        self.maturin_target_combo.currentTextChanged.connect(self._on_architecture_changed)
        arch_cpu_layout.addRow("Target Architecture:", self.maturin_target_combo)
    
        self.rust_cpu_combo = QComboBox()
        self.rust_cpu_combo.setToolTip("Specific CPU architecture to optimize for (-C target-cpu). 'native' uses the host's CPU.")
        # Initial placeholder items – will be replaced when architecture changes
        self.rust_cpu_combo.addItems(["(none)", "native"])
        arch_cpu_layout.addRow("Target CPU:", self.rust_cpu_combo)
    
        self.rust_features_edit = QLineEdit()
        self.rust_features_edit.setPlaceholderText("e.g., +avx2,+bmi2")
        self.rust_features_edit.setToolTip("Hardware specific target features to enable (-C target-feature).")
        arch_cpu_layout.addRow("Target Features:", self.rust_features_edit)
    
        build_layout.addWidget(arch_cpu_group)
    
        # ---- Tab Widget for Cargo and Maturin ----
        build_tabs = QTabWidget()
        
        # ---------- Maturin Tab ----------
        maturin_tab = QWidget()
        maturin_layout = QVBoxLayout(maturin_tab)
    
        maturin_group = QGroupBox("Maturin Flags (for 'maturin build')")
        maturin_flags_layout = QVBoxLayout(maturin_group)
    
        maturin_form = QFormLayout()
        self.maturin_auditwheel_combo = QComboBox()
        self.maturin_auditwheel_combo.setToolTip("Linux only: Repair the wheel for broader compatibility using auditwheel.")
        self.maturin_auditwheel_combo.addItems(["(default)", "repair", "skip", "check"])
        maturin_form.addRow("Auditwheel:", self.maturin_auditwheel_combo)
        maturin_flags_layout.addLayout(maturin_form)
    
        self.maturin_release_cb = QCheckBox("--release")
        self.maturin_release_cb.setToolTip("Build the Python wheel in release mode with optimizations.")
        self.maturin_strip_cb = QCheckBox("--strip")
        self.maturin_strip_cb.setToolTip("Strip symbols from the compiled library for minimum file size.")
        self.maturin_sdist_cb = QCheckBox("--sdist")
        self.maturin_sdist_cb.setToolTip("Build a source distribution (.tar.gz) alongside the wheel.")
        self.maturin_no_default_features_cb = QCheckBox("--no-default-features")
        self.maturin_no_default_features_cb.setToolTip("Disable the default Rust features defined in the project's Cargo.toml.")
    
        maturin_extra_layout = QHBoxLayout()
        maturin_extra_layout.addWidget(QLabel("Extra args:"))
        self.maturin_extra_edit = QLineEdit()
        self.maturin_extra_edit.setToolTip("Any additional arguments to pass to 'maturin build'.")
        maturin_extra_layout.addWidget(self.maturin_extra_edit)
    
        maturin_flags_layout.addWidget(self.maturin_release_cb)
        maturin_flags_layout.addWidget(self.maturin_strip_cb)
        maturin_flags_layout.addWidget(self.maturin_sdist_cb)
        maturin_flags_layout.addWidget(self.maturin_no_default_features_cb)
        maturin_flags_layout.addLayout(maturin_extra_layout)
    
        self.run_maturin_btn = QPushButton("📦 Run Maturin Build")
        self._setup_button(self.run_maturin_btn, "Build Python wheels using Maturin in the selected environment.")
        self._style_critical_button(self.run_maturin_btn, "#6A5ACD", "#5F4FBD")
        self.run_maturin_btn.clicked.connect(self.run_maturin)
        maturin_flags_layout.addWidget(self.run_maturin_btn)   
 
        # ---------- Cargo Tab ----------
        cargo_tab = QWidget()
        cargo_layout = QVBoxLayout(cargo_tab)
    
        cargo_group = QGroupBox("Cargo Commands & Flags")
        cargo_flags_layout = QVBoxLayout(cargo_group)
    
        cargo_form = QFormLayout()
        self.cargo_cmd_combo = QComboBox()
        self.cargo_cmd_combo.setToolTip("Standard cargo commands.")
        self.cargo_cmd_combo.addItems(["build", "test", "check", "run", "clean"])
        cargo_form.addRow("Command:", self.cargo_cmd_combo)
        cargo_flags_layout.addLayout(cargo_form)
    
        self.cargo_release_cb = QCheckBox("--release")
        self.cargo_release_cb.setToolTip("Build artifacts in release mode, with optimizations (slower build, faster execution).")
        self.cargo_verbose_cb = QCheckBox("--verbose")
        self.cargo_verbose_cb.setToolTip("Use verbose output, providing more detailed logging during the build.")
        self.cargo_all_features_cb = QCheckBox("--all-features")
        self.cargo_all_features_cb.setToolTip("Activate all available features of the selected package defined in Cargo.toml.")
        self.cargo_no_default_features_cb = QCheckBox("--no-default-features")
        self.cargo_no_default_features_cb.setToolTip("Do not activate the 'default' feature.")
    
        cargo_extra_layout = QHBoxLayout()
        cargo_extra_layout.addWidget(QLabel("Extra args:"))
        self.cargo_extra_edit = QLineEdit()
        self.cargo_extra_edit.setToolTip("Any additional arguments you want to pass to the Cargo command.")
        cargo_extra_layout.addWidget(self.cargo_extra_edit)
    
        cargo_flags_layout.addWidget(self.cargo_release_cb)
        cargo_flags_layout.addWidget(self.cargo_verbose_cb)
        cargo_flags_layout.addWidget(self.cargo_all_features_cb)
        cargo_flags_layout.addWidget(self.cargo_no_default_features_cb)
        cargo_flags_layout.addLayout(cargo_extra_layout)
    
        self.run_cargo_btn = QPushButton("🛠️ Run Cargo")
        self._setup_button(self.run_cargo_btn, "Execute the configured Cargo command in the selected environment.")
        self._style_critical_button(self.run_cargo_btn, "#1976D2", "#1565C0")
        self.run_cargo_btn.clicked.connect(self.run_cargo)
        cargo_flags_layout.addWidget(self.run_cargo_btn)
      
        cargo_layout.addWidget(cargo_group)
        cargo_layout.addStretch()
            
        # ---------------------------------
    
        maturin_layout.addWidget(maturin_group)
        maturin_layout.addStretch()
        
        build_tabs.addTab(maturin_tab, "Maturin")
            
        build_tabs.addTab(cargo_tab, "Cargo")
    
        build_layout.addWidget(build_tabs)
        build_layout.addStretch()
    
        build_scroll.setWidget(build_widget)
        build_dock.setWidget(build_scroll)
        return build_dock

    def _load_build_settings(self):
        # 1. Restore the target architecture, but block signal to prevent premature save
        target_cmd = self.settings.get("maturin_target", "(default)")
        self.maturin_target_combo.blockSignals(True)
        self.maturin_target_combo.setCurrentText(target_cmd)
        self.maturin_target_combo.blockSignals(False)

        # Manually populate CPU combo based on the architecture
        self._on_architecture_changed(target_cmd)

        # 2. Restore CPU selection
        cpu_val = self.settings.get("rust_target_cpu", "(none)")
        idx = self.rust_cpu_combo.findText(cpu_val)
        if idx >= 0:
            self.rust_cpu_combo.setCurrentIndex(idx)
        # 3. Restore target features
        self.rust_features_edit.setText(self.settings.get("rust_target_features", ""))

        # 4. Cargo settings
        cargo_cmd = self.settings.get("cargo_command", "build")
        idx = self.cargo_cmd_combo.findText(cargo_cmd)
        if idx >= 0: self.cargo_cmd_combo.setCurrentIndex(idx)

        self.cargo_release_cb.setChecked(self.settings.get("cargo_release", True))
        self.cargo_verbose_cb.setChecked(self.settings.get("cargo_verbose", False))
        self.cargo_all_features_cb.setChecked(self.settings.get("cargo_all_features", False))
        self.cargo_no_default_features_cb.setChecked(self.settings.get("cargo_no_default_features", False))
        self.cargo_extra_edit.setText(self.settings.get("cargo_extra_args", ""))

        # 5. Maturin settings
        self.maturin_release_cb.setChecked(self.settings.get("maturin_release", True))
        self.maturin_strip_cb.setChecked(self.settings.get("maturin_strip", False))
        self.maturin_sdist_cb.setChecked(self.settings.get("maturin_sdist", False))
        self.maturin_no_default_features_cb.setChecked(self.settings.get("maturin_no_default_features", False))

        aw_cmd = self.settings.get("maturin_auditwheel", "(default)")
        idx = self.maturin_auditwheel_combo.findText(aw_cmd)
        if idx >= 0: self.maturin_auditwheel_combo.setCurrentIndex(idx)

        self.maturin_extra_edit.setText(self.settings.get("maturin_extra_args", ""))

    def _save_build_settings(self):
        self.settings.set("maturin_target", self.maturin_target_combo.currentText())
        self.settings.set("rust_target_cpu", self.rust_cpu_combo.currentText())
        self.settings.set("rust_target_features", self.rust_features_edit.text().strip())

        self.settings.set("cargo_command", self.cargo_cmd_combo.currentText())
        self.settings.set("cargo_release", self.cargo_release_cb.isChecked())
        self.settings.set("cargo_verbose", self.cargo_verbose_cb.isChecked())
        self.settings.set("cargo_all_features", self.cargo_all_features_cb.isChecked())
        self.settings.set("cargo_no_default_features", self.cargo_no_default_features_cb.isChecked())
        self.settings.set("cargo_extra_args", self.cargo_extra_edit.text().strip())
        
        self.settings.set("maturin_release", self.maturin_release_cb.isChecked())
        self.settings.set("maturin_strip", self.maturin_strip_cb.isChecked())
        self.settings.set("maturin_sdist", self.maturin_sdist_cb.isChecked())
        self.settings.set("maturin_no_default_features", self.maturin_no_default_features_cb.isChecked())
        self.settings.set("maturin_auditwheel", self.maturin_auditwheel_combo.currentText())
        self.settings.set("maturin_extra_args", self.maturin_extra_edit.text().strip())

    def _on_architecture_changed(self, text):
        # Save the currently selected CPU value before clearing (if any)
        current_cpu = self.rust_cpu_combo.currentText()
        self.rust_cpu_combo.clear()

        text_lower = text.lower()
        if "x86_64" in text_lower:
            key = "x86"
        elif "aarch64" in text_lower or "arm" in text_lower or "darwin" in text_lower:
            key = "arm"
        else:
            key = "generic"

        self.rust_cpu_combo.addItems(self.CPU_PRESETS[key])
        
        idx = self.rust_cpu_combo.findText(current_cpu)
        if idx >= 0:
            self.rust_cpu_combo.setCurrentIndex(idx)
        else:
            # Default to first item (usually "(none)")
            self.rust_cpu_combo.setCurrentIndex(0)
        self.save_current_settings()

    def _get_compiled_rustflags(self):
        flags = []
        cpu = self.rust_cpu_combo.currentText()
        if cpu != "(none)":
            flags.append(f"-C target-cpu={cpu}")
            
        features = self.rust_features_edit.text().strip()
        if features:
            flags.append(f"-C target-feature={features}")
            
        return " ".join(flags) if flags else None

    def run_cargo(self):
        self.save_current_settings()
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            return

        cmd = self.cargo_cmd_combo.currentText()
        base_args = [cmd]
        
        if cmd != "clean":
            if self.cargo_release_cb.isChecked():
                base_args.append("--release")
            if self.cargo_all_features_cb.isChecked():
                base_args.append("--all-features")
            if self.cargo_no_default_features_cb.isChecked():
                base_args.append("--no-default-features")
                
        if self.cargo_verbose_cb.isChecked():
            base_args.append("--verbose")
        extra = self.cargo_extra_edit.text().strip()
        if extra:
            base_args.extend(extra.split())
            
        program, args, env_data = self._build_env_command("cargo", base_args)
        if program:
            rustflags = self._get_compiled_rustflags()
            self.run_command(program, args, project_folder, f"Cargo {cmd}", env_data, rustflags=rustflags)

    def run_maturin(self):
        self.save_current_settings()
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            return

        base_args = ["build"]
        if self.maturin_release_cb.isChecked():
            base_args.append("--release")
        if self.maturin_strip_cb.isChecked():
            base_args.append("--strip")
        if self.maturin_sdist_cb.isChecked():
            base_args.append("--sdist")
        if self.maturin_no_default_features_cb.isChecked():
            base_args.append("--no-default-features")
            
        aw = self.maturin_auditwheel_combo.currentText()
        if aw != "(default)":
            base_args.extend(["--auditwheel", aw])
            
        tgt = self.maturin_target_combo.currentText()
        if tgt and tgt != "(default)":
            base_args.extend(["--target", tgt])
            
        extra = self.maturin_extra_edit.text().strip()
        if extra:
            base_args.extend(extra.split())
            
        program, args, env_data = self._build_env_command("maturin", base_args)
        if program:
            rustflags = self._get_compiled_rustflags()
            self.run_command(program, args, project_folder, "Maturin build", env_data, rustflags=rustflags)