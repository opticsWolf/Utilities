import sys
import os
import json
from PySide6.QtWidgets import (QDockWidget, QScrollArea, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLineEdit, QPushButton, QComboBox, 
                               QLabel, QTabWidget, QListWidget, QMessageBox)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment

class GlobalPackagesMixin:
    """Manages the global packages functionality (PyPI, Conda Search, Multi-Uninstall, Update)."""

    def _build_global_packages_dock(self):
        global_dock = QDockWidget("Global Package Management", self)
        global_dock.setObjectName("globalPackagesDock")   # For restoreState()
        global_dock.setMinimumSize(320, 300)
        global_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        global_dock.setFeatures(QDockWidget.DockWidgetMovable)

        global_scroll = QScrollArea()
        global_scroll.setWidgetResizable(True)
        global_scroll.setFrameShape(QScrollArea.NoFrame)
        global_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        global_widget = QWidget()
        global_layout = QVBoxLayout(global_widget)

        global_tabs = QTabWidget()

        # --- TAB 1: PyPI Search & Install (only pip and uv pip) ---
        tab_pypi = QWidget()
        pypi_layout = QVBoxLayout(tab_pypi)
        
        # Package manager selector for PyPI installs
        pypi_pm_layout = QHBoxLayout()
        pypi_pm_layout.addWidget(QLabel("Package manager for PyPI:"))
        self.pypi_pm_combo = QComboBox()
        self.pypi_pm_combo.setToolTip("Select the package manager to use when installing from PyPI.")
        self.pypi_pm_combo.addItems(["pip", "uv pip"])   # only pip and uv pip
        self.pypi_pm_combo.currentTextChanged.connect(self.save_current_settings)
        pypi_pm_layout.addWidget(self.pypi_pm_combo)
        pypi_pm_layout.addStretch()
        pypi_layout.addLayout(pypi_pm_layout)

        # Search box
        pypi_search_layout = QHBoxLayout()
        self.pypi_search_edit = QLineEdit()
        self.pypi_search_edit.setPlaceholderText("e.g. requests")
        self.pypi_search_edit.setToolTip("Enter the exact package name to look up on PyPI.")
        self.pypi_search_edit.returnPressed.connect(self.search_pypi_info)
        
        pypi_search_btn = QPushButton("🔍")
        pypi_search_btn.setToolTip("Search for this package on PyPI (You can also press Enter).")
        pypi_search_btn.clicked.connect(self.search_pypi_info)
        self._style_square_icon_button(pypi_search_btn)   # <-- ADD THIS
        
        pypi_search_layout.addWidget(self.pypi_search_edit)
        pypi_search_layout.addWidget(pypi_search_btn)
        pypi_layout.addLayout(pypi_search_layout)

        self.pypi_info_label = QLabel("Enter a package name to search.")
        self.pypi_info_label.setWordWrap(True)
        pypi_layout.addWidget(self.pypi_info_label)

        self.pypi_install_btn = QPushButton("🌐 Install from PyPI")
        self._setup_button(self.pypi_install_btn, "Install this package from PyPI using the selected package manager.")
        self._style_critical_button(self.pypi_install_btn, "#0277BD", "#01579B")
        self.pypi_install_btn.clicked.connect(self.install_from_pypi)
        pypi_layout.addWidget(self.pypi_install_btn)
        pypi_layout.addStretch()
        global_tabs.addTab(tab_pypi, "PyPI Install")

        # --- TAB 2: Conda Search & Install (with channel selector) ---
        tab_conda = QWidget()
        conda_layout = QVBoxLayout(tab_conda)
        
        # Channel selector for Conda installs
        conda_channel_layout = QHBoxLayout()
        conda_channel_layout.addWidget(QLabel("Conda channel:"))
        self.conda_channel_combo = QComboBox()
        self.conda_channel_combo.setToolTip("Select the Conda channel/repository to install from.")
        self.conda_channel_combo.setEditable(True)  # allow custom channel input
        self.conda_channel_combo.addItems(["conda-forge", "defaults", "bioconda", "anaconda", "pytorch", "nvidia"])
        self.conda_channel_combo.currentTextChanged.connect(self.save_current_settings)
        conda_channel_layout.addWidget(self.conda_channel_combo)
        conda_channel_layout.addStretch()
        conda_layout.addLayout(conda_channel_layout)
        
        # Search box
        conda_search_layout = QHBoxLayout()
        self.conda_search_edit = QLineEdit()
        self.conda_search_edit.setPlaceholderText("e.g. numpy")
        self.conda_search_edit.setToolTip("Enter the exact package name to look up on Conda.")
        self.conda_search_edit.returnPressed.connect(self.search_conda_info)
        
        conda_search_btn = QPushButton("🔍")
        conda_search_btn.setToolTip("Search for this package on Conda (You can also press Enter).")
        conda_search_btn.clicked.connect(self.search_conda_info)
        self._style_square_icon_button(conda_search_btn)   # <-- ADD THIS
        
        conda_search_layout.addWidget(self.conda_search_edit)
        conda_search_layout.addWidget(conda_search_btn)
        conda_layout.addLayout(conda_search_layout)

        self.conda_info_label = QLabel("Enter a package name to search via conda.")
        self.conda_info_label.setWordWrap(True)
        conda_layout.addWidget(self.conda_info_label)

        self.conda_install_btn = QPushButton("🌐 Install via Conda")
        self._setup_button(self.conda_install_btn, "Install this package using Conda (only for Conda environments).")
        self._style_critical_button(self.conda_install_btn, "#00796B", "#004D40")
        self.conda_install_btn.clicked.connect(self.install_from_conda_tab)
        conda_layout.addWidget(self.conda_install_btn)
        conda_layout.addStretch()
        global_tabs.addTab(tab_conda, "Conda Install")

        # --- TAB 3: Installed Packages (Multi-Uninstall & Update) ---
        tab_installed = QWidget()
        installed_layout = QVBoxLayout(tab_installed)
        
        # Manager for uninstall/update (dropdown) placed ABOVE the refresh button
        manager_layout = QHBoxLayout()
        manager_layout.addWidget(QLabel("Package Manager (uninstall/update):"))
        self.global_pm_combo = QComboBox()
        self.global_pm_combo.setToolTip("Package manager to use for uninstalling or updating packages.")
        self.global_pm_combo.addItems(["pip", "conda", "uv pip"])
        self.global_pm_combo.currentTextChanged.connect(self.save_current_settings)
        manager_layout.addWidget(self.global_pm_combo)
        manager_layout.addStretch()
        installed_layout.addLayout(manager_layout)
        
        # Refresh button
        self.refresh_installed_btn = QPushButton("🔄 Fetch Installed Packages")
        self.refresh_installed_btn.setToolTip("Get a list of all installed packages in the active environment.")
        self.refresh_installed_btn.clicked.connect(self.refresh_installed_packages)
        installed_layout.addWidget(self.refresh_installed_btn)

        self.installed_list = QListWidget()
        self.installed_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.installed_list.setToolTip("Click and drag or hold Ctrl/Shift to select multiple packages.")
        self.installed_list.itemSelectionChanged.connect(self._on_installed_selection_changed)
        installed_layout.addWidget(self.installed_list)

        # Single text widget for selected packages (used by both update and uninstall)
        selected_pkg_layout = QHBoxLayout()
        selected_pkg_layout.addWidget(QLabel("Package(s) selected:"))
        self.global_selected_pkg_edit = QLineEdit()
        self.global_selected_pkg_edit.setToolTip("Space-separated list of packages (auto-filled by selection).")
        self.global_selected_pkg_edit.textChanged.connect(self.save_current_settings)
        selected_pkg_layout.addWidget(self.global_selected_pkg_edit)
        installed_layout.addLayout(selected_pkg_layout)

        # Update button (first)
        self.global_update_btn = QPushButton("🔄 Update Selected")
        self._setup_button(self.global_update_btn, "Update the selected package(s) to the latest version.")
        self._style_critical_button(self.global_update_btn, "#FF8C00", "#E67E00")  # Orange
        self.global_update_btn.clicked.connect(self.update_global_packages)
        installed_layout.addWidget(self.global_update_btn)

        # Uninstall button (second)
        self.global_uninstall_btn = QPushButton("🗑️ Uninstall Selected")
        self._setup_button(self.global_uninstall_btn, "Uninstall the selected package(s) simultaneously.")
        self._style_critical_button(self.global_uninstall_btn, "#D32F2F", "#C62828")
        self.global_uninstall_btn.clicked.connect(self.uninstall_global_packages)
        installed_layout.addWidget(self.global_uninstall_btn)

        installed_layout.addStretch()
        global_tabs.addTab(tab_installed, "Installed")

        global_layout.addWidget(global_tabs)
        
        global_scroll.setWidget(global_widget)
        global_dock.setWidget(global_scroll)
        return global_dock

    def _load_global_settings(self):
        # Block signals for combos to prevent premature saves
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

        self.global_selected_pkg_edit.setText(self.settings.get("global_selected_packages", ""))
        self.pypi_search_edit.setText(self.settings.get("pypi_search_package", ""))
        self.conda_search_edit.setText(self.settings.get("conda_search_package", ""))

    def _save_global_settings(self):
        self.settings.set("global_package_manager", self.global_pm_combo.currentText())
        self.settings.set("pypi_package_manager", self.pypi_pm_combo.currentText())
        self.settings.set("conda_channel", self.conda_channel_combo.currentText())
        self.settings.set("global_selected_packages", self.global_selected_pkg_edit.text().strip())
        self.settings.set("pypi_search_package", self.pypi_search_edit.text().strip())
        self.settings.set("conda_search_package", self.conda_search_edit.text().strip())

    def uninstall_global_packages(self):
        pkg_text = self.global_selected_pkg_edit.text().strip()
        if not pkg_text:
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Uninstall",
            f"Are you sure you want to uninstall the following package(s)?\n\n{pkg_text}\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.save_current_settings()
        pm = self.global_pm_combo.currentText()
        env_data = self.get_selected_env_data()
        if not env_data:
            return

        pkgs = pkg_text.split()

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", ["uninstall", "-y"] + pkgs)
        elif pm == "conda":
            if env_data["type"] == "venv":
                QMessageBox.warning(self, "Invalid Environment", "Conda uninstall only works in Conda environments.")
                return
            program = env_data["exe"]
            args = ["remove", "-n", env_data["name"], "-y"] + pkgs
        elif pm == "uv pip":
            program, args, _ = self._build_env_command("uv", ["pip", "uninstall"] + pkgs)
        else:
            return

        if program:
            self.run_command(program, args, None, f"{pm} uninstall {' '.join(pkgs)}", env_data, refresh_packages=True)

    def update_global_packages(self):
        pkg_text = self.global_selected_pkg_edit.text().strip()
        if not pkg_text:
            return

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Update",
            f"Are you sure you want to update the following package(s) to the latest version?\n\n{pkg_text}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.save_current_settings()
        pm = self.global_pm_combo.currentText()
        env_data = self.get_selected_env_data()
        if not env_data:
            return

        pkgs = pkg_text.split()

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", ["install", "--upgrade"] + pkgs)
        elif pm == "uv pip":
            program, args, _ = self._build_env_command("uv", ["pip", "install", "--upgrade"] + pkgs)
        elif pm == "conda":
            if env_data["type"] == "venv":
                QMessageBox.warning(self, "Invalid Environment", "Conda update only works in Conda environments.")
                return
            program = env_data["exe"]
            args = ["update", "-n", env_data["name"], "-y"]
            
            # Apply the channel defined in the Conda Install tab
            channel = self.conda_channel_combo.currentText().strip()
            if channel and channel != "defaults":
                args.extend(["-c", channel])
            
            # Append the packages at the end
            args.extend(pkgs)
        else:
            return

        if program:
            # Update the status text to show the channel being used (optional but helpful)
            cmd_display = f"{pm} update {' '.join(pkgs)}"
            if pm == "conda" and channel and channel != "defaults":
                cmd_display += f" (channel: {channel})"
                
            self.run_command(program, args, None, cmd_display, env_data, refresh_packages=True)

    def search_pypi_info(self):
        pkg = self.pypi_search_edit.text().strip()
        if not pkg: return
        self.pypi_info_label.setText("Searching PyPI...")
        
        code = f"""
import urllib.request, json
try:
    req = urllib.request.Request('https://pypi.org/pypi/{pkg}/json', headers={{'User-Agent': 'Mozilla/5.0'}})
    with urllib.request.urlopen(req, timeout=5) as r:
        d = json.loads(r.read().decode())
        v = d.get('info', {{}}).get('version', 'unknown')
        s = d.get('info', {{}}).get('summary', 'No summary')
        print(v + "|||" + s)
except Exception:
    print("NOT_FOUND")
"""
        self._pypi_proc = QProcess(self)
        self._pypi_proc_output = ""
        self._pypi_proc.readyReadStandardOutput.connect(
            lambda: setattr(self, '_pypi_proc_output', self._pypi_proc_output + self._pypi_proc.readAllStandardOutput().data().decode('utf-8'))
        )
        self._pypi_proc.finished.connect(self._on_pypi_search_finished)
        self._pypi_proc.start(sys.executable, ["-c", code])

    def _on_pypi_search_finished(self):
        out = self._pypi_proc_output.strip()
        if out == "NOT_FOUND" or not out:
            self.pypi_info_label.setText("Package not found on PyPI.")
        elif "|||" in out:
            v, s = out.split("|||", 1)
            self.pypi_info_label.setText(f"<b>Version:</b> {v}<br><b>Summary:</b> {s}")
        else:
            self.pypi_info_label.setText("Error retrieving info.")

    def install_from_pypi(self):
        self.save_current_settings()
        pkg_name = self.pypi_search_edit.text().strip()
        pm = self.pypi_pm_combo.currentText()
        env_data = self.get_selected_env_data()

        if not env_data or not pkg_name: return

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", ["install", pkg_name])
        elif pm == "uv pip":
            program, args, _ = self._build_env_command("uv", ["pip", "install", pkg_name])
        else:
            return

        if program:
            self.run_command(program, args, None, f"{pm} install {pkg_name}", env_data, refresh_packages=True)

    def search_conda_info(self):
        pkg = self.conda_search_edit.text().strip()
        if not pkg: return
        
        env_data = self.get_selected_env_data()
        conda_exe = self._current_conda_exe
        if env_data and env_data.get("type") == "conda":
            conda_exe = env_data.get("exe", conda_exe)
            
        if not conda_exe:
            self.conda_info_label.setText("Conda executable not found. Please ensure a conda environment is available.")
            return

        channel = self.conda_channel_combo.currentText().strip()
        self.conda_info_label.setText(f"Searching Conda (channel: {channel})...")
        
        args = ["search", pkg, "--json"]
        if channel and channel != "defaults":
            args.extend(["-c", channel])
        
        self._conda_proc = QProcess(self)
        self._conda_proc_output = ""
        self._conda_proc.readyReadStandardOutput.connect(
            lambda: setattr(self, '_conda_proc_output', self._conda_proc_output + self._conda_proc.readAllStandardOutput().data().decode('utf-8', errors='replace'))
        )
        self._conda_proc.finished.connect(self._on_conda_search_finished)
        self._conda_proc.start(conda_exe, args)

    def _on_conda_search_finished(self):
        out = self._conda_proc_output.strip()
        try:
            data = json.loads(out)
            if "error" in data:
                self.conda_info_label.setText(f"Error: {data.get('error')}")
                return
            
            pkg = self.conda_search_edit.text().strip()
            key_to_use = pkg if pkg in data else list(data.keys())[0] if data else None
            
            if key_to_use and len(data[key_to_use]) > 0:
                latest = data[key_to_use][-1] 
                v = latest.get("version", "unknown")
                c = latest.get("channel", "unknown")
                b = latest.get("build", "unknown")
                self.conda_info_label.setText(f"<b>Version:</b> {v}<br><b>Build:</b> {b}<br><b>Channel:</b> {c}")
            else:
                self.conda_info_label.setText("Package found but no version info available.")
        except Exception:
            self.conda_info_label.setText("Package not found or error parsing results.")

    def install_from_conda_tab(self):
        self.save_current_settings()
        pkg_name = self.conda_search_edit.text().strip()
        env_data = self.get_selected_env_data()

        if not env_data or not pkg_name: return
        
        if env_data["type"] != "conda":
            QMessageBox.warning(self, "Invalid Environment", "You must select a Conda environment to use 'Install via Conda'.")
            return

        program = env_data["exe"]
        channel = self.conda_channel_combo.currentText().strip()
        args = ["install", "-n", env_data["name"], pkg_name, "-y"]
        if channel and channel != "defaults":
            args.extend(["-c", channel])
            
        self.run_command(program, args, None, f"conda install {pkg_name} (channel: {channel})", env_data, refresh_packages=True)

    def refresh_installed_packages(self):
        pm = self.global_pm_combo.currentText()
        env_data = self.get_selected_env_data()
        if not env_data: return

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", ["list", "--format=json"])
        elif pm == "uv pip":
            program, args, _ = self._build_env_command("uv", ["pip", "list", "--format=json", "--quiet"])
        elif pm == "conda":
            if env_data["type"] == "venv":
                self.installed_list.clear()
                self.installed_list.addItem("Conda list not available for venvs.")
                return
            program = env_data["exe"]
            args = ["list", "-n", env_data["name"], "--json"]
        else:
            return

        if not program: return

        self.refresh_installed_btn.setEnabled(False)
        self.refresh_installed_btn.setText("🔄 Fetching...")
        self.installed_list.clear()
        
        self._list_proc = QProcess(self)
        self._list_proc.setProcessChannelMode(QProcess.MergedChannels)
        
        qenv = QProcessEnvironment.systemEnvironment()
        if env_data and env_data.get("type") == "venv":
            path_val = env_data["path"]
            venv_bin = os.path.join(path_val, "Scripts" if os.name == "nt" else "bin")
            qenv.insert("VIRTUAL_ENV", path_val)
            qenv.insert("PATH", venv_bin + os.pathsep + qenv.value("PATH"))
        self._list_proc.setProcessEnvironment(qenv)
        
        self._list_proc_output = ""
        self._list_proc.readyReadStandardOutput.connect(
            lambda: setattr(self, '_list_proc_output', self._list_proc_output + self._list_proc.readAllStandardOutput().data().decode('utf-8', errors='replace'))
        )
        self._list_proc.finished.connect(self._on_list_proc_finished)
        self._list_proc.start(program, args)

    def _on_list_proc_finished(self):
        self.refresh_installed_btn.setEnabled(True)
        self.refresh_installed_btn.setText("🔄 Fetch Installed Packages")
        
        output = self._list_proc_output
        
        start = output.find('[')
        end = output.rfind(']')
        if start == -1 or end == -1 or end <= start:
            self.installed_list.addItem("No valid JSON data found.")
            return
        
        json_str = output[start:end+1]
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.installed_list.addItem(f"Failed to parse data: {e}")
            print(f"JSON parse error. Snippet: {json_str[:200]}")
            return
        
        if isinstance(data, list):
            for item in data:
                name = item.get("name", "")
                version = item.get("version", "")
                if name:
                    self.installed_list.addItem(f"{name} ({version})")
                else:
                    self.installed_list.addItem(str(item))
        else:
            self.installed_list.addItem("Unexpected data format (not a list).")

    def _on_installed_selection_changed(self):
        selected_items = self.installed_list.selectedItems()
        pkg_names = [item.text().split(' ')[0] for item in selected_items]
        self.global_selected_pkg_edit.setText(" ".join(pkg_names))