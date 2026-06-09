import os
import glob
from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QComboBox,
    QLabel,
)
from PySide6.QtCore import Qt


class LocalPackagesMixin:
    """Manages the UI logic for interacting with locally compiled Wheels."""

    def _build_local_packages_dock(self):
        pkg_dock = QDockWidget("Package Management", self)
        pkg_dock.setObjectName("localPackagesDock")  # For restoreState()
        pkg_dock.setMinimumSize(280, 250)  # min width/height
        pkg_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        pkg_dock.setFeatures(QDockWidget.DockWidgetMovable)

        pkg_widget = QWidget()
        pkg_layout = QVBoxLayout(pkg_widget)

        pm_layout = QHBoxLayout()
        pm_layout.addWidget(QLabel("Package manager:"))
        self.package_manager_combo = QComboBox()
        self.package_manager_combo.setToolTip(
            "Select the package manager to use for installing local wheels and basic uninstalling."
        )
        self.package_manager_combo.addItems(["pip", "conda", "uv pip"])
        self.package_manager_combo.currentTextChanged.connect(
            self.save_current_settings
        )
        pm_layout.addWidget(self.package_manager_combo)
        pm_layout.addStretch()
        pkg_layout.addLayout(pm_layout)

        # --- Local Wheels Group ---
        wheels_group = QGroupBox("Install Wheels (Project folder)")
        wheels_layout = QVBoxLayout(wheels_group)

        self.refresh_wheels_btn = QPushButton("🔄 Refresh Wheels")
        self._setup_button(
            self.refresh_wheels_btn,
            "Manually reload the list of generated wheels from target/wheels/ or recursively from the project folder.",
        )
        self.refresh_wheels_btn.clicked.connect(self.refresh_wheel_list)
        wheels_layout.addWidget(self.refresh_wheels_btn)

        self.wheels_combo = QComboBox()
        self.wheels_combo.setToolTip("Select a wheel to install.")
        wheels_layout.addWidget(self.wheels_combo)

        self.install_btn = QPushButton("📥 Install Selected Wheel")
        self._setup_button(
            self.install_btn, "Install the selected wheel into the current environment."
        )
        self._style_critical_button(self.install_btn, "#388E3C", "#2E7D32")  # Green
        self.install_btn.clicked.connect(self.install_wheel)
        wheels_layout.addWidget(self.install_btn)

        pkg_layout.addWidget(wheels_group)

        # --- Local Uninstall Group ---
        uninstall_group = QGroupBox("Uninstall")
        uninstall_layout = QVBoxLayout(uninstall_group)

        self.copy_package_name_btn = QPushButton("📋 Extract name for Uninstall")
        self._setup_button(
            self.copy_package_name_btn,
            "Extracts the package name from the selected wheel above and sets it in the input below.",
        )
        self.copy_package_name_btn.clicked.connect(self.copy_package_name_from_wheel)
        uninstall_layout.addWidget(self.copy_package_name_btn)

        uninstall_name_layout = QHBoxLayout()
        uninstall_name_layout.addWidget(QLabel("Package Name:"))
        self.uninstall_name_edit = QLineEdit()
        self.uninstall_name_edit.setToolTip(
            "Enter the exact name of the Python package you want to uninstall."
        )
        self.uninstall_name_edit.textChanged.connect(self.save_current_settings)
        uninstall_name_layout.addWidget(self.uninstall_name_edit)
        uninstall_layout.addLayout(uninstall_name_layout)

        self.uninstall_btn = QPushButton("🗑️ Uninstall")
        self._setup_button(
            self.uninstall_btn,
            "Uninstall the specified package from the active environment.",
        )
        self._style_critical_button(self.uninstall_btn, "#D32F2F", "#C62828")  # Red
        self.uninstall_btn.clicked.connect(self.uninstall_package)
        uninstall_layout.addWidget(self.uninstall_btn)

        pkg_layout.addWidget(uninstall_group)
        pkg_layout.addStretch()

        pkg_dock.setWidget(pkg_widget)
        return pkg_dock

    def _load_local_settings(self):
        pm = self.settings.get("package_manager", "pip")
        idx = self.package_manager_combo.findText(pm)
        if idx >= 0:
            self.package_manager_combo.blockSignals(True)
            self.package_manager_combo.setCurrentIndex(idx)
            self.package_manager_combo.blockSignals(False)

        self.uninstall_name_edit.setText(
            self.settings.get("uninstall_package_name", "")
        )

    def _save_local_settings(self):
        self.settings.set("package_manager", self.package_manager_combo.currentText())
        self.settings.set(
            "uninstall_package_name", self.uninstall_name_edit.text().strip()
        )
        # Save the full path (user data) of the selected wheel
        selected_wheel = self.wheels_combo.currentData()
        if selected_wheel and os.path.exists(selected_wheel):
            self.settings.set("last_selected_wheel", selected_wheel)

    def refresh_wheel_list(self):
        project_folder = self.folder_edit.text().strip()
        if not project_folder or not os.path.isdir(project_folder):
            self.wheels_combo.clear()
            self.wheels_combo.addItem("No project folder selected")
            return

        wheel_files = []
        # 1) Primary location: target/wheels/
        primary_dir = os.path.join(project_folder, "target", "wheels")
        if os.path.isdir(primary_dir):
            primary_wheels = glob.glob(os.path.join(primary_dir, "*.whl"))
            if primary_wheels:
                wheel_files = primary_wheels

        # 2) If primary had no wheels, recursively search the whole project folder
        if not wheel_files:
            # Folders to skip (virtual environments, cache, build dirs)
            skip_dirs = {"venv", ".venv", "env", ".env", "__pycache__", "build", "dist"}
            for root, dirs, files in os.walk(project_folder):
                # Modify dirs in-place to skip unwanted folders
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for file in files:
                    if file.endswith(".whl"):
                        full_path = os.path.join(root, file)
                        wheel_files.append(full_path)

        if not wheel_files:
            self.wheels_combo.clear()
            self.wheels_combo.addItem("No wheel files found")
            return

        # Sort by modification time (newest first)
        wheel_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

        self.wheels_combo.clear()
        for wf in wheel_files:
            # Display relative path to project folder, keep full path as user data
            rel_path = os.path.relpath(wf, project_folder)
            self.wheels_combo.addItem(rel_path, userData=wf)

        # Restore previously selected wheel (if any)
        last_selected = self.settings.get("last_selected_wheel")
        if last_selected and os.path.exists(last_selected):
            for i in range(self.wheels_combo.count()):
                if self.wheels_combo.itemData(i) == last_selected:
                    self.wheels_combo.setCurrentIndex(i)
                    break

    def copy_package_name_from_wheel(self):
        # Use full path from user data
        wheel_path = self.wheels_combo.currentData()
        if not wheel_path or not wheel_path.endswith(".whl"):
            return
        # Extract package name (first part before the first dash)
        base_name = os.path.basename(wheel_path)
        pkg_name = base_name.split("-")[0]
        self.uninstall_name_edit.setText(pkg_name)
        self.save_current_settings()

    def uninstall_package(self):
        self.save_current_settings()
        pkg_name = self.uninstall_name_edit.text().strip()
        pm = self.package_manager_combo.currentText()
        if not pkg_name:
            return

        env_data = self.get_selected_env_data()
        if not env_data:
            return

        if pm == "pip":
            program, args, _ = self._build_env_command(
                "pip", ["uninstall", pkg_name, "-y"]
            )
        elif pm == "conda":
            if env_data["type"] == "venv":
                return
            program = env_data["exe"]
            args = ["remove", "-n", env_data["name"], pkg_name, "-y"]
        elif pm == "uv pip":
            program, args, _ = self._build_env_command(
                "uv", ["pip", "uninstall", pkg_name]
            )
        else:
            return

        if program:
            self.run_command(
                program, args, None, f"{pm} uninstall {pkg_name}", env_data
            )

    def install_wheel(self):
        self.save_current_settings()
        # Get full wheel path from user data
        wheel_path = self.wheels_combo.currentData()
        pm = self.package_manager_combo.currentText()
        env_data = self.get_selected_env_data()

        if not env_data or not wheel_path or not os.path.isfile(wheel_path):
            return

        if pm in ["pip", "conda"]:
            program, args, _ = self._build_env_command("pip", ["install", wheel_path])
        elif pm == "uv pip":
            program, args, _ = self._build_env_command(
                "uv", ["pip", "install", wheel_path]
            )
        else:
            return

        if program:
            self.run_command(
                program,
                args,
                None,
                f"{pm} install {os.path.basename(wheel_path)}",
                env_data,
            )