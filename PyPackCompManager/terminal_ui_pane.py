import re
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QProgressBar, QMessageBox, QSplitter,
    QBoxLayout)
from PySide6.QtGui import QFont, QTextCursor, QKeyEvent
from PySide6.QtCore import Qt, QTimer, QProcess, Signal
from process_wrapper import EnvProcess
from settings_manager import Settings   # <-- added import


class HistoryTextEdit(QTextEdit):
    """Custom QTextEdit for terminal input with history and Enter-to-send support."""
    returnPressed = Signal()
    historyChanged = Signal()   # <-- added signal to notify about history updates

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []
        self.history_index = 0
        self._current_draft = ""
        self.setAcceptRichText(False)

    def text(self):
        """Maintain compatibility with QLineEdit's .text() method."""
        return self.toPlainText()

    def add_to_history(self, text):
        """Add a command to the history buffer (max 100)."""
        text = text.strip()
        if not text:
            return

        # Prevent consecutive duplicates
        if not self.history or self.history[-1] != text:
            self.history.append(text)
            if len(self.history) > 100:
                self.history.pop(0)

        self.history_index = len(self.history)
        self._current_draft = ""
        self.historyChanged.emit()   # <-- notify that history changed

    def set_history(self, history):
        """Restore history from saved settings."""
        self.history = history[-100:] if history else []
        self.history_index = len(self.history)
        self._current_draft = ""

    def keyPressEvent(self, event: QKeyEvent):
        # Handle Enter for sending (Shift+Enter for a new line)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
            return

        cursor = self.textCursor()

        # Handle Up Arrow (Triggers if cursor is at the start OR at the end)
        if event.key() == Qt.Key_Up:
            if cursor.atStart() or cursor.atEnd():
                self._navigate_history(-1)
                return

        # Handle Down Arrow (Triggers if cursor is at the start OR at the end)
        elif event.key() == Qt.Key_Down:
            if cursor.atStart() or cursor.atEnd():
                self._navigate_history(1)
                return

        super().keyPressEvent(event)

    def _navigate_history(self, direction):
        if not self.history:
            return

        if self.history_index == len(self.history):
            self._current_draft = self.toPlainText()

        new_index = self.history_index + direction

        if 0 <= new_index < len(self.history):
            self.history_index = new_index
            self.setPlainText(self.history[self.history_index])
            self.moveCursor(QTextCursor.End)
        elif new_index == len(self.history):
            self.history_index = new_index
            self.setPlainText(self._current_draft)
            self.moveCursor(QTextCursor.End)


class ResponsiveInputWidget(QWidget):
    """An input container that dynamically repositions its buttons based on its height."""

    def __init__(self, input_line, send_btn, clear_btn, parent=None):
        super().__init__(parent)
        self.input_line = input_line
        self.send_btn = send_btn
        self.clear_btn = clear_btn

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.main_layout.addWidget(QLabel("> "), 0, Qt.AlignTop)
        self.main_layout.addWidget(self.input_line, 1)

        self.btn_layout = QBoxLayout(QBoxLayout.TopToBottom)
        self.btn_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_layout.addWidget(self.send_btn)
        self.btn_layout.addWidget(self.clear_btn)
        self.stretch_item = self.btn_layout.addStretch()

        self.main_layout.addLayout(self.btn_layout, 0)

    def resizeEvent(self, event):
        if event.size().height() < 70:
            if self.btn_layout.direction() != QBoxLayout.LeftToRight:
                self.btn_layout.setDirection(QBoxLayout.LeftToRight)
        else:
            if self.btn_layout.direction() != QBoxLayout.TopToBottom:
                self.btn_layout.setDirection(QBoxLayout.TopToBottom)
        super().resizeEvent(event)


class TerminalMixin:
    """Manages the central terminal widget, ANSI parsing, and process execution logic.
    Also handles persistence of splitter sizes and command history via Settings.
    """

    def __init__(self):
        self._init_attributes()
        self.settings = None          # will be set by set_settings_manager()
        self.splitter = None          # reference to the QSplitter

    def _init_attributes(self):
        """Ensure all mixin attributes exist (lazy initialisation)."""
        if not hasattr(self, '_prompt_pending'):
            self._prompt_pending = False
        if not hasattr(self, '_cr_pending'):
            self._cr_pending = False
        if not hasattr(self, '_ansi_bold'):
            self._ansi_bold = False
        if not hasattr(self, '_ansi_color'):
            self._ansi_color = None
        if not hasattr(self, 'current_process'):
            self.current_process = None
        if not hasattr(self, '_refresh_packages_after'):
            self._refresh_packages_after = False
        if not hasattr(self, '_pending_command'):
            self._pending_command = None
        if not hasattr(self, '_ansi_buffer'):
            self._ansi_buffer = ""

    def _load_terminal_settings(self):
        """Restore splitter sizes and command history from settings."""
        if not self.settings:
            return
        # Restore splitter sizes
        if self.splitter:
            sizes = self.settings.get("splitter_sizes", [])
            if len(sizes) == 2:
                self.splitter.setSizes(sizes)
        # Restore command history
        history = self.settings.get("command_history", [])
        if history and hasattr(self, 'input_line'):
            self.input_line.set_history(history)

    def _save_terminal_settings(self):
        """Save current splitter sizes and command history to settings."""
        if not self.settings:
            return
        if self.splitter:
            self.settings.set("splitter_sizes", self.splitter.sizes())
        if hasattr(self, 'input_line'):
            self.settings.set("command_history", self.input_line.history[-100:])

    # ----- Helper for square icon buttons -----
    def _style_square_icon_button(self, button):
        button.setFixedSize(30, 30)
        button.setStyleSheet("""
            QPushButton {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #555;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #3d3d3d; }
            QPushButton:pressed { background-color: #1d1d1d; }
        """)

    # ----- Build UI -----
    def _build_terminal_ui(self):
        self._init_attributes()
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        # Create Splitter and store reference
        splitter = QSplitter(Qt.Vertical)
        self.splitter = splitter

        # 1. Output Area (Top)
        output_widget = QWidget()
        output_widget.setMinimumHeight(150)
        output_layout = QVBoxLayout(output_widget)
        output_layout.setContentsMargins(0, 0, 0, 0)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Monospace", 10))

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        output_layout.addWidget(QLabel("<b>Terminal Output</b>"))
        output_layout.addWidget(self.output_text)
        output_layout.addWidget(self.progress_bar)

        splitter.addWidget(output_widget)

        # 2. Input Area Setup (Bottom)
        self.input_line = HistoryTextEdit()
        self.input_line.setPlaceholderText("Type a command and press Enter (Shift+Enter for newline)...")
        self.input_line.returnPressed.connect(self._send_input)
        self.input_line.setEnabled(True)

        # Connect history change signal to auto-save (optional)
        # self.input_line.historyChanged.connect(self.save_settings)  # uncomment for real‑time saving

        font_metrics = self.input_line.fontMetrics()
        line_height = font_metrics.lineSpacing()
        doc_margin = self.input_line.document().documentMargin()
        max_height = (line_height * 5) + int(doc_margin * 2) + 10

        self.send_btn = QPushButton("⬆️")
        self._style_square_icon_button(self.send_btn)
        self.send_btn.setToolTip("Send command")
        self.send_btn.clicked.connect(self._send_input)

        self.clear_btn = QPushButton("🧹")
        self._style_square_icon_button(self.clear_btn)
        self.clear_btn.setToolTip("Clear terminal output")
        self.clear_btn.clicked.connect(self.output_text.clear)

        input_widget = ResponsiveInputWidget(self.input_line, self.send_btn, self.clear_btn)
        input_widget.setMinimumHeight(line_height + 15)
        input_widget.setMaximumHeight(max_height)

        splitter.addWidget(input_widget)

        # Splitter Settings
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        main_layout.addWidget(splitter)

        return central_widget

    # ----- ANSI to HTML (preserves colors, bold, and spaces) -----
    def _ansi_to_html(self, text):
        """Convert ANSI escape codes to HTML, preserving colors, bold, and whitespace."""
        self._init_attributes()
        text = re.sub(r'\x1B\].*?(?:\x07|\x1B\\)', '', text)
        text = re.sub(r'\x1B\[[0-9;?]*[^m]', '', text)
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = text.replace(' ', '&nbsp;')

        colors = {
            '30': '#000000', '31': '#cd3131', '32': '#0dbc79', '33': '#e5e510',
            '34': '#2472c8', '35': '#bc3fbc', '36': '#11a8cd', '37': '#e5e5e5',
            '90': '#666666', '91': '#f14c4c', '92': '#23d18b', '93': '#f5f543',
            '94': '#3b8eea', '95': '#d670d6', '96': '#29b8db', '97': '#e5e5e5',
        }

        html = ""
        if self._ansi_bold:
            html += '<b>'
        if self._ansi_color:
            html += f'<span style="color: {self._ansi_color};">'

        ansi_re = re.compile(r'\x1B\[([0-9;]*)m')
        last_end = 0

        for match in ansi_re.finditer(text):
            html += text[last_end:match.start()]
            codes = match.group(1).split(';')
            if not codes or codes == ['']:
                codes = ['0']

            for code in codes:
                if code == '0':
                    if self._ansi_color:
                        html += '</span>'
                        self._ansi_color = None
                    if self._ansi_bold:
                        html += '</b>'
                        self._ansi_bold = False
                elif code == '1':
                    if not self._ansi_bold:
                        html += '<b>'
                        self._ansi_bold = True
                elif code in colors:
                    if self._ansi_color:
                        html += '</span>'
                    html += f'<span style="color: {colors[code]};">'
                    self._ansi_color = colors[code]

            last_end = match.end()

        html += text[last_end:]
        if self._ansi_color:
            html += '</span>'
        if self._ansi_bold:
            html += '</b>'

        return html

    # ----- Logging (no double escaping) -----
    def _log_terminal(self, text, is_html=False):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        if is_html:
            cursor.insertHtml(text)
        else:
            cursor.insertText(text)
        self.output_text.verticalScrollBar().setValue(
            self.output_text.verticalScrollBar().maximum()
        )

    # ----- Starting a shell with forced initial prompt -----
    def _start_default_shell(self):
        if sys.platform == "win32":
            shell_program = "cmd.exe"
            shell_args = ["/K"]
        else:
            import os
            shell_program = os.environ.get("SHELL", "/bin/bash")
            shell_args = ["-i"]

        self._log_terminal(f"\n>>> No active process. Starting default shell: {shell_program}\n")
        env_data = {"type": "system"}
        self.run_command(str(shell_program), shell_args, str(Path.cwd()), "default_shell", env_data)

        QTimer.singleShot(150, self._send_initial_newline)

    def _send_initial_newline(self):
        if self.current_process and self.current_process.state() == QProcess.ProcessState.Running:
            self.current_process.write_input("\n")

    # ----- Execute a command -----
    def run_command(self, program, args, working_dir, command_name, env_data, rustflags=None, refresh_packages=False):
        self._init_attributes()
        self.set_action_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self._refresh_packages_after = refresh_packages
        self._prompt_pending = False

        self._log_terminal(f"\n>>> Running: {program} {' '.join(args)}\n")
        if rustflags:
            self._log_terminal(f">>> Environment RUSTFLAGS: {rustflags}\n")

        self.current_process = EnvProcess(self)
        self.current_process.output_ready.connect(self._on_command_output)
        self.current_process.finished_signal.connect(self._on_command_finished)
        self.current_process.run_command(program, args, working_dir, env_data, rustflags=rustflags)

        self.input_line.setFocus()

    # ----- Input handling with HTML newline fix -----
    def _send_input(self):
        self._init_attributes()
        if self._prompt_pending:
            self._log_terminal("\n[Input ignored – a dialog is waiting for your answer]\n")
            self.input_line.clear()
            return

        text = self.input_line.text().strip()
        if not text:
            return

        self.input_line.add_to_history(text)

        if not self.current_process:
            self._pending_command = text
            self._start_default_shell()
            QTimer.singleShot(250, self._send_pending_command)
            self.input_line.clear()
            return

        display_text = text.replace('\n', '<br>')
        self._log_terminal(f'<span style="color: #23d18b;"><b>$ {display_text}</b></span><br>', is_html=True)
        self._send_to_process(text)
        self.input_line.clear()

    def _send_pending_command(self):
        if self._pending_command and self.current_process:
            display_text = self._pending_command.replace('\n', '<br>')
            self._log_terminal(f'<span style="color: #23d18b;"><b>$ {display_text}</b></span><br>', is_html=True)
            self._send_to_process(self._pending_command)
            self._pending_command = None

    def _send_to_process(self, text):
        if self.current_process and self.current_process.state() == QProcess.ProcessState.Running:
            line_ending = "\r\n" if sys.platform == "win32" else "\n"
            self.current_process.write_input(text + line_ending)
        else:
            self._log_terminal("\n[Error: No process available to receive input]\n")

    # ----- Output handling (full terminal emulation) with ANSI buffering -----
    def _on_command_output(self, data):
        self._init_attributes()
        data = self._ansi_buffer + data
        self._ansi_buffer = ""

        cursor = self.output_text.textCursor()
        parts = re.split(r'(\r\n|\n|\r|\x08|\x1b\[[0-2]?K)', data)

        for part in parts:
            if not part:
                continue

            if part in ('\r\n', '\n'):
                cursor.movePosition(QTextCursor.End)
                cursor.insertHtml("<br>")
            elif part == '\r':
                self._cr_pending = True
            elif part == '\x08':
                cursor.movePosition(QTextCursor.End)
                cursor.deletePreviousChar()
            elif part.startswith('\x1b[') and part.endswith('K'):
                cursor.movePosition(QTextCursor.End)
                if part in ('\x1b[K', '\x1b[0K'):
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                elif part == '\x1b[1K':
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                elif part == '\x1b[2K':
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
            else:
                cursor.movePosition(QTextCursor.End)
                if self._cr_pending:
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                    self._cr_pending = False

                html_data = self._ansi_to_html(part)
                cursor.insertHtml(html_data)

        incomplete_match = re.search(r'\x1B\[[0-9;]*$', data)
        if incomplete_match:
            self._ansi_buffer = incomplete_match.group(0)

        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        regex_pattern = r"([^\n]+(?:\[?y(?:es)?\]?/\[?n(?:o)?\]?(?:/\[?q(?:uit)?\]?)?|\(y(?:es)?/n(?:o)?(?:/q(?:uit)?)?\))[\s\?:]*)$"
        prompt_match = re.search(regex_pattern, data, re.IGNORECASE)
        if prompt_match and not self._prompt_pending:
            question_text = prompt_match.group(1).strip()
            self._prompt_pending = True
            self.input_line.setEnabled(False)
            QTimer.singleShot(50, lambda: self._handle_interactive_prompt(question_text))

    def _handle_interactive_prompt(self, question_text):
        reply = QMessageBox.question(
            self.output_text,
            "Input Required",
            f"The running process requires input:\n\n{question_text}",
            QMessageBox.Yes | QMessageBox.No
        )
        response = "y\n" if reply == QMessageBox.Yes else "n\n"
        self._log_terminal(f'<span style="color: #23d18b;"><b>{response.strip()}</b></span><br>', is_html=True)
        if self.current_process:
            self.current_process.write_input(response)
        self._prompt_pending = False
        self.input_line.setEnabled(True)
        self.input_line.setFocus()

    def _on_command_finished(self, exit_code, exit_status):
        self.set_action_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self._log_terminal("\n>>> Command finished.\n\n")
        self._prompt_pending = False
        self.current_process = None
        if hasattr(self, 'refresh_wheel_list'):
            self.refresh_wheel_list()
        if getattr(self, '_refresh_packages_after', False) and hasattr(self, 'refresh_installed_packages'):
            self.refresh_installed_packages()