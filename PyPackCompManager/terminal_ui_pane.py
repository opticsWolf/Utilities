import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, 
    QPushButton, QProgressBar, QMessageBox
)
from PySide6.QtGui import QFont, QTextCursor, QColor
from PySide6.QtCore import Qt, QTimer
from process_wrapper import EnvProcess

class TerminalMixin:
    """Manages the central terminal widget, ANSI parsing, and process execution logic."""

    def _build_terminal_ui(self):
        central_widget = QWidget()
        output_layout = QVBoxLayout(central_widget)
        
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Monospace", 10))
        
        clear_btn = QPushButton("🧹 Clear Output")
        self._setup_button(clear_btn, "Clears the terminal output window below.")
        clear_btn.clicked.connect(self.output_text.clear)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        output_layout.addWidget(QLabel("<b>Terminal Output</b>"))
        output_layout.addWidget(self.output_text)
        output_layout.addWidget(clear_btn)
        output_layout.addWidget(self.progress_bar)
        
        return central_widget

    def _ansi_to_html(self, text):
        """Convert ANSI escape codes to HTML (Control chars are now handled by cursor)."""
        if not hasattr(self, '_ansi_bold'):
            self._ansi_bold = False
            self._ansi_color = None
            
        text = re.sub(r'\x1B\].*?(?:\x07|\x1B\\)', '', text)
        text = re.sub(r'\x1B\[[0-9;?]*[a-ln-zA-Z@]', '', text)
            
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        colors = {
            '30': '#000000', '31': '#cd3131', '32': '#0dbc79', '33': '#e5e510',
            '34': '#2472c8', '35': '#bc3fbc', '36': '#11a8cd', '37': '#e5e5e5',
            '90': '#666666', '91': '#f14c4c', '92': '#23d18b', '93': '#f5f543',
            '94': '#3b8eea', '95': '#d670d6', '96': '#29b8db', '97': '#e5e5e5',
        }
        
        html = ""
        
        if self._ansi_bold: html += '<b>'
        if self._ansi_color: html += f'<span style="color: {self._ansi_color};">'
        
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
        
        if self._ansi_color: html += '</span>'
        if self._ansi_bold: html += '</b>'
        
        return html

    def _log_terminal(self, text, is_html=False):
        """Log text to the terminal, preserving distinct blocks."""
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        self._cr_pending = False
        
        if is_html:
            cursor.insertHtml(text)
        else:
            safe_text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_lines = [f"<p style='margin:0;'><b><i>{line}</i></b></p>" for line in safe_text.split('\n')]
            cursor.insertHtml("".join(html_lines))
        
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def run_command(self, program, args, working_dir, command_name, env_data, rustflags=None, refresh_packages=False):
        """Execute a command in the selected environment."""
        self.set_action_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self._refresh_packages_after = refresh_packages

        self._log_terminal(f"\n>>> Running: {program} {' '.join(args)}\n")
        if rustflags:
            self._log_terminal(f">>> Environment RUSTFLAGS: {rustflags}\n")
        
        self.current_process = EnvProcess(self)
        self.current_process.output_ready.connect(self._on_command_output)
        self.current_process.finished_signal.connect(self._on_command_finished)
        self.current_process.run_command(program, args, working_dir, env_data, rustflags=rustflags)

    def _on_command_output(self, data):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        if not hasattr(self, '_cr_pending'):
            self._cr_pending = False
        
        parts = re.split(r'(\r\n|\r|\n|\x08|\x1b\[[0-2]?K)', data)
        
        for part in parts:
            if not part:
                continue
                
            if part in ('\r\n', '\n'):
                if self._cr_pending:
                    self._cr_pending = False
                cursor.insertText('\n')
                
            elif part == '\r':
                self._cr_pending = True
                
            elif part == '\x08':
                if self._cr_pending:
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                    self._cr_pending = False
                cursor.deletePreviousChar()
                
            elif part.startswith('\x1b[') and part.endswith('K'):
                if part in ('\x1b[K', '\x1b[0K'):
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                elif part == '\x1b[1K':
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                elif part == '\x1b[2K':
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                self._cr_pending = False
                
            else:
                if self._cr_pending:
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                    self._cr_pending = False
                
                html_data = self._ansi_to_html(part)
                cursor.insertHtml(html_data)
        
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # --- UPDATED: PROMPT DETECTION ---
        # Matches formats like: [y/N], (y/n), [Yes]/No, yes/[no], Y/n/q
        # re.IGNORECASE handles capitalized vs lowercase automatically
        regex_pattern = r"([^\n]+(?:\[?y(?:es)?\]?/\[?n(?:o)?\]?(?:/\[?q(?:uit)?\]?)?|\(y(?:es)?/n(?:o)?(?:/q(?:uit)?)?\))[\s\?:]*)$"
        
        prompt_match = re.search(regex_pattern, data, re.IGNORECASE)
        if prompt_match:
            question_text = prompt_match.group(1).strip()
            QTimer.singleShot(50, lambda: self._handle_interactive_prompt(question_text))

    def _handle_interactive_prompt(self, question_text):
        """Displays a dialog for process confirmation and sends the answer back."""
        # Using self.output_text as the parent guarantees it attaches to a valid QWidget
        reply = QMessageBox.question(
            self.output_text,  
            "Input Required",
            f"The running process requires input:\n\n{question_text}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        response = "y\n" if reply == QMessageBox.Yes else "n\n"
        
        # Visually log the choice in the terminal so the user has a history of what happened
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(f'<span style="color: #23d18b;"><b>{response}</b></span>')
        
        # Send back to the running process
        if self.current_process and hasattr(self.current_process, 'write_input'):
            self.current_process.write_input(response)
        else:
            self._log_terminal("\n[Error: EnvProcess lacks a 'write_input' method to send data to stdin]\n")

    def _on_command_finished(self, exit_code, exit_status):
        self.set_action_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self._log_terminal("\n>>> Command finished.\n\n")
        
        if hasattr(self, 'refresh_wheel_list'):
            self.refresh_wheel_list()
        
        if getattr(self, '_refresh_packages_after', False) and hasattr(self, 'refresh_installed_packages'):
            self.refresh_installed_packages()
        
        self.current_process = None