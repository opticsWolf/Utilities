"""CUDA / MSVC tooling: vcvars detection, system audit, and toolkit prep."""

import os

from PySide6.QtWidgets import QMessageBox, QFileDialog


class CudaAuditMixin:
    """Detect the MSVC environment, audit the system, and install CUDA."""

    # ========== CUDA and MSVC VCVARS Methods ==========
    def _browse_vcvars(self):
        start_dir = r"C:\Program Files\Microsoft Visual Studio"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select vcvars64.bat", start_dir, "Batch Files (*.bat);;All Files (*)"
        )
        if file_path:
            # QFileDialog returns forward slashes on Windows; normalise so the
            # path is safe to hand to cmd.exe / vcvars later.
            self.vcvars_edit.setText(os.path.normpath(file_path))

    def _auto_find_vcvars(self):
        """Locate vcvars64.bat, preferring vswhere (version-independent).

        Order:
          1. vswhere.exe -- authoritative, finds any installed VS regardless of
             version (handles VS 18+, Preview, etc.). Reuses ``_get_vcvars_path``
             when the terminal mixin is present.
          2. Filesystem scan of the standard install roots, covering both the
             year-style folders (``2017``..``2022``) and the newer numeric
             version folders (``17``, ``18``, ...), newest first.
        Returns a normalised path, or "" if nothing is found.
        """
        # 1. vswhere (delegated to the terminal mixin's implementation if available)
        via_vswhere = getattr(self, "_get_vcvars_path", lambda: None)()
        if via_vswhere and os.path.exists(via_vswhere):
            return os.path.normpath(via_vswhere)

        # 2. Filesystem fallback
        scanned = self._scan_for_vcvars()
        return os.path.normpath(scanned) if scanned else ""

    def _scan_for_vcvars(self):
        """Scan standard VS install roots for vcvars64.bat, newest version first.

        Version-proof: instead of hardcoding release years it enumerates whatever
        version folders exist under each root, so future Visual Studio releases
        (numeric or year-named) are picked up automatically.
        """
        suffix = os.path.join("VC", "Auxiliary", "Build", "vcvars64.bat")
        editions = ["Preview", "Enterprise", "Professional", "Community", "BuildTools"]

        base_paths = [
            os.path.expandvars(r"%ProgramFiles%\Microsoft Visual Studio"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft Visual Studio"),
            r"C:\Program Files\Microsoft Visual Studio",
            r"C:\Program Files (x86)\Microsoft Visual Studio",
        ]

        candidates = []  # (version_sort_key, path)
        seen = set()

        for base in base_paths:
            if not os.path.isdir(base):
                continue
            try:
                version_dirs = os.listdir(base)
            except OSError:
                continue

            for version_dir in version_dirs:
                version_path = os.path.join(base, version_dir)
                if not os.path.isdir(version_path):
                    continue

                # Newer layouts nest an edition under the version folder; some
                # installs place VC directly under the version folder.
                possible = [
                    os.path.join(version_path, edition, suffix)
                    for edition in editions
                ]
                possible.append(os.path.join(version_path, suffix))

                for cand in possible:
                    norm = os.path.normpath(cand)
                    if norm not in seen and os.path.exists(norm):
                        seen.add(norm)
                        candidates.append((self._version_sort_key(version_dir), norm))

        if not candidates:
            return ""

        # Highest version number wins (e.g. 18 > 2022 numerically via digits).
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _version_sort_key(version_dir):
        """Order VS version folder names by true major version, newest highest.

        Two naming schemes coexist: older year folders ('2017'..'2022') and the
        newer numeric major-version folders ('17', '18', ...). Mapping years onto
        the major-version scale keeps ordering correct, e.g. numeric 18 must
        outrank year 2022 (which is major 17). Non-numeric names sort last.
        """
        digits = "".join(ch for ch in version_dir if ch.isdigit())
        if not digits:
            return -1
        value = int(digits)
        if value >= 1000:  # a year-style folder
            year_to_major = {2015: 14, 2017: 15, 2019: 16, 2022: 17}
            # Unknown future year folders are treated as the last year-based
            # release (17 / 2022) so genuine numeric versions still win.
            return year_to_major.get(value, 17)
        return value  # already a numeric major version (15, 16, 17, 18, ...)

    def _manual_auto_detect_vcvars(self):
        found = self._auto_find_vcvars()
        if found:
            self.vcvars_edit.setText(found)
            QMessageBox.information(
                self, "MSVC Found", f"Successfully found vcvars64.bat at:\n{found}"
            )
        else:
            QMessageBox.warning(
                self,
                "Not Found",
                "Could not automatically locate vcvars64.bat.\nPlease browse for it manually.",
            )

    def _on_check_cl_clicked(self):
        """Auto-detects (and overrides) MSVC path if found, then runs the audit command."""
        found = self._auto_find_vcvars()
        if found:
            self.vcvars_edit.setText(found)
            self.save_current_settings()
        self.run_audit_command("cl")

    # ========== System Audit Method ==========
    def run_audit_command(self, cmd_type):
        env_data = self.get_selected_env_data()

        if cmd_type == "nvidia-smi":
            program = "nvidia-smi"
            args = []
            cmd_display = "nvidia-smi (System GPU Info)"
        elif cmd_type == "nvcc":
            program = "nvcc"
            args = ["--version"]
            cmd_display = "nvcc --version (CUDA Compiler Info)"
        elif cmd_type == "cl":
            program = "cl"
            args = []
            cmd_display = "cl.exe (MSVC Compiler Info)"
        else:
            return

        require_msvc = cmd_type == "cl"
        self.run_command(
            program,
            args,
            None,
            cmd_display,
            env_data,
            refresh_packages=False,
            require_msvc=require_msvc,
        )

    # ========== CUDA Toolkit Preparation ==========
    def prep_cuda_environment(self):
        env_data = self.get_selected_env_data()

        if not env_data:
            QMessageBox.warning(
                self,
                "No Environment",
                "Please select an environment before installing CUDA.",
            )
            return

        if env_data.get("type") == "conda":
            reply = QMessageBox.question(
                self,
                "Install CUDA Toolkit (Conda)",
                "This will install the full CUDA toolkit from the 'nvidia' channel into your active Conda environment. This download can be several gigabytes.\n\nProceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply == QMessageBox.Yes:
                program = env_data["exe"]
                args = ["install", "-n", env_data["name"], "cuda", "-c", "nvidia", "-y"]
                self.run_command(
                    program,
                    args,
                    None,
                    "Conda CUDA Toolkit Prep",
                    env_data,
                    refresh_packages=True,
                )
        else:
            # Standard Python environment (venv)
            reply = QMessageBox.question(
                self,
                "Install CUDA Toolkit (Pip)",
                "For venv/pip environments, this will attempt to install the PyPI CUDA runtime and NVCC wheels (nvidia-cuda-runtime-cu12, nvidia-cuda-nvcc-cu12).\n\n(Note: Some builds still require a native system-wide CUDA toolkit installation. Ensure your environment manager is set up correctly in the Installed tab).\n\nProceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply == QMessageBox.Yes:
                pm = self.global_pm_combo.currentText()
                cuda_pkgs = ["nvidia-cuda-runtime-cu12", "nvidia-cuda-nvcc-cu12"]

                if pm == "uv pip":
                    program, args, _ = self._build_env_command(
                        "uv", ["pip", "install"] + cuda_pkgs
                    )
                else:
                    program, args, _ = self._build_env_command(
                        "pip", ["install"] + cuda_pkgs
                    )

                if program:
                    self.run_command(
                        program,
                        args,
                        None,
                        "Pip CUDA Toolkit Prep",
                        env_data,
                        refresh_packages=True,
                    )
