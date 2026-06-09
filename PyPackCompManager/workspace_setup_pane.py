"""Workspace dock: environment selection, inline creation/duplication panes,
project folder, plus hardened clone/delete actions.

Design notes
------------
* Creation and Duplication are *inline panes* inside collapsible group boxes.
  Neither runs in a dialog -- the only dialog shown is a final confirmation
  (QMessageBox) summarising exactly what will happen before it runs.
* Venv duplication can target the source's parent folder *or* a user-defined
  parent folder.
* Square icon buttons use ``self._style_square_icon_button`` and primary action
  buttons use ``self._setup_button`` / ``self._style_critical_button`` from the
  host's CoreUIMixin, matching the rest of the app.
* Collapsible panes use ``CollapsibleGroupBox`` from ``core_ui_helpers``.

Safety (clone & delete only ever touch Python environments)
-----------------------------------------------------------
1. ``_is_python_environment`` -- a folder must currently contain pyvenv.cfg or
   conda-meta to be eligible for cloning/deletion.
2. ``_is_path_safe_to_delete`` / ``_is_path_safe_to_create`` -- block roots,
   mount points, the home directory and its ancestors, and very shallow paths.
3. Explicit confirmation dialog for every destructive/creative action.
4. The venv clone/delete subprocesses re-validate the target *themselves*
   immediately before copytree/rmtree, so a stale selection can never act on a
   non-environment. Conda clone/remove rely on conda's own prefix validation.
"""

import os
import sys
import json
from typing import Protocol, Any, Optional, Dict, List

from PySide6.QtWidgets import (
    QDockWidget,
    QScrollArea,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt, QProcess

# Assumes EnvProcess is implemented elsewhere in your project
from process_wrapper import EnvProcess

# Reuse the app's shared collapsible group box + horizontal rule
from core_ui_helpers import CollapsibleGroupBox, QHLine


class WorkspaceHost(Protocol):
    """
    Protocol defining the expected interface for the class that consumes
    WorkspaceMixin. Keeps linters/type-checkers happy.
    """
    settings: Any
    current_process: Any

    def run_command(
        self,
        program: str,
        args: List[str],
        working_dir: Optional[str],
        command_name: str,
        env_data: Dict[str, Any],
        refresh_packages: bool,
        require_msvc: bool,
    ) -> None: ...

    def save_current_settings(self) -> None: ...
    def _get_fallback_path(self, path: str) -> str: ...
    def _setup_button(self, btn: QPushButton, tooltip: str) -> None: ...
    def _style_square_icon_button(self, btn: QPushButton) -> None: ...
    def _style_critical_button(self, btn: QPushButton, c1: str, c2: str) -> None: ...


class WorkspaceMixin:
    """Environment selection, inline create/duplicate panes, and project folder."""

    # Files/dirs that uniquely identify a directory as a Python environment we
    # are allowed to clone or delete. A directory lacking ALL of these is never
    # touched by clone or delete operations.
    _ENV_MARKERS = ("pyvenv.cfg", "conda-meta")

    # Built-in fallback list of Python minor versions (used offline / on failure).
    _PY_VERSION_FALLBACK = ("3.14", "3.13", "3.12", "3.11", "3.10", "3.9")
    # Online source the tool can query to self-manage the version list.
    _PY_EOL_API_URL = "https://endoflife.date/api/python.json"

    # ==================================================================
    # Dock assembly
    # ==================================================================
    def _build_workspace_dock(self: WorkspaceHost):
        workspace_dock = QDockWidget("Workspace Setup", self)
        workspace_dock.setObjectName("workspaceDock")
        workspace_dock.setMinimumSize(340, 320)
        workspace_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        workspace_dock.setFeatures(QDockWidget.DockWidgetMovable)

        # The pane is now tall, so wrap it in a scroll area like the other docks.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)

        layout.addWidget(self._build_env_select_group())
        layout.addWidget(self._build_create_group())
        layout.addWidget(self._build_duplicate_group())
        layout.addWidget(self._build_project_group())
        layout.addStretch()

        # Wire env-selection changes once every group exists (the duplicate pane's
        # source label depends on the current selection).
        self.env_combo.currentIndexChanged.connect(self._on_env_selection_changed)

        scroll.setWidget(container)
        workspace_dock.setWidget(scroll)
        return workspace_dock

    # ----- Group 1: Environment selection + delete -----
    def _build_env_select_group(self: WorkspaceHost):
        group = QGroupBox("Environment Selection")
        v = QVBoxLayout(group)

        form = QFormLayout()

        # Base directory
        self.env_base_edit = QLineEdit()
        self.env_base_edit.setToolTip(
            "The base directory containing your virtual environments or the conda 'envs' folder."
        )
        browse_env_base_btn = QPushButton("📂")
        self._setup_button(browse_env_base_btn, "Browse for your environment base directory.")
        browse_env_base_btn.clicked.connect(self.browse_env_base)
        self._style_square_icon_button(browse_env_base_btn)

        base_row = QHBoxLayout()
        base_row.addWidget(self.env_base_edit)
        base_row.addWidget(browse_env_base_btn)
        form.addRow("Base Directory:", base_row)

        # Active environment combo + refresh
        self.env_combo = QComboBox()
        self.env_combo.setToolTip(
            "Select the active environment (Conda or Venv) to run the build tools in."
        )
        refresh_env_btn = QPushButton("🔄")
        self._setup_button(refresh_env_btn, "Refresh the list of available environments.")
        refresh_env_btn.clicked.connect(self.refresh_env_list)
        self._style_square_icon_button(refresh_env_btn)

        combo_row = QHBoxLayout()
        combo_row.addWidget(self.env_combo)
        combo_row.addWidget(refresh_env_btn)
        form.addRow("Environment:", combo_row)

        v.addLayout(form)

        return group

    # ----- Group 2: Create (inline, collapsible) -----
    def _build_create_group(self: WorkspaceHost):
        self.create_group = CollapsibleGroupBox("Create New Environment")
        self.create_group.setToolTip(
            "Click the title to expand/collapse. Fill the fields, then press Create "
            "(a confirmation dialog appears before anything runs)."
        )
        form = QFormLayout(self.create_group.content_widget)

        # Environment type
        self.create_type_combo = QComboBox()
        self.create_type_combo.addItems(
            ["Venv via Python", "Venv via UV", "Conda Environment"]
        )
        self.create_type_combo.currentTextChanged.connect(self._on_create_type_changed)
        self.create_type_combo.currentTextChanged.connect(self.save_current_settings)
        form.addRow("Type:", self.create_type_combo)

        # Name
        self.create_name_edit = QLineEdit()
        self.create_name_edit.setPlaceholderText("e.g. my-new-env")
        form.addRow("Name:", self.create_name_edit)

        # Location type
        self.create_loc_combo = QComboBox()
        self.create_loc_combo.addItems(["Default Base Directory", "Custom Specific Folder"])
        self.create_loc_combo.currentTextChanged.connect(self._on_create_location_changed)
        self.create_loc_combo.currentTextChanged.connect(self.save_current_settings)
        form.addRow("Location:", self.create_loc_combo)

        # Custom destination (parent) folder -- disabled unless "Custom" is chosen
        self.create_custom_edit = QLineEdit()
        self.create_custom_edit.setPlaceholderText("Custom parent folder for the new env...")
        create_browse_btn = QPushButton("📂")
        self._setup_button(create_browse_btn, "Browse for a custom destination folder.")
        create_browse_btn.clicked.connect(self._browse_create_custom_path)
        self._style_square_icon_button(create_browse_btn)

        self.create_custom_row = QWidget()
        create_custom_layout = QHBoxLayout(self.create_custom_row)
        create_custom_layout.setContentsMargins(0, 0, 0, 0)
        create_custom_layout.addWidget(self.create_custom_edit)
        create_custom_layout.addWidget(create_browse_btn)
        form.addRow("Custom Path:", self.create_custom_row)
        self.create_custom_row.setEnabled(False)

        # Python version (applies to UV and Conda) -- editable combo with an
        # optional online refresh. The first entry, "Default", means no version
        # pin; its label is filled in live with the version the selected tool
        # would actually use.
        self.create_pyver_combo = QComboBox()
        self.create_pyver_combo.setEditable(True)
        self.create_pyver_combo.setToolTip(
            "Python version for the new environment (UV and Conda). 'Default' lets "
            "the tool choose (the resolved version is shown in the entry). "
            "'Venv via Python' always uses the interpreter running this app."
        )
        self.create_pyver_combo.setEnabled(False)
        self._py_default_label = "Default"  # updated by _resolve_default_python()

        self.create_pyver_refresh_btn = QPushButton("🔄")
        self._setup_button(
            self.create_pyver_refresh_btn,
            "Refresh the Python version list from endoflife.date.",
        )
        self.create_pyver_refresh_btn.clicked.connect(self._refresh_python_versions_online)
        self._style_square_icon_button(self.create_pyver_refresh_btn)
        self.create_pyver_refresh_btn.setEnabled(False)

        pyver_row = QWidget()
        pyver_layout = QHBoxLayout(pyver_row)
        pyver_layout.setContentsMargins(0, 0, 0, 0)
        pyver_layout.addWidget(self.create_pyver_combo)
        pyver_layout.addWidget(self.create_pyver_refresh_btn)
        form.addRow("Python Version:", pyver_row)

        # Seed with the built-in list; _load_workspace_settings may replace it
        # with a cached/online list and restore the last-used selection.
        self._populate_python_versions(list(self._PY_VERSION_FALLBACK))

        # Extra args / dependencies
        self.create_extra_edit = QLineEdit()
        self.create_extra_edit.setPlaceholderText("e.g. --system-site-packages")
        self.create_extra_edit.textChanged.connect(self.save_current_settings)
        form.addRow("Extra Args:", self.create_extra_edit)

        # Create button
        self.btn_create_env = QPushButton("➕ Create Environment")
        self._setup_button(
            self.btn_create_env,
            "Create the environment described above (a confirmation dialog appears first).",
        )
        self._style_critical_button(self.btn_create_env, "#388E3C", "#2E7D32")
        self.btn_create_env.clicked.connect(self.on_create_clicked)
        form.addRow(self.btn_create_env)

        return self.create_group

    # ----- Group 3: Duplicate (inline, collapsible) -----
    def _build_duplicate_group(self: WorkspaceHost):
        self.duplicate_group = CollapsibleGroupBox("Duplicate / Clone / Delete Environment")
        self.duplicate_group.setToolTip(
            "Clone the currently selected environment, or delete it. Venvs may be "
            "cloned beside the source or into a user-defined folder. A confirmation "
            "dialog appears first."
        )
        form = QFormLayout(self.duplicate_group.content_widget)

        # Source (reflects current selection; read-only)
        self.dup_source_label = QLabel("Select an environment above.")
        self.dup_source_label.setWordWrap(True)
        form.addRow("Source:", self.dup_source_label)

        # New name
        self.dup_name_edit = QLineEdit()
        self.dup_name_edit.setPlaceholderText("e.g. my-env-copy")
        form.addRow("New Name:", self.dup_name_edit)

        # Destination parent type
        self.dup_dest_combo = QComboBox()
        self.dup_dest_combo.addItems(["Beside Source", "Custom Parent Folder"])
        self.dup_dest_combo.setToolTip(
            "'Beside Source' places the copy in the same parent folder as the source. "
            "'Custom Parent Folder' lets you choose any destination (venv)."
        )
        self.dup_dest_combo.currentTextChanged.connect(self._on_duplicate_dest_type_changed)
        self.dup_dest_combo.currentTextChanged.connect(self.save_current_settings)
        form.addRow("Destination:", self.dup_dest_combo)

        # Custom parent folder -- disabled unless "Custom Parent Folder" chosen
        self.dup_custom_edit = QLineEdit()
        self.dup_custom_edit.setPlaceholderText("Custom parent folder for the copy...")
        self.dup_custom_edit.textChanged.connect(self.save_current_settings)
        dup_browse_btn = QPushButton("📂")
        self._setup_button(dup_browse_btn, "Browse for a custom destination folder.")
        dup_browse_btn.clicked.connect(self._browse_duplicate_custom_parent)
        self._style_square_icon_button(dup_browse_btn)

        self.dup_custom_row = QWidget()
        dup_custom_layout = QHBoxLayout(self.dup_custom_row)
        dup_custom_layout.setContentsMargins(0, 0, 0, 0)
        dup_custom_layout.addWidget(self.dup_custom_edit)
        dup_custom_layout.addWidget(dup_browse_btn)
        form.addRow("Custom Parent:", self.dup_custom_row)
        self.dup_custom_row.setEnabled(False)

        # Duplicate button
        self.btn_duplicate_env = QPushButton("📋 Duplicate Environment")
        self._setup_button(
            self.btn_duplicate_env,
            "Clone the selected environment (a confirmation dialog appears first).",
        )
        self._style_critical_button(self.btn_duplicate_env, "#0277BD", "#01579B")
        self.btn_duplicate_env.clicked.connect(self.on_duplicate_clicked)
        form.addRow(self.btn_duplicate_env)

        # Delete button -- moved here from the selection group, separated by a rule.
        form.addRow(QHLine())
        self.btn_delete_env = QPushButton("🗑️ Delete Selected Environment")
        self._setup_button(
            self.btn_delete_env,
            "Permanently delete the selected environment from disk (with confirmation).",
        )
        self._style_critical_button(self.btn_delete_env, "#D32F2F", "#C62828")
        self.btn_delete_env.clicked.connect(self.delete_selected_env)
        form.addRow(self.btn_delete_env)

        return self.duplicate_group

    # ----- Group 4: Project folder (regular group box) -----
    def _build_project_group(self: WorkspaceHost):
        group = QGroupBox("Project Folder")
        v = QVBoxLayout(group)

        self.folder_edit = QLineEdit()
        self.folder_edit.setToolTip(
            "The root folder of your Rust/Python project (where Cargo.toml is located)."
        )
        browse_folder_btn = QPushButton("📂")
        self._setup_button(browse_folder_btn, "Browse for your project folder.")
        browse_folder_btn.clicked.connect(self.browse_folder)
        self._style_square_icon_button(browse_folder_btn)

        row = QHBoxLayout()
        row.addWidget(self.folder_edit)
        row.addWidget(browse_folder_btn)
        v.addLayout(row)

        return group

    # ==================================================================
    # Dynamic form behaviour
    # ==================================================================
    def _on_create_type_changed(self, text):
        # Version selection is meaningful for UV (can fetch/select an interpreter)
        # and Conda. Plain "Venv via Python" always uses the running interpreter.
        needs_version = text in ("Venv via UV", "Conda Environment")
        self.create_pyver_combo.setEnabled(needs_version)
        self.create_pyver_refresh_btn.setEnabled(needs_version)
        is_conda = (text == "Conda Environment")
        self.create_extra_edit.setPlaceholderText(
            "e.g. numpy scipy (dependencies)" if is_conda else "e.g. --system-site-packages"
        )
        # Live-resolve the version the chosen tool would use for "Default".
        self._resolve_default_python()

    def _on_create_location_changed(self, text):
        self.create_custom_row.setEnabled(text == "Custom Specific Folder")

    def _on_duplicate_dest_type_changed(self, text):
        self.dup_custom_row.setEnabled(text == "Custom Parent Folder")

    def _on_env_selection_changed(self, *_):
        self._sync_duplicate_source_label()
        # Persist last selection only when a real environment is selected
        # (skips placeholder items like "Loading...", "No environments found").
        if self.env_combo.currentData():
            self.save_current_settings()

    def _sync_duplicate_source_label(self):
        env_data = self.env_combo.currentData()
        if env_data and env_data.get("path"):
            self.dup_source_label.setText(
                f"{env_data['type']}: {env_data['name']}\n{env_data['path']}"
            )
        else:
            self.dup_source_label.setText("Select a valid environment above.")

    # ==================================================================
    # Python version list (built-in fallback + optional online self-management)
    # ==================================================================
    def _populate_python_versions(self, versions):
        """Refill the version combo. Index 0 is the "Default" sentinel (no version
        pin; its label shows the tool's resolved version). When there is no prior
        selection, default to the latest concrete version. Newest-first input."""
        was_default = (self.create_pyver_combo.currentIndex() == 0)
        current = self.create_pyver_combo.currentText().strip()
        real = [v for v in versions if v]
        self.create_pyver_combo.blockSignals(True)
        self.create_pyver_combo.clear()
        self.create_pyver_combo.addItem(getattr(self, "_py_default_label", "Default"))
        self.create_pyver_combo.addItems(real)
        if was_default:
            self.create_pyver_combo.setCurrentIndex(0)               # keep "Default"
        elif current and self.create_pyver_combo.findText(current) >= 0:
            self.create_pyver_combo.setCurrentText(current)          # keep an existing pick
        elif current:
            self.create_pyver_combo.setEditText(current)             # keep a custom value
        elif real:
            self.create_pyver_combo.setCurrentIndex(1)               # default selection = latest
        else:
            self.create_pyver_combo.setCurrentIndex(0)
        self.create_pyver_combo.blockSignals(False)

    def _selected_python_version(self):
        """Effective version to pass to the create command. Index 0 ("Default")
        means no pin, so return an empty string regardless of its display label."""
        if self.create_pyver_combo.currentIndex() == 0:
            return ""
        return self.create_pyver_combo.currentText().strip()

    def _set_default_label(self, version):
        """Update the index-0 'Default' entry to show the resolved version."""
        self._py_default_label = f"Default ({version})" if version else "Default"
        self.create_pyver_combo.blockSignals(True)
        self.create_pyver_combo.setItemText(0, self._py_default_label)
        if self.create_pyver_combo.currentIndex() == 0:
            self.create_pyver_combo.setEditText(self._py_default_label)
        self.create_pyver_combo.blockSignals(False)

    # ----- Live resolution of the tool's default Python version -----
    def _resolve_default_python(self: WorkspaceHost):
        """Work out which Python the currently-selected tool would use by default,
        and show it in the 'Default' entry. Async for UV/Conda; instant for venv."""
        self._py_default_token = getattr(self, "_py_default_token", 0) + 1
        token = self._py_default_token
        env_type = self.create_type_combo.currentText()

        if env_type == "Venv via Python":
            import platform
            # `python -m venv` uses this very interpreter.
            self._set_default_label(platform.python_version())
            return

        if env_type == "Venv via UV":
            self._set_default_label("resolving…")
            self._py_probe = QProcess(self)
            self._py_probe_out = ""
            self._py_probe.readyReadStandardOutput.connect(
                lambda: setattr(
                    self, "_py_probe_out",
                    self._py_probe_out
                    + self._py_probe.readAllStandardOutput().data().decode("utf-8", "replace"),
                )
            )
            self._py_probe.finished.connect(lambda *a: self._on_uv_path_found(token))
            self._py_probe.errorOccurred.connect(lambda *a: self._set_default_label(""))
            self._py_probe.start("uv", ["python", "find"])
            return

        if env_type == "Conda Environment":
            conda_exe = getattr(self, "_current_conda_exe", None)
            if not conda_exe:
                env_data = self.env_combo.currentData()
                if env_data and env_data.get("type") == "conda":
                    conda_exe = env_data.get("exe")
            if not conda_exe:
                self._set_default_label("")  # unknown until a conda env is available
                return
            self._set_default_label("resolving…")
            channel = (
                self.conda_channel_combo.currentText().strip()
                if hasattr(self, "conda_channel_combo") else ""
            )
            args = ["search", "python", "--json"]
            if channel and channel != "defaults":
                args += ["-c", channel]
            self._py_probe = QProcess(self)
            self._py_probe_out = ""
            self._py_probe.readyReadStandardOutput.connect(
                lambda: setattr(
                    self, "_py_probe_out",
                    self._py_probe_out
                    + self._py_probe.readAllStandardOutput().data().decode("utf-8", "replace"),
                )
            )
            self._py_probe.finished.connect(lambda *a: self._on_conda_default_found(token))
            self._py_probe.errorOccurred.connect(lambda *a: self._set_default_label(""))
            self._py_probe.start(conda_exe, args)

    def _on_uv_path_found(self, token):
        if token != getattr(self, "_py_default_token", None):
            return  # a newer resolution superseded this one
        lines = (self._py_probe_out or "").strip().splitlines()
        path = lines[0].strip() if lines else ""
        if not path or not os.path.exists(path):
            self._set_default_label("")
            return
        # Ask the resolved interpreter for its own version.
        self._py_probe2 = QProcess(self)
        self._py_probe2_out = ""
        self._py_probe2.readyReadStandardOutput.connect(
            lambda: setattr(
                self, "_py_probe2_out",
                self._py_probe2_out
                + self._py_probe2.readAllStandardOutput().data().decode("utf-8", "replace"),
            )
        )
        self._py_probe2.finished.connect(lambda *a: self._on_uv_version_found(token))
        self._py_probe2.errorOccurred.connect(lambda *a: self._set_default_label(""))
        self._py_probe2.start(path, ["-c", "import platform;print(platform.python_version())"])

    def _on_uv_version_found(self, token):
        if token != getattr(self, "_py_default_token", None):
            return
        ver = (self._py_probe2_out or "").strip()
        self._set_default_label(ver if ver and ver[0].isdigit() else "")

    def _on_conda_default_found(self, token):
        if token != getattr(self, "_py_default_token", None):
            return
        try:
            data = json.loads(self._py_probe_out or "")
            builds = data.get("python") or []
            # conda search --json returns ascending order; the last build is newest.
            ver = builds[-1].get("version", "") if builds else ""
        except Exception:
            ver = ""
        self._set_default_label(ver)


    @staticmethod
    def _parse_python_cycles(data):
        """Extract sorted 'X.Y' minor versions from either the legacy
        /api/python.json (list of {'cycle'}) or v1 (dict with result.releases)."""
        import re

        raw = []
        if isinstance(data, list):
            for e in data:
                if isinstance(e, dict):
                    raw.append(e.get("cycle") or e.get("name"))
        elif isinstance(data, dict):
            rel = (data.get("result") or {}).get("releases") or data.get("releases") or []
            for e in rel:
                if isinstance(e, dict):
                    raw.append(e.get("name") or e.get("cycle"))

        out = []
        for c in raw:
            c = str(c).strip()
            if re.fullmatch(r"\d+\.\d+", c):
                out.append(c)
        return sorted(
            set(out), key=lambda c: tuple(int(x) for x in c.split(".")), reverse=True
        )

    def _refresh_python_versions_online(self: WorkspaceHost):
        """Query endoflife.date in a subprocess (urllib) and refresh the version list.
        Non-blocking; failures keep the existing list."""
        self.create_pyver_refresh_btn.setEnabled(False)

        # urllib runs in a short-lived subprocess (same idiom as the PyPI/conda
        # fetches) so the GUI thread never blocks and no extra Qt module is needed.
        # The URL is passed as argv, not interpolated. Plain string -> literal braces.
        code = """
import sys, json, urllib.request
try:
    req = urllib.request.Request(sys.argv[1], headers={'User-Agent': 'gpm-workspace'})
    with urllib.request.urlopen(req, timeout=8) as r:
        sys.stdout.write(r.read().decode('utf-8', 'replace'))
except Exception as exc:
    sys.stdout.write('ERROR: ' + str(exc))
"""
        self._pyver_proc = QProcess(self)
        self._pyver_proc_output = ""
        self._pyver_proc.readyReadStandardOutput.connect(
            lambda: setattr(
                self,
                "_pyver_proc_output",
                self._pyver_proc_output
                + self._pyver_proc.readAllStandardOutput().data().decode("utf-8", "replace"),
            )
        )
        self._pyver_proc.finished.connect(self._on_python_versions_finished)
        self._pyver_proc.errorOccurred.connect(self._on_python_versions_error)
        self._pyver_proc.start(sys.executable, ["-c", code, self._PY_EOL_API_URL])

    def _reenable_pyver_refresh(self):
        self.create_pyver_refresh_btn.setEnabled(
            self.create_type_combo.currentText() in ("Venv via UV", "Conda Environment")
        )

    def _on_python_versions_error(self: WorkspaceHost, error):
        # `finished` is not emitted when the process fails to start, so handle it here.
        if error == QProcess.ProcessError.FailedToStart:
            self._reenable_pyver_refresh()
            QMessageBox.information(
                self,
                "Version Refresh",
                "Could not start the version lookup process; keeping the built-in list.",
            )

    def _on_python_versions_finished(self: WorkspaceHost, exit_code=0, exit_status=None):
        self._reenable_pyver_refresh()
        out = (self._pyver_proc_output or "").strip()
        try:
            if not out or out.startswith("ERROR:"):
                raise RuntimeError(out[len("ERROR:"):].strip() or "no response")
            cycles = self._parse_python_cycles(json.loads(out))
            if not cycles:
                raise ValueError("No versions found in the response.")
            self._populate_python_versions(cycles)
            # Cache as a comma-separated string for backend-agnostic persistence.
            self.settings.set("python_versions_cache", ",".join(cycles))
            self.save_current_settings()
        except Exception as exc:
            QMessageBox.information(
                self,
                "Version Refresh",
                "Could not fetch the online Python version list; keeping the "
                f"built-in list.\n\nReason: {exc}",
            )

    # ==================================================================
    # Settings load / save
    # ==================================================================
    def _set_env_actions_enabled(self, enabled: bool):
        """Enable/disable management controls during background operations."""
        self.btn_create_env.setEnabled(enabled)
        self.btn_duplicate_env.setEnabled(enabled)
        self.btn_delete_env.setEnabled(enabled)
        self.env_combo.setEnabled(enabled)

    def _load_workspace_settings(self: WorkspaceHost):
        self.env_base_edit.setText(self.settings.get("env_base_dir", ""))
        self.folder_edit.setText(self.settings.get("project_folder", ""))

        # Create pane defaults (block signals so loading doesn't trigger saves)
        def _set_combo(combo, value):
            idx = combo.findText(value)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

        _set_combo(self.create_type_combo, self.settings.get("create_env_type", "Venv via Python"))
        _set_combo(self.create_loc_combo, self.settings.get("create_location_type", "Default Base Directory"))
        self.create_extra_edit.blockSignals(True)
        self.create_extra_edit.setText(self.settings.get("create_extra_args", ""))
        self.create_extra_edit.blockSignals(False)

        # Python version list: prefer the cached online list, else the built-in one.
        # _populate_python_versions defaults the selection to the latest; restore the
        # saved choice (a version, or the "__default__" sentinel for the Default entry).
        cached = self.settings.get("python_versions_cache", "")
        versions = [v for v in cached.split(",") if v] or list(self._PY_VERSION_FALLBACK)
        self._populate_python_versions(versions)
        last_pyver = self.settings.get("create_python_version", "")
        self.create_pyver_combo.blockSignals(True)
        if last_pyver == "__default__":
            self.create_pyver_combo.setCurrentIndex(0)        # the "Default" entry
        elif last_pyver:
            self.create_pyver_combo.setCurrentText(last_pyver)
        self.create_pyver_combo.blockSignals(False)

        # Duplicate pane defaults
        _set_combo(self.dup_dest_combo, self.settings.get("duplicate_dest_type", "Beside Source"))
        self.dup_custom_edit.blockSignals(True)
        self.dup_custom_edit.setText(self.settings.get("duplicate_custom_parent", ""))
        self.dup_custom_edit.blockSignals(False)

        # Apply dependent enabled/disabled state
        self._on_create_type_changed(self.create_type_combo.currentText())
        self._on_create_location_changed(self.create_loc_combo.currentText())
        self._on_duplicate_dest_type_changed(self.dup_dest_combo.currentText())

        # Restore collapsible expansion states
        for grp, key, default in [
            (self.create_group, "workspace_create_expanded", False),
            (self.duplicate_group, "workspace_duplicate_expanded", False),
        ]:
            expanded = self.settings.get(key, default)
            grp.is_expanded = expanded
            grp.content_widget.setVisible(expanded)
            grp._update_title()

    def _save_workspace_settings(self: WorkspaceHost):
        self.settings.set("env_base_dir", self.env_base_edit.text().strip())
        self.settings.set("last_env", self.env_combo.currentText())
        self.settings.set("project_folder", self.folder_edit.text().strip())

        self.settings.set("create_env_type", self.create_type_combo.currentText())
        self.settings.set("create_location_type", self.create_loc_combo.currentText())
        self.settings.set("create_extra_args", self.create_extra_edit.text().strip())
        self.settings.set(
            "create_python_version",
            "__default__" if self.create_pyver_combo.currentIndex() == 0
            else self._selected_python_version(),
        )

        self.settings.set("duplicate_dest_type", self.dup_dest_combo.currentText())
        self.settings.set("duplicate_custom_parent", self.dup_custom_edit.text().strip())

        self.settings.set("workspace_create_expanded", self.create_group.is_expanded)
        self.settings.set("workspace_duplicate_expanded", self.duplicate_group.is_expanded)

    # ==================================================================
    # Selection helpers
    # ==================================================================
    def get_selected_env_data(self):
        env_data = self.env_combo.currentData()
        if not env_data:
            QMessageBox.warning(self, "No Environment", "Please select a valid environment.")
            return None
        return env_data

    def _build_env_command(self, base_program, base_args):
        env_data = self.get_selected_env_data()
        if not env_data:
            return None, None, None
        if env_data["type"] == "conda":
            return (
                env_data["exe"],
                ["run", "-n", env_data["name"], base_program] + base_args,
                env_data,
            )
        return base_program, base_args, env_data

    # ==================================================================
    # Safety helpers (shared by clone & delete)
    # ==================================================================
    def _is_python_environment(self, path: str) -> bool:
        """True only if `path` is an existing, real (non-symlink) directory
        containing a venv/conda marker. PRIMARY guarantee for clone/delete."""
        if not path or not os.path.isdir(path) or os.path.islink(path):
            return False
        return any(os.path.exists(os.path.join(path, m)) for m in self._ENV_MARKERS)

    def _is_path_safe_to_delete(self, path: str):
        """Catastrophic-target guard for deletion. Returns (ok, reason)."""
        if not path:
            return False, "Empty path."
        real = os.path.realpath(os.path.abspath(path))  # resolve symlinks/.. first
        if not os.path.isdir(real):
            return False, "Target is not an existing directory."
        if os.path.islink(path):
            return False, "Target is a symlink."
        if os.path.ismount(real):
            return False, "Target is a filesystem root or mount point."
        home = os.path.realpath(os.path.expanduser("~"))
        if real == home:
            return False, "Target is the home directory."
        if home.startswith(real + os.sep):
            return False, "Target is an ancestor of the home directory."
        _, tail = os.path.splitdrive(real)
        if len([p for p in tail.split(os.sep) if p]) < 2:
            return False, "Target is too close to the filesystem root."
        return True, ""

    def _is_path_safe_to_create(self, path: str):
        """Guard for the DESTINATION of a clone/create. Returns (ok, reason)."""
        if not path:
            return False, "Empty destination path."
        real = os.path.realpath(os.path.abspath(path))
        if os.path.exists(real):
            return False, "Destination already exists."
        if os.path.ismount(real):
            return False, "Destination is a filesystem root or mount point."
        home = os.path.realpath(os.path.expanduser("~"))
        if real == home:
            return False, "Destination is the home directory."
        parent = os.path.dirname(real)
        if not parent or not os.path.isdir(parent):
            return False, "Destination's parent directory does not exist."
        _, tail = os.path.splitdrive(real)
        if len([p for p in tail.split(os.sep) if p]) < 2:
            return False, "Destination is too close to the filesystem root."
        return True, ""

    # ==================================================================
    # Browse handlers
    # ==================================================================
    def browse_env_base(self: WorkspaceHost):
        start_path = self._get_fallback_path(self.env_base_edit.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "Select Environment Base Folder", start_path)
        if folder:
            self.env_base_edit.setText(folder)
            self.save_current_settings()
            self.refresh_env_list()

    def browse_folder(self: WorkspaceHost):
        start_path = self._get_fallback_path(self.folder_edit.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", start_path)
        if folder:
            self.folder_edit.setText(folder)
            self.save_current_settings()
            if hasattr(self, "refresh_wheel_list"):
                self.refresh_wheel_list()

    def _browse_create_custom_path(self: WorkspaceHost):
        start_path = self._get_fallback_path(self.create_custom_edit.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "Select Custom Parent Folder", start_path)
        if folder:
            self.create_custom_edit.setText(folder)
            self.save_current_settings()

    def _browse_duplicate_custom_parent(self: WorkspaceHost):
        start_path = self._get_fallback_path(self.dup_custom_edit.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "Select Custom Parent Folder", start_path)
        if folder:
            self.dup_custom_edit.setText(folder)
            self.save_current_settings()

    # ==================================================================
    # Environment discovery
    # ==================================================================
    def _get_conda_executable(self, base_dir):
        parent_dir = (
            os.path.dirname(base_dir) if os.path.basename(base_dir) == "envs" else base_dir
        )
        candidates = []
        if os.name == "nt":
            candidates.extend(
                [
                    os.path.join(base_dir, "Scripts", "conda.exe"),
                    os.path.join(base_dir, "condabin", "conda.bat"),
                    os.path.join(parent_dir, "Scripts", "conda.exe"),
                    os.path.join(parent_dir, "condabin", "conda.bat"),
                ]
            )
        else:
            candidates.extend(
                [
                    os.path.join(base_dir, "bin", "conda"),
                    os.path.join(base_dir, "condabin", "conda"),
                    os.path.join(parent_dir, "bin", "conda"),
                    os.path.join(parent_dir, "condabin", "conda"),
                ]
            )
        for c in candidates:
            if os.path.exists(c):
                return c
        return None

    def refresh_env_list(self):
        base_dir = self.env_base_edit.text().strip()
        if not base_dir or not os.path.isdir(base_dir):
            return

        conda_exe = self._get_conda_executable(base_dir)
        self.env_combo.clear()
        self._set_env_actions_enabled(False)

        if conda_exe:
            self.env_combo.addItem("Loading Conda environments...")
            self._current_conda_exe = conda_exe

            self.env_list_process = EnvProcess(self)
            self.env_list_process.output_ready.connect(self._on_env_list_output)
            self.env_list_process.finished_signal.connect(self._on_env_list_finished)
            self.env_list_process.run_command(conda_exe, ["env", "list", "--json"])
        else:
            self._current_conda_exe = None
            venvs = []

            def is_venv(p):
                return os.path.exists(os.path.join(p, "pyvenv.cfg"))

            def is_conda_env(p):
                return os.path.exists(os.path.join(p, "conda-meta"))

            if is_venv(base_dir) or is_conda_env(base_dir):
                venvs.append(
                    {"name": os.path.basename(base_dir), "path": base_dir, "type": "venv"}
                )
            else:
                try:
                    for entry in os.scandir(base_dir):
                        if entry.is_dir() and (is_venv(entry.path) or is_conda_env(entry.path)):
                            venvs.append(
                                {"name": entry.name, "path": entry.path, "type": "venv"}
                            )
                except Exception:
                    pass

            if venvs:
                for v in venvs:
                    self.env_combo.addItem(f"venv: {v['name']}", userData=v)
                self._restore_last_env_selection()
            else:
                self.env_combo.addItem("No environments found")

            self._set_env_actions_enabled(True)

        self._sync_duplicate_source_label()

    def _on_env_list_output(self, data):
        if not hasattr(self, "_env_json_data"):
            self._env_json_data = ""
        self._env_json_data += data

    def _on_env_list_finished(self, exit_code, exit_status):
        self._set_env_actions_enabled(True)
        if exit_code != 0 or exit_status != QProcess.NormalExit:
            self.env_combo.clear()
            self.env_combo.addItem("Error listing environments")
            self._sync_duplicate_source_label()
            return

        try:
            data = json.loads(self._env_json_data)
            envs = data.get("envs", [])
            self.env_combo.clear()

            for env_path in envs:
                name = (
                    "base"
                    if env_path == data.get("default_prefix")
                    else os.path.basename(env_path)
                )
                self.env_combo.addItem(
                    f"conda: {name}",
                    userData={
                        "type": "conda",
                        "name": name,
                        "path": env_path,
                        "exe": self._current_conda_exe,
                    },
                )
            self._restore_last_env_selection()
        except Exception:
            self.env_combo.clear()
            self.env_combo.addItem("Parse error")
        finally:
            if hasattr(self, "_env_json_data"):
                delattr(self, "_env_json_data")
            self._sync_duplicate_source_label()

    def _restore_last_env_selection(self: WorkspaceHost):
        last_env = self.settings.get("last_env")
        if last_env:
            idx = self.env_combo.findText(last_env)
            if idx >= 0:
                self.env_combo.setCurrentIndex(idx)

    # ==================================================================
    # Actions: Create / Duplicate / Delete  (inline, confirm-only dialogs)
    # ==================================================================
    def _execute_env_modification(self: WorkspaceHost, program, args, cmd_name):
        """Run the command, disable UI, and wire up the refresh signal safely."""
        self._set_env_actions_enabled(False)
        self.run_command(
            program=program,
            args=args,
            working_dir=None,
            command_name=cmd_name,
            env_data={"type": "system"},
            refresh_packages=False,
            require_msvc=False,
        )
        if self.current_process:
            # UniqueConnection prevents multiple bindings on rapid clicks.
            self.current_process.finished_signal.connect(
                self._on_env_modification_finished, Qt.UniqueConnection
            )

    def on_create_clicked(self: WorkspaceHost):
        """Validate the inline create form, confirm, then run. No creation dialog."""
        base_dir = self.env_base_edit.text().strip()
        if not base_dir or not os.path.isdir(base_dir):
            QMessageBox.warning(self, "Invalid Base Dir", "Please specify a valid base directory first.")
            return

        env_type = self.create_type_combo.currentText()
        name = self.create_name_edit.text().strip()
        loc_type = self.create_loc_combo.currentText()
        pyver = self._selected_python_version()
        extra_args = [x for x in self.create_extra_edit.text().split() if x]

        # Resolve destination
        if loc_type == "Default Base Directory":
            if not name:
                QMessageBox.warning(self, "Invalid Name", "Please provide a name for the environment.")
                return
            destination = os.path.join(base_dir, name)
        else:
            custom = self.create_custom_edit.text().strip()
            if not custom:
                QMessageBox.warning(self, "Invalid Path", "Please select or enter a custom destination path.")
                return
            # Treat the custom field as a PARENT folder when a name is given;
            # otherwise treat it as the full destination path.
            destination = os.path.join(custom, name) if name else custom

        safe, reason = self._is_path_safe_to_create(destination)
        if not safe:
            QMessageBox.warning(self, "Invalid Destination", f"Cannot create at:\n{destination}\n\n{reason}")
            return

        # Build the command
        if env_type == "Venv via Python":
            # NOTE: under PyInstaller, sys.executable is the frozen app, not a real
            # interpreter; locate a system python if you freeze this app.
            program = sys.executable
            args = ["-m", "venv", destination] + extra_args
            cmd_name = "create_venv_python"
            method = f"{os.path.basename(sys.executable)} -m venv"
        elif env_type == "Venv via UV":
            program = "uv"
            args = ["venv", destination]
            if pyver:
                args += ["--python", pyver]  # uv fetches the interpreter if needed
            args += extra_args
            cmd_name = "create_venv_uv"
            method = "uv venv"
        else:  # Conda
            program = getattr(self, "_current_conda_exe", None)
            if not program:
                QMessageBox.warning(self, "Conda Error", "Conda executable was not auto-detected. Check base directory.")
                return
            args = ["create", "--prefix", destination, "-y"]
            if pyver:
                args.append(f"python={pyver}")
            if extra_args:
                args.extend(extra_args)
            cmd_name = "create_conda_env"
            method = "conda create"

        details = (
            f"Create a new environment?\n\n"
            f"Type:        {env_type}\n"
            f"Destination: {destination}\n"
            f"Method:      {method}\n"
        )
        if env_type in ("Venv via UV", "Conda Environment"):
            details += f"Python:      {pyver or 'latest / default'}\n"
        if extra_args:
            details += f"Extra:       {' '.join(extra_args)}\n"

        if QMessageBox.question(
            self, "Confirm Environment Creation", details + "\nProceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        self._execute_env_modification(program, args, cmd_name)

    def on_duplicate_clicked(self: WorkspaceHost):
        """Validate the inline duplicate form, confirm, then clone. No input dialog."""
        env_data = self.get_selected_env_data()
        if not env_data:
            return

        src_path = env_data.get("path")
        if not src_path:
            QMessageBox.warning(self, "Unsupported", "Cannot resolve the path for duplication.")
            return

        # Guard 1 (primary): source must currently be a recognizable environment.
        if not self._is_python_environment(src_path):
            QMessageBox.warning(
                self, "Not an Environment",
                "The selected folder is no longer a recognizable virtual or conda "
                "environment (no pyvenv.cfg or conda-meta). Duplication aborted.",
            )
            return

        new_name = self.dup_name_edit.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a name for the duplicate.")
            return

        # Resolve destination parent
        if self.dup_dest_combo.currentText() == "Custom Parent Folder":
            parent_dir = self.dup_custom_edit.text().strip()
            if not parent_dir:
                QMessageBox.warning(self, "Invalid Path", "Please choose a custom parent folder.")
                return
            if not os.path.isdir(parent_dir):
                QMessageBox.warning(self, "Invalid Path", f"Parent folder does not exist:\n{parent_dir}")
                return
        else:
            parent_dir = os.path.dirname(src_path)

        dest_path = os.path.join(parent_dir, new_name)

        # Guard 2: destination must be a safe, brand-new location.
        safe, reason = self._is_path_safe_to_create(dest_path)
        if not safe:
            QMessageBox.warning(self, "Invalid Destination", f"Cannot create the duplicate at:\n{dest_path}\n\n{reason}")
            return

        method = "Recursive copy (copytree)" if env_data["type"] == "venv" else "conda --clone"

        if QMessageBox.question(
            self, "Confirm Duplication",
            f"Create a copy of environment '{env_data['name']}'?\n\n"
            f"Source:      {src_path}\n"
            f"Destination: {dest_path}\n"
            f"Method:      {method}\n\n"
            f"This copies the entire environment and may take a while.\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        if env_data["type"] == "venv":
            program = sys.executable
            # Self-guarding clone: the copying process re-checks that the source is an
            # environment and that the destination does not exist BEFORE copytree runs.
            code = (
                "import os, shutil, sys; "
                "s, d = sys.argv[1], sys.argv[2]; "
                "(os.path.isdir(s) and not os.path.islink(s) and "
                "(os.path.exists(os.path.join(s, 'pyvenv.cfg')) or "
                "os.path.exists(os.path.join(s, 'conda-meta')))) "
                "or sys.exit('REFUSED: source is not a Python environment: ' + s); "
                "(not os.path.exists(d)) or sys.exit('REFUSED: destination already exists: ' + d); "
                "shutil.copytree(s, d, symlinks=True, ignore_dangling_symlinks=True); "
                "print('Environment copy completed successfully!')"
            )
            args = ["-c", code, src_path, dest_path]
            cmd_name = "duplicate_venv"
        else:  # Conda: `create --clone` validates the source is a real conda env.
            program = env_data.get("exe") or getattr(self, "_current_conda_exe", None)
            if not program:
                QMessageBox.warning(self, "Conda Error", "Conda executable path was not resolved.")
                return
            args = ["create", "--prefix", dest_path, "--clone", src_path, "-y"]
            cmd_name = "duplicate_conda"

        self._execute_env_modification(program, args, cmd_name)

    def delete_selected_env(self: WorkspaceHost):
        """Permanently delete the selected environment folder (confirm + guards)."""
        env_data = self.get_selected_env_data()
        if not env_data:
            return

        src_path = env_data.get("path")
        if not src_path:
            QMessageBox.warning(self, "Unsupported", "Cannot resolve the directory path for deletion.")
            return

        # Guard 1: refuse catastrophic locations regardless of markers.
        safe, reason = self._is_path_safe_to_delete(src_path)
        if not safe:
            QMessageBox.warning(self, "Safety Guard", f"Refused to delete this location.\n\n{reason}")
            return

        # Guard 2 (primary): must currently be a recognizable environment.
        if not self._is_python_environment(src_path):
            QMessageBox.warning(
                self, "Not an Environment",
                "The selected folder is no longer a recognizable virtual or conda "
                "environment (no pyvenv.cfg or conda-meta). Deletion aborted.",
            )
            return

        if QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to permanently delete environment '{env_data['name']}'?\n\n"
            f"Location: {src_path}\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        if env_data["type"] == "venv":
            program = sys.executable
            # Self-guarding delete: the deleting process re-checks the env marker before
            # rmtree. The lambda handles read-only files without needing a `def` (which
            # is invalid syntax inside a `python -c` one-liner).
            code = (
                "import os, stat, shutil, sys; "
                "p = sys.argv[1]; "
                "(os.path.isdir(p) and not os.path.islink(p) and "
                "(os.path.exists(os.path.join(p, 'pyvenv.cfg')) or "
                "os.path.exists(os.path.join(p, 'conda-meta')))) "
                "or sys.exit('REFUSED: not a Python environment: ' + p); "
                "shutil.rmtree(p, onerror=lambda fn, pth, exc: (os.chmod(pth, stat.S_IWRITE), fn(pth))); "
                "print('Environment deleted successfully!')"
            )
            args = ["-c", code, src_path]
            cmd_name = "delete_venv"
        else:  # Conda: `env remove --prefix` refuses non-conda prefixes.
            program = env_data.get("exe") or getattr(self, "_current_conda_exe", None)
            if not program:
                QMessageBox.warning(self, "Conda Error", "Conda executable path was not resolved.")
                return
            args = ["env", "remove", "--prefix", src_path, "-y"]
            cmd_name = "delete_conda"

        self._execute_env_modification(program, args, cmd_name)

    def _on_env_modification_finished(self, exit_code, exit_status):
        """Called when a create/duplicate/delete background task finishes."""
        # Drop the single connection so it doesn't re-trigger on unrelated tasks.
        if hasattr(self, "current_process") and self.current_process:
            try:
                self.current_process.finished_signal.disconnect(self._on_env_modification_finished)
            except (TypeError, RuntimeError):
                pass

        # Non-zero exit means failure or a refusal by an in-subprocess guard
        # (the "REFUSED: ..." messages). Surface it rather than silently refreshing.
        if exit_code != 0 or exit_status != QProcess.NormalExit:
            QMessageBox.warning(
                self,
                "Operation Did Not Complete",
                "The environment operation did not finish successfully. No changes "
                "were made, or they were rolled back. Check the command output/log "
                "for details.",
            )

        self.refresh_env_list()