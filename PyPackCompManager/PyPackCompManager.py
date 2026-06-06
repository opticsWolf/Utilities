import sys
import os
from PySide6.QtWidgets import QMainWindow, QApplication
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon

# Import from custom modules
from settings_manager import Settings
from core_ui_helpers import CoreUIMixin
from terminal_ui_pane import TerminalMixin
from workspace_setup_pane import WorkspaceMixin
from build_tools_pane import BuildToolsMixin
from nuitka_pane import NuitkaMixin
from local_packages_pane import LocalPackagesMixin
from global_packages_pane import GlobalPackagesMixin

class MainWindow(
    QMainWindow, 
    CoreUIMixin, 
    TerminalMixin, 
    WorkspaceMixin, 
    BuildToolsMixin,
    NuitkaMixin,
    LocalPackagesMixin, 
    GlobalPackagesMixin
):
    """
    Main application window inheriting functionality from separated Mixin submodules.
    This guarantees that the UI logic is broken out while acting as one cohesive object at runtime.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python Package Compiler & Manager v0.5")
        self.setMinimumSize(1000, 700)

        # Load and set the window icon
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Allow flexible nesting, tabbed docking, and animation
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)

        self.settings = Settings()
        self.current_process = None
        self.env_list_process = None
        self._current_conda_exe = None
        self._is_loading = False   # Prevent saving during load

        self._build_ui()
        self.load_settings_to_ui()

        if self.settings.get("env_base_dir"):
            self.refresh_env_list()
        self.refresh_wheel_list()

    def _build_ui(self):
        """Orchestrates the UI construction using the separated mixins."""
        self.setCentralWidget(self._build_terminal_ui())
        
        # 1. Generate and store references to the left dock widgets
        workspace_dock = self._build_workspace_dock()
        build_tools_dock = self._build_tools_dock()
        nuitka_dock = self._build_nuitka_dock()
        
        self.addDockWidget(Qt.LeftDockWidgetArea, workspace_dock)
        
        self.addDockWidget(Qt.LeftDockWidgetArea, build_tools_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, nuitka_dock)
        
        self.tabifyDockWidget(build_tools_dock, nuitka_dock)
        build_tools_dock.raise_()
        
        self.addDockWidget(Qt.RightDockWidgetArea, self._build_local_packages_dock())
        self.addDockWidget(Qt.RightDockWidgetArea, self._build_global_packages_dock())

    def load_settings_to_ui(self):
        """Distributes the load command to all UI submodules."""
        self._is_loading = True
        try:
            self._load_workspace_settings()
            self._load_build_settings()
            self._load_nuitka_settings()
            self._load_local_settings()
            self._load_global_settings()
        
            # Restore window geometry (size/position) and state (dock layouts)
            geometry_b64 = self.settings.get("window_geometry", "")
            if geometry_b64:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode('utf-8')))
                
            state_b64 = self.settings.get("window_state", "")
            if state_b64:
                self.restoreState(QByteArray.fromBase64(state_b64.encode('utf-8')))
        finally:
            self._is_loading = False

    def save_current_settings(self):
        """Distributes the set state commands to submodules and then triggers one global disk save."""
        if getattr(self, '_is_loading', False):
            return   # Do not save while loading, as it would overwrite saved settings with defaults

        self._save_workspace_settings()
        self._save_build_settings()
        self._save_nuitka_settings()
        self._save_local_settings()
        self._save_global_settings()

        # Save window geometry and state as base64 strings so JSON can store them
        geom = self.saveGeometry().toBase64().data().decode('utf-8')
        state = self.saveState().toBase64().data().decode('utf-8')
        
        self.settings.set("window_geometry", geom)
        self.settings.set("window_state", state)
        
        # Flush all the gathered states to the settings.json file precisely once
        self.settings.save()

    def closeEvent(self, event):
        """Intercept the window close event to ensure layout and settings are saved."""
        self.save_current_settings()
        super().closeEvent(event)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    # Set application icon (affects taskbar/dock)
    icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()