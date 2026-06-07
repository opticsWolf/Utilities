from pathlib import Path
from PySide6.QtCore import QDir, Qt
from PySide6.QtWidgets import QGroupBox, QWidget, QVBoxLayout

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


class CollapsibleGroupBox(QGroupBox):
    """A native-looking QGroupBox that toggles its content when the title is clicked."""
    
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._base_title = title
        self.is_expanded = True

        # Create the internal widget that will be hidden/shown
        self.content_widget = QWidget()

        # Main layout for the QGroupBox itself
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(3, 3, 3, 3)   
        self._main_layout.addWidget(self.content_widget)

        self._update_title()

    def _update_title(self):
        # FIXED: Changed the collapsed indicator to a right-pointing arrow
        indicator = "▾" if self.is_expanded else "▸"
        self.setTitle(f"{indicator}  {self._base_title}")

    def mousePressEvent(self, event):
        # Intercept clicks on the top area of the group box
        if event.button() == Qt.MouseButton.LeftButton:
            # Dynamically calculate the title area height based on font size
            title_height = self.fontMetrics().height()

            # If the click happens in the top area, toggle visibility
            if event.position().y() <= title_height:
                self.is_expanded = not self.is_expanded
                self.content_widget.setVisible(self.is_expanded)
                self._update_title()

                # --- OPTIMIZATION FOR A VERY THIN BOX ---
                if self.is_expanded:
                    # Remove height restriction when expanded (16777215 is QWIDGETSIZE_MAX)
                    self.setMaximumHeight(16777215) 
                else:
                    # Clamp the maximum height to just the title area and top margin when collapsed
                    self.setMaximumHeight(title_height + self._main_layout.contentsMargins().top())

                event.accept()
                return

        # Pass any other clicks (inside the widget) to the base class
        super().mousePressEvent(event)