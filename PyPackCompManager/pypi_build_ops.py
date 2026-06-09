"""PyPI operations and the advanced build / wheel pipeline.

Grouped together because the build flags and CMAKE_ARGS configured here are
consumed directly by the PyPI install and wheel commands.
"""

import os
import sys
import html
from urllib.parse import quote

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

        # The package name is passed as argv (NOT interpolated into the source) and
        # URL-encoded inside the subprocess, so special characters can neither break
        # the script nor inject code. Plain (non-f) string: braces are literal.
        code = """
import sys, json, urllib.request, urllib.parse
name = urllib.parse.quote(sys.argv[1], safe='')
try:
    req = urllib.request.Request(
        'https://pypi.org/pypi/' + name + '/json',
        headers={'User-Agent': 'Mozilla/5.0'},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        d = json.loads(r.read().decode())
        info = d.get('info', {})

        # Version + summary (strip newlines to protect the ||| split)
        v = info.get('version', 'unknown')
        s = str(info.get('summary', 'No summary')).replace('\\n', ' ')

        # Homepage with "UNKNOWN" / null project_urls fallbacks (case-insensitive)
        h = info.get('home_page')
        if not h or h == 'UNKNOWN':
            urls = info.get('project_urls') or {}
            urls_lower = {k.lower(): val for k, val in urls.items()}
            h = (urls_lower.get('homepage') or urls_lower.get('home')
                 or urls_lower.get('repository') or urls_lower.get('source') or '')
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
        self._pypi_proc.start(sys.executable, ["-c", code, pkg])

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
        v = html.escape(str(parts[0]))
        s = html.escape(str(parts[1]))
        homepage = parts[2] if len(parts) > 2 else ""

        # Always add a link to the PyPI project page (name URL-encoded for the href)
        pkg_q = quote(pkg_name, safe="")
        pypi_link = (
            f'<br><a href="https://pypi.org/project/{pkg_q}/" target="_blank" '
            f'style="color: #039BE5; text-decoration: underline;">📦 PyPI Project Page</a>'
        )

        # Add homepage link if available and valid (escaped for the href attribute)
        if homepage and homepage.startswith("http"):
            hp = html.escape(homepage, quote=True)
            homepage_link = (
                f'<br><a href="{hp}" target="_blank" '
                f'style="color: #039BE5; text-decoration: underline;">🌐 Project Homepage</a>'
            )
        else:
            homepage_link = ""

        self.pypi_info_label.setTextFormat(Qt.RichText)
        self.pypi_info_label.setText(
            f"<b>Version:</b> {v}<br><b>Summary:</b> {s}{pypi_link}{homepage_link}"
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
        """Dynamically add or remove preset flags without overwriting custom user input."""
        current_text = self.pypi_cmake_args_edit.text()
        
        # Map checkboxes to their respective CMake flags
        preset_map = {
            self.cmake_ninja_cb: "-G Ninja",
            self.cmake_cuda_cb: "-DGGML_CUDA=on",
            self.cmake_metal_cb: "-DGGML_METAL=on",
            self.cmake_vulkan_cb: "-DGGML_VULKAN=on",
            self.cmake_openblas_cb: "-DGGML_OPENBLAS=on",
            self.cmake_clblast_cb: "-DGGML_CLBLAST=on",
            self.cmake_unsupported_compiler_cb: '-DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler"'
        }

        new_text = current_text
        
        for cb, flag in preset_map.items():
            if cb.isChecked():
                # Add flag if it's not already in the text
                if flag not in new_text:
                    new_text = f"{new_text} {flag}".strip()
            else:
                # Remove flag if it was unchecked
                if flag in new_text:
                    new_text = new_text.replace(flag, "").strip()
                    # Clean up any double spaces left behind
                    new_text = " ".join(new_text.split())

        # Only update and block signals if the text actually changed
        if new_text != current_text:
            self.pypi_cmake_args_edit.blockSignals(True)
            self.pypi_cmake_args_edit.setText(new_text)
            self.pypi_cmake_args_edit.blockSignals(False)

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