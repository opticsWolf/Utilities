"""Conda operations and management of the installed-packages list.

Covers everything that acts against a selected environment's package set:
Conda search/install, listing installed packages, and multi-package
uninstall / update across pip, uv pip and conda.
"""

import os
import json

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import QMessageBox


class CondaInstalledMixin:
    """Conda search/install plus installed-list refresh, uninstall and update."""

    # ========== Conda Search ==========
    def search_conda_info(self):
        pkg = self.conda_search_edit.text().strip()
        if not pkg:
            return

        env_data = self.get_selected_env_data()
        conda_exe = self._current_conda_exe
        if env_data and env_data.get("type") == "conda":
            conda_exe = env_data.get("exe", conda_exe)

        if not conda_exe:
            self.conda_info_label.setText(
                "Conda executable not found. Please ensure a conda environment is available."
            )
            return

        channel = self.conda_channel_combo.currentText().strip()
        self.conda_info_label.setText(f"Searching Conda (channel: {channel})...")

        args = ["search", pkg, "--json"]
        if channel and channel != "defaults":
            args.extend(["-c", channel])

        self._conda_proc = QProcess(self)
        self._conda_proc_output = ""
        self._conda_proc.readyReadStandardOutput.connect(
            lambda: setattr(
                self,
                "_conda_proc_output",
                self._conda_proc_output
                + self._conda_proc.readAllStandardOutput()
                .data()
                .decode("utf-8", errors="replace"),
            )
        )
        self._conda_proc.finished.connect(self._on_conda_search_finished)
        self._conda_proc.errorOccurred.connect(self._on_conda_search_error)
        self._conda_proc.start(conda_exe, args)

    def _on_conda_search_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.conda_info_label.setText(
                "Could not start conda. Check that it is installed and on your PATH."
            )

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
                self.conda_info_label.setText(
                    f"<b>Version:</b> {v}<br><b>Build:</b> {b}<br><b>Channel:</b> {c}"
                )
            else:
                self.conda_info_label.setText(
                    "Package found but no version info available."
                )
        except Exception:
            self.conda_info_label.setText("Package not found or error parsing results.")

    # ========== Conda Install ==========
    def install_from_conda_tab(self):
        self.save_current_settings()
        pkg_name = self.conda_search_edit.text().strip()
        env_data = self.get_selected_env_data()

        if not env_data or not pkg_name:
            return

        if env_data["type"] != "conda":
            QMessageBox.warning(
                self,
                "Invalid Environment",
                "You must select a Conda environment to use 'Install via Conda'.",
            )
            return

        program = env_data["exe"]
        channel = self.conda_channel_combo.currentText().strip()
        args = ["install", "-n", env_data["name"], pkg_name, "-y"]
        if channel and channel != "defaults":
            args.extend(["-c", channel])

        self.run_command(
            program,
            args,
            None,
            f"conda install {pkg_name} (channel: {channel})",
            env_data,
            refresh_packages=True,
        )

    # ========== Installed Packages: listing ==========
    def refresh_installed_packages(self):
        pm = self.global_pm_combo.currentText()
        env_data = self.get_selected_env_data()
        if not env_data:
            return

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", ["list", "--format=json"])
        elif pm == "uv pip":
            program, args, _ = self._build_env_command(
                "uv", ["pip", "list", "--format=json", "--quiet"]
            )
        elif pm == "conda":
            if env_data["type"] == "venv":
                self.installed_list.clear()
                self.installed_list.addItem("Conda list not available for venvs.")
                return
            program = env_data["exe"]
            args = ["list", "-n", env_data["name"], "--json"]
        else:
            return

        if not program:
            return

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
            lambda: setattr(
                self,
                "_list_proc_output",
                self._list_proc_output
                + self._list_proc.readAllStandardOutput()
                .data()
                .decode("utf-8", errors="replace"),
            )
        )
        self._list_proc.finished.connect(self._on_list_proc_finished)
        self._list_proc.errorOccurred.connect(self._on_list_proc_error)
        self._list_proc.start(program, args)

    def _on_list_proc_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.refresh_installed_btn.setEnabled(True)
            self.refresh_installed_btn.setText("🔄 Fetch Installed Packages")
            self.installed_list.clear()
            self.installed_list.addItem(
                "Failed to start the package manager. Check that it is installed."
            )
            self._installed_packages_raw = []

    def _on_list_proc_finished(self):
        self.refresh_installed_btn.setEnabled(True)
        self.refresh_installed_btn.setText("🔄 Fetch Installed Packages")

        output = self._list_proc_output

        start = output.find("[")
        end = output.rfind("]")
        if start == -1 or end == -1 or end <= start:
            self.installed_list.addItem("No valid JSON data found.")
            self._installed_packages_raw = []
            return

        json_str = output[start : end + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            self.installed_list.addItem(f"Failed to parse data: {e}")
            self._installed_packages_raw = []
            return

        self._installed_packages_raw = []
        if isinstance(data, list):
            for item in data:
                name = item.get("name", "")
                version = item.get("version", "")
                if name:
                    display = f"{name} ({version})"
                    self._installed_packages_raw.append(display)
                else:
                    self._installed_packages_raw.append(str(item))
        else:
            self._installed_packages_raw.append("Unexpected data format (not a list).")

        self._update_installed_list()

    def _update_installed_list(self):
        """Refresh the list widget according to the current filter text."""
        self.installed_list.clear()
        filter_text = (
            self.installed_filter_edit.text().strip()
            if hasattr(self, "installed_filter_edit")
            else ""
        )
        if not filter_text:
            for display in self._installed_packages_raw:
                self.installed_list.addItem(display)
            return

        terms = filter_text.lower().split()
        for display in self._installed_packages_raw:
            lower_display = display.lower()
            if any(term in lower_display for term in terms):
                self.installed_list.addItem(display)

    def _filter_installed_packages(self):
        """Called when the filter text changes."""
        if hasattr(self, "_installed_packages_raw"):
            self._update_installed_list()

    def _on_installed_selection_changed(self):
        selected_items = self.installed_list.selectedItems()
        pkg_names = [item.text().split(" ")[0] for item in selected_items]
        self.global_selected_pkg_edit.setText(" ".join(pkg_names))

    # ========== Installed Packages: uninstall / update ==========
    def uninstall_global_packages(self):
        pkg_text = self.global_selected_pkg_edit.text().strip()
        if not pkg_text:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Uninstall",
            f"Are you sure you want to uninstall the following package(s)?\n\n{pkg_text}\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
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
            program, args, _ = self._build_env_command(
                "pip", ["uninstall", "-y"] + pkgs
            )
        elif pm == "conda":
            if env_data["type"] == "venv":
                QMessageBox.warning(
                    self,
                    "Invalid Environment",
                    "Conda uninstall only works in Conda environments.",
                )
                return
            program = env_data["exe"]
            args = ["remove", "-n", env_data["name"], "-y"] + pkgs
        elif pm == "uv pip":
            program, args, _ = self._build_env_command(
                "uv", ["pip", "uninstall"] + pkgs
            )
        else:
            return

        if program:
            self.run_command(
                program,
                args,
                None,
                f"{pm} uninstall {' '.join(pkgs)}",
                env_data,
                refresh_packages=True,
            )

    def update_global_packages(self):
        pkg_text = self.global_selected_pkg_edit.text().strip()
        if not pkg_text:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Update",
            f"Are you sure you want to update the following package(s) to the latest version?\n\n{pkg_text}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
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
            program, args, _ = self._build_env_command(
                "pip", ["install", "--upgrade"] + pkgs
            )
        elif pm == "uv pip":
            program, args, _ = self._build_env_command(
                "uv", ["pip", "install", "--upgrade"] + pkgs
            )
        elif pm == "conda":
            if env_data["type"] == "venv":
                QMessageBox.warning(
                    self,
                    "Invalid Environment",
                    "Conda update only works in Conda environments.",
                )
                return
            program = env_data["exe"]
            args = ["update", "-n", env_data["name"], "-y"]

            channel = self.conda_channel_combo.currentText().strip()
            if channel and channel != "defaults":
                args.extend(["-c", channel])

            args.extend(pkgs)
        else:
            return

        if program:
            cmd_display = f"{pm} update {' '.join(pkgs)}"
            if pm == "conda" and channel and channel != "defaults":
                cmd_display += f" (channel: {channel})"

            self.run_command(
                program, args, None, cmd_display, env_data, refresh_packages=True
            )