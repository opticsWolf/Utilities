import os
import json
from PySide6.QtWidgets import (QDockWidget, QScrollArea, QWidget, QVBoxLayout, 
                               QHBoxLayout, QFormLayout, QGroupBox, QLineEdit, 
                               QPushButton, QComboBox, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, QProcess
from process_wrapper import EnvProcess

class WorkspaceMixin:
    """Manages the Environment selection and Project folder UI."""

    def _build_workspace_dock(self):
        workspace_dock = QDockWidget("Workspace Setup", self)
        workspace_dock.setObjectName("workspaceDock")
        workspace_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        workspace_dock.setFeatures(QDockWidget.DockWidgetMovable)
        
        workspace_widget = QWidget()
        workspace_layout = QVBoxLayout(workspace_widget)

        # Environment Configuration
        env_group = QGroupBox("Environment Configuration")
        env_layout = QFormLayout(env_group)

        self.env_base_edit = QLineEdit()
        self.env_base_edit.setToolTip("The base directory containing your virtual environments or the conda 'envs' folder.")
        browse_env_base_btn = QPushButton("📂")
        self._setup_button(browse_env_base_btn, "Browse for your environment base directory.")
        browse_env_base_btn.clicked.connect(self.browse_env_base)
        self._style_square_icon_button(browse_env_base_btn)
        
        env_path_layout = QHBoxLayout()
        env_path_layout.addWidget(self.env_base_edit)
        env_path_layout.addWidget(browse_env_base_btn)
        env_layout.addRow("Base Directory:", env_path_layout)

        self.env_combo = QComboBox()
        self.env_combo.setToolTip("Select the active environment (Conda or Venv) to run the build tools in.")
        refresh_env_btn = QPushButton("🔄")
        self._setup_button(refresh_env_btn, "Refresh the list of available environments.")
        refresh_env_btn.clicked.connect(self.refresh_env_list)
        self._style_square_icon_button(refresh_env_btn)
        
        env_combo_layout = QHBoxLayout()
        env_combo_layout.addWidget(self.env_combo)
        env_combo_layout.addWidget(refresh_env_btn)
        env_layout.addRow("Environment:", env_combo_layout)

        workspace_layout.addWidget(env_group)

        # Project Folder
        folder_group = QGroupBox("Project Folder")
        folder_layout = QHBoxLayout(folder_group)
        self.folder_edit = QLineEdit()
        self.folder_edit.setToolTip("The root folder of your Rust/Python project (where Cargo.toml is located).")
        browse_folder_btn = QPushButton("📂")
        self._setup_button(browse_folder_btn, "Browse for your project folder.")
        browse_folder_btn.clicked.connect(self.browse_folder)
        self._style_square_icon_button(browse_folder_btn)
        
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(browse_folder_btn)
        
        workspace_layout.addWidget(folder_group)
        workspace_layout.addStretch()
        
        workspace_dock.setWidget(workspace_widget)
        return workspace_dock

    def _load_workspace_settings(self):
        self.env_base_edit.setText(self.settings.get("env_base_dir", ""))
        self.folder_edit.setText(self.settings.get("project_folder", ""))

    def _save_workspace_settings(self):
        self.settings.set("env_base_dir", self.env_base_edit.text().strip())
        self.settings.set("last_env", self.env_combo.currentText())
        self.settings.set("project_folder", self.folder_edit.text().strip())

    def get_selected_env_data(self):
        env_data = self.env_combo.currentData()
        if not env_data:
            QMessageBox.warning(self, "No Environment", "Please select a valid environment.")
            return None
        return env_data

    def _build_env_command(self, base_program, base_args):
        env_data = self.get_selected_env_data()
        if not env_data: return None, None, None
        if env_data["type"] == "conda":
            return env_data["exe"], ["run", "-n", env_data["name"], base_program] + base_args, env_data
        return base_program, base_args, env_data

    def browse_env_base(self):
        start_path = self._get_fallback_path(self.env_base_edit.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "Select Environment Base Folder", start_path)
        if folder:
            self.env_base_edit.setText(folder)
            self.save_current_settings()
            self.refresh_env_list()

    def browse_folder(self):
        start_path = self._get_fallback_path(self.folder_edit.text().strip())
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", start_path)
        if folder:
            self.folder_edit.setText(folder)
            self.save_current_settings()
            if hasattr(self, 'refresh_wheel_list'):
                self.refresh_wheel_list()

    def _get_conda_executable(self, base_dir):
        parent_dir = os.path.dirname(base_dir) if os.path.basename(base_dir) == "envs" else base_dir
        candidates = []
        if os.name == "nt":
            candidates.extend([
                os.path.join(base_dir, "Scripts", "conda.exe"),
                os.path.join(base_dir, "condabin", "conda.bat"),
                os.path.join(parent_dir, "Scripts", "conda.exe"),
                os.path.join(parent_dir, "condabin", "conda.bat"),
            ])
        else:
            candidates.extend([
                os.path.join(base_dir, "bin", "conda"),
                os.path.join(base_dir, "condabin", "conda"),
                os.path.join(parent_dir, "bin", "conda"),
                os.path.join(parent_dir, "condabin", "conda"),
            ])
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
        
        if conda_exe:
            self.env_combo.addItem("Loading Conda environments...")
            self.env_combo.setEnabled(False)
            self._current_conda_exe = conda_exe

            self.env_list_process = EnvProcess(self)
            self.env_list_process.output_ready.connect(self._on_env_list_output)
            self.env_list_process.finished_signal.connect(self._on_env_list_finished)
            self.env_list_process.run_command(conda_exe, ["env", "list", "--json"])
        else:
            self._current_conda_exe = None
            venvs = []
            
            def is_venv(p): return os.path.exists(os.path.join(p, "pyvenv.cfg"))
            def is_conda_env(p): return os.path.exists(os.path.join(p, "conda-meta"))

            if is_venv(base_dir) or is_conda_env(base_dir):
                venvs.append({"name": os.path.basename(base_dir), "path": base_dir, "type": "venv"})
            else:
                try:
                    for entry in os.scandir(base_dir):
                        if entry.is_dir() and (is_venv(entry.path) or is_conda_env(entry.path)):
                            venvs.append({"name": entry.name, "path": entry.path, "type": "venv"})
                except Exception:
                    pass

            if venvs:
                for v in venvs:
                    self.env_combo.addItem(f"venv: {v['name']}", userData=v)
                self._restore_last_env_selection()
            else:
                self.env_combo.addItem("No environments found")

    def _on_env_list_output(self, data):
        if not hasattr(self, '_env_json_data'): self._env_json_data = ""
        self._env_json_data += data

    def _on_env_list_finished(self, exit_code, exit_status):
        self.env_combo.setEnabled(True)
        if exit_code != 0 or exit_status != QProcess.NormalExit:
            self.env_combo.clear()
            self.env_combo.addItem("Error listing environments")
            return

        try:
            data = json.loads(self._env_json_data)
            envs = data.get("envs", [])
            self.env_combo.clear()
            
            for env_path in envs:
                name = "base" if env_path == data.get("default_prefix") else os.path.basename(env_path)
                self.env_combo.addItem(f"conda: {name}", userData={"type": "conda", "name": name, "exe": self._current_conda_exe})
            self._restore_last_env_selection()
        except Exception:
            self.env_combo.clear()
            self.env_combo.addItem("Parse error")
        finally:
            if hasattr(self, '_env_json_data'): delattr(self, '_env_json_data')

    def _restore_last_env_selection(self):
        last_env = self.settings.get("last_env")
        if last_env:
            idx = self.env_combo.findText(last_env)
            if idx >= 0: self.env_combo.setCurrentIndex(idx)