from pathlib import Path
from PySide6.QtCore import QDir

class CoreUIMixin:
    """Contains shared generic UI styling and path helper methods."""

    def _setup_button(self, button, tooltip=""):
        button.setMinimumHeight(35)
        if tooltip:
            button.setToolTip(tooltip)

    def _style_critical_button(self, button, bg_color, border_color):
        """Applies a distinct color style to critical action buttons."""
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                font-weight: bold;
                border: 1px solid {border_color};
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton:hover {{
                background-color: {border_color};
            }}
            QPushButton:disabled {{
                background-color: #555555;
                color: #aaaaaa;
                border: 1px solid #444444;
            }}
        """)

    def _style_square_icon_button(self, button):
        """Make a button square (32x32) for icon-only buttons."""
        button.setFixedSize(32, 32)
        # Optionally, you can uncomment the next line for rounded corners:
        # button.setStyleSheet("border-radius: 6px;")
        return button

    def _get_fallback_path(self, current_path):
        if not current_path:
            return QDir.homePath()
        path = Path(current_path).resolve()
        while path.parent != path:
            if path.exists() and path.is_dir():
                return str(path)
            path = path.parent
        if path.exists() and path.is_dir():
            return str(path)
        return QDir.homePath()

    def set_action_buttons_enabled(self, enabled):
        """Dynamically enables/disables critical UI buttons during processes."""
        btn_names = [
            'run_cargo_btn', 'run_maturin_btn', 'uninstall_btn', 
            'global_uninstall_btn', 'install_btn', 'global_update_btn'
        ]
        for btn in btn_names:
            if hasattr(self, btn):
                getattr(self, btn).setEnabled(enabled)