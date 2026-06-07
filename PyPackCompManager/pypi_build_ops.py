"""PyPI operations and the advanced build / wheel pipeline.

Grouped together because the build flags and CMAKE_ARGS configured here are
consumed directly by the PyPI install and wheel commands.
"""

import os
import sys

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import QMessageBox, QFileDialog


class PyPIBuildMixin:
    """Search/install from PyPI and build wheels from source."""

    # ========== PyPI Search ==========
    def search_pypi_info(self):
        pkg = self.pypi_search_edit.text().strip()
        if not pkg:
            return
            
        if os.path.isfile(pkg) or os.path.isdir(pkg):
            self.pypi_info_label.setText("Local path selected. Ready to install/build from file.")
            return

        self.pypi_info_label.setText("Searching PyPI...")

        # Fixed embedded script: handles "UNKNOWN", null project_urls, case-insensitive keys, and newlines
        code = f"""
import urllib.request, json
try:
    req = urllib.request.Request('https://pypi.org/pypi/{pkg}/json', headers={{'User-Agent': 'Mozilla/5.0'}})
    with urllib.request.urlopen(req, timeout=5) as r:
        d = json.loads(r.read().decode())
        info = d.get('info', {{}})
        
        # 1. Safely extract version and summary (stripping newlines to protect the ||| split)
        v = info.get('version', 'unknown')
        s = str(info.get('summary', 'No summary')).replace('\\n', ' ')
        
        # 2. Handle the "UNKNOWN" fallback
        h = info.get('home_page')
        if not h or h == 'UNKNOWN':
            # 3. Handle null project_urls safely using `or {{}}`
            urls = info.get('project_urls') or {{}}
            
            # 4. Normalize keys to lowercase for case-insensitive matching
            urls_lower = {{k.lower(): val for k, val in urls.items()}}
            
            # 5. Check common URL keys
            h = urls_lower.get('homepage') or urls_lower.get('home') or urls_lower.get('repository') or urls_lower.get('source') or ''
            
        if not h:
            h = ''
            
        print(v + "|||" + s + "|||" + str(h).strip())
except Exception:
    print("NOT_FOUND")
"""
        self._pypi_proc = QProcess(self)
        self._pypi_proc_output = ""
        self._pypi_proc.readyReadStandardOutput.connect(
            lambda: setattr(
                self,
                "_pypi_proc_output",
                self._pypi_proc_output
                + self._pypi_proc.readAllStandardOutput().data().decode("utf-8"),
            )
        )
        self._pypi_proc.finished.connect(self._on_pypi_search_finished)
        self._pypi_proc.errorOccurred.connect(self._on_pypi_search_error)
        self._pypi_proc.start(sys.executable, ["-c", code])

    def _on_pypi_search_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.pypi_info_label.setText(
                "Could not start the search process (Python interpreter not found)."
            )

    def _on_pypi_search_finished(self):
        out = self._pypi_proc_output.strip()
        if out == "NOT_FOUND" or not out:
            self.pypi_info_label.setText("Package not found on PyPI.")
            return

        if "|||" not in out:
            self.pypi_info_label.setText("Error retrieving info.")
            return

        parts = out.split("|||")
        pkg_name = self.pypi_search_edit.text().strip()
        v = parts[0]
        s = parts[1]
        homepage = parts[2] if len(parts) > 2 else ""

        # Always add a link to the PyPI project page
        pypi_link = f'<br><a href="https://pypi.org/project/{pkg_name}/" target="_blank" style="color: #039BE5; text-decoration: underline;">📦 PyPI Project Page</a>'
        
        # Add homepage link if available and valid
        if homepage and homepage.startswith("http"):
            homepage_link = f'<br><a href="{homepage}" target="_blank" style="color: #039BE5; text-decoration: underline;">🌐 Project Homepage</a>'
        else:
            homepage_link = ""

        self.pypi_info_label.setTextFormat(Qt.RichText)
        self.pypi_info_label.setText(
            f"<b>Version:</b> {v}<br><b>Summary:</b> {s}{homepage_link}{pypi_link}"
        )
        self.pypi_info_label.setOpenExternalLinks(True)

    # ========== PyPI Install ==========
    def install_from_pypi(self):
        self.save_current_settings()
        pkg_name = self.pypi_search_edit.text().strip()
        pm = self.pypi_pm_combo.currentText()
        env_data = self.get_selected_env_data()

        if not env_data or not pkg_name:
            return

        install_args = ["install"]

        # General installation flags
        if self.pypi_no_cache_cb.isChecked():
            install_args.append(
                "--no-cache" if pm == "uv pip" else "--no-cache-dir"
            )
        if self.pypi_force_reinstall_cb.isChecked():
            install_args.append("--force-reinstall")
        if self.pypi_upgrade_cb.isChecked():
            install_args.append("--upgrade")

        # Handle local files and requirements lists
        if os.path.isfile(pkg_name):
            if pkg_name.endswith('.txt'):
                install_args.extend(["-r", pkg_name])
            elif pkg_name.endswith('.toml'):
                install_args.append(os.path.dirname(pkg_name))
            else:
                install_args.append(pkg_name)
        elif os.path.isdir(pkg_name):
            install_args.append(pkg_name)
        else:
            install_args.append(pkg_name)

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", install_args)
        elif pm == "uv pip":
            program, args, _ = self._build_env_command("uv", ["pip"] + install_args)
        else:
            return

        if program:
            extra_env = {}
            require_msvc = False
            if self.build_enabled_cb.isChecked():
                cmake_val = self.pypi_cmake_args_edit.text().strip()
                if cmake_val:
                    extra_env["CMAKE_ARGS"] = cmake_val
                require_msvc = True

            cmd_display = f"{pm} install {pkg_name}" + (
                " (CUDA/Source Build)" if require_msvc else ""
            )

            self.run_command(
                program,
                args,
                None,
                cmd_display,
                env_data,
                refresh_packages=True,
                require_msvc=require_msvc,
                extra_env=extra_env,
            )

    # ========== Advanced Build: CMake presets & toggling ==========
    def _toggle_advanced_build_widgets(self, enabled):
        self.cmake_presets_group.setEnabled(enabled)
        self.pypi_cmake_args_edit.setEnabled(enabled)

    def _update_cmake_args_from_presets(self):
        if getattr(self, "_cmake_manual_edit", False):
            return
        parts = []
        if self.cmake_ninja_cb.isChecked():
            parts.append("-G Ninja")
        if self.cmake_cuda_cb.isChecked():
            parts.append("-DGGML_CUDA=on")
        if self.cmake_metal_cb.isChecked():
            parts.append("-DGGML_METAL=on")
        if self.cmake_vulkan_cb.isChecked():
            parts.append("-DGGML_VULKAN=on")
        if self.cmake_openblas_cb.isChecked():
            parts.append("-DGGML_OPENBLAS=on")
        if self.cmake_clblast_cb.isChecked():
            parts.append("-DGGML_CLBLAST=on")
        if self.cmake_unsupported_compiler_cb.isChecked():
            parts.append('-DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler"')

        new_args = " ".join(parts)
        if new_args != self.pypi_cmake_args_edit.text():
            self.pypi_cmake_args_edit.blockSignals(True)
            self.pypi_cmake_args_edit.setText(new_args)
            self.pypi_cmake_args_edit.blockSignals(False)

    def _on_cmake_args_manually_edited(self):
        self._cmake_manual_edit = True

    # ========== Wheel Building ==========
    def _browse_wheel_output_dir(self):
        start_dir = (
            self.folder_edit.text().strip()
            if hasattr(self, "folder_edit")
            else os.getcwd()
        )
        if not os.path.isdir(start_dir):
            start_dir = os.getcwd()
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Wheel Output Directory", start_dir
        )
        if dir_path:
            self.wheel_output_edit.setText(dir_path)

    def build_wheel_from_pypi(self):
        self.save_current_settings()
        pkg_name = self.pypi_search_edit.text().strip()
        pm = self.pypi_pm_combo.currentText()
        env_data = self.get_selected_env_data()
        wheel_dir = self.wheel_output_edit.text().strip()

        if not env_data or not pkg_name:
            return
        if not wheel_dir:
            QMessageBox.warning(
                self,
                "Missing Output Folder",
                "Please select a folder for the wheel output.",
            )
            return
        if not os.path.isdir(wheel_dir):
            QMessageBox.warning(
                self,
                "Invalid Folder",
                "The selected wheel output folder does not exist.",
            )
            return

        if pm == "pip":
            program, args, _ = self._build_env_command("pip", ["wheel"])
        elif pm == "uv pip":
            program, args, _ = self._build_env_command("uv", ["pip", "wheel"])
        else:
            return

        wheel_args = args + ["--wheel-dir", wheel_dir]

        if self.pypi_no_cache_cb.isChecked():
            wheel_args.append("--no-cache-dir" if pm == "pip" else "--no-cache")
        if self.pypi_force_reinstall_cb.isChecked():
            wheel_args.append("--force-reinstall")
        if self.pypi_upgrade_cb.isChecked():
            wheel_args.append("--upgrade")

        if os.path.isfile(pkg_name):
            if pkg_name.endswith('.txt'):
                wheel_args.extend(["-r", pkg_name])
            elif pkg_name.endswith('.toml'):
                wheel_args.append(os.path.dirname(pkg_name))
            else:
                wheel_args.append(pkg_name)
        elif os.path.isdir(pkg_name):
            wheel_args.append(pkg_name)
        else:
            wheel_args.append(pkg_name)

        extra_env = {}
        require_msvc = False
        if self.build_enabled_cb.isChecked():
            cmake_val = self.pypi_cmake_args_edit.text().strip()
            if cmake_val:
                extra_env["CMAKE_ARGS"] = cmake_val
            require_msvc = True

        cmd_display = f"{pm} wheel --wheel-dir {wheel_dir} {pkg_name}" + (
            " (CUDA/Source Build)" if require_msvc else ""
        )
        self.run_command(
            program,
            wheel_args,
            None,
            cmd_display,
            env_data,
            refresh_packages=False,
            require_msvc=require_msvc,
            extra_env=extra_env,
        )