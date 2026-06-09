"""
Dialog to show detected packages and let user choose actions.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QComboBox, QDialogButtonBox
)


class DependencyUpdateDialog(QDialog):
    def __init__(self, detected_packages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detected Third‑Party Imports")
        self.resize(900, 550)
        self.detected = detected_packages

        layout = QVBoxLayout(self)

        info_label = QLabel(
            "The following third‑party packages were detected from import statements.\n"
            "Select which ones to add/update in pyproject.toml, choose a version policy, and indicate whether they are development dependencies."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Table: Add | Dev | Package | Import Name | Installed | Latest | Version Constraint
        self.table = QTableWidget(len(detected_packages), 7)
        self.table.setHorizontalHeaderLabels(["Add", "Dev", "Package", "Import Name", "Installed", "Latest", "Version Constraint"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)

        for row, (pkg_name, info) in enumerate(detected_packages.items()):
            # Add checkbox
            chk_add = QCheckBox()
            chk_add.setChecked(True)
            self.table.setCellWidget(row, 0, chk_add)

            # Dev checkbox – pre‑checked if detection marked it as dev only
            chk_dev = QCheckBox()
            chk_dev.setChecked(info.get('dev', False))
            self.table.setCellWidget(row, 1, chk_dev)

            # Package name
            self.table.setItem(row, 2, QTableWidgetItem(pkg_name))
            # Import name
            self.table.setItem(row, 3, QTableWidgetItem(info['import_name']))
            # Installed version
            installed = info['installed'] or "not installed"
            self.table.setItem(row, 4, QTableWidgetItem(installed))
            # Latest version
            latest = info['latest'] or "unknown"
            self.table.setItem(row, 5, QTableWidgetItem(latest))
            # Version constraint combo
            combo = QComboBox()
            combo.addItems(["Keep as is (no change)", ">= latest", "== latest", "Keep existing constraint (if any)"])
            combo.setToolTip("How to pin this package in pyproject.toml")
            self.table.setCellWidget(row, 6, combo)

        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_selected(self):
        """Return list of (pkg_name, version_constraint_str, is_dev) for checked rows."""
        result = []
        for row in range(self.table.rowCount()):
            chk_add = self.table.cellWidget(row, 0)
            if chk_add and chk_add.isChecked():
                pkg_item = self.table.item(row, 2)
                if pkg_item:
                    pkg_name = pkg_item.text()
                    combo = self.table.cellWidget(row, 6)
                    constraint_choice = combo.currentText()
                    chk_dev = self.table.cellWidget(row, 1)
                    is_dev = chk_dev.isChecked() if chk_dev else False
                    result.append((pkg_name, constraint_choice, is_dev))
        return result