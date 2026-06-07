import re
import sys
import os
import subprocess
import tempfile
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QProgressBar,
    QMessageBox,
    QSplitter,
    QBoxLayout,
)
from PySide6.QtGui import QFont, QTextCursor, QKeyEvent
from PySide6.QtCore import Qt, QTimer, QProcess, Signal
from process_wrapper import EnvProcess


class HistoryTextEdit(QTextEdit):
    """Custom QTextEdit for terminal input with history and Enter-to-send support."""

    returnPressed = Signal()
    historyChanged = Signal()

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
        self.historyChanged.emit()

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
    """Manages the central terminal widget, ANSI parsing, and process execution logic."""

    def __init__(self):
        self._init_attributes()
        self.settings = None
        self.splitter = None

    def _init_attributes(self):
        if not hasattr(self, "_prompt_pending"):
            self._prompt_pending = False
        if not hasattr(self, "_cr_pending"):
            self._cr_pending = False
        if not hasattr(self, "_ansi_bold"):
            self._ansi_bold = False
        if not hasattr(self, "_ansi_color"):
            self._ansi_color = None
        if not hasattr(self, "current_process"):
            self.current_process = None
        if not hasattr(self, "_refresh_packages_after"):
            self._refresh_packages_after = False
        if not hasattr(self, "_pending_command"):
            self._pending_command = None
        if not hasattr(self, "_ansi_buffer"):
            self._ansi_buffer = ""
        if not hasattr(self, "_interactive_session"):
            self._interactive_session = False

    def _build_env_command(self, program, args, env_data=None):
        """Preprocesses executable arguments to guarantee line buffering, unbuffered execution, and progress logging corrections."""
        args = list(args)

        # 1. Conda run buffering: add --live-stream if we run via conda run
        if program == "conda" and len(args) > 0 and args[0] == "run":
            if "--live-stream" not in args:
                args.insert(1, "--live-stream")

        # 2. Python buffering & Pip normalization:
        # Change pip invocations from pip install ... to python -u -m pip install ...
        # This ensures PYTHONUNBUFFERED=1 takes full effect.
        is_pip_cmd = (program == "pip" or (len(args) > 0 and args[0] == "pip"))
        if is_pip_cmd:
            if program == "pip":
                program = "python"
                if sys.platform == "win32":
                    args = ["-u", "-m", "pip"] + args
                else:
                    args = ["-m", "pip"] + args
            elif len(args) > 0 and args[0] == "pip":
                if program in ("python", "python3") or program.endswith("python") or program.endswith("python.exe"):
                    if sys.platform == "win32" and "-u" not in args:
                        args.insert(0, "-u")

        # Automatic stripping of pip and uv progress arguments has been removed
        # to allow native progress animations to render properly on screen.

        return program, args, env_data

    def _load_terminal_settings(self):
        if not self.settings:
            return
        if self.splitter:
            sizes = self.settings.get("splitter_sizes", [])
            if len(sizes) == 2:
                self.splitter.setSizes(sizes)
        history = self.settings.get("command_history", [])
        if history and hasattr(self, "input_line"):
            self.input_line.set_history(history)

    def _save_terminal_settings(self):
        if not self.settings:
            return
        if self.splitter:
            self.settings.set("splitter_sizes", self.splitter.sizes())
        if hasattr(self, "input_line"):
            self.settings.set("command_history", self.input_line.history[-100:])

    def _build_terminal_ui(self):
        self._init_attributes()
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        splitter = QSplitter(Qt.Vertical)
        self.splitter = splitter

        output_widget = QWidget()
        output_widget.setMinimumHeight(150)
        output_layout = QVBoxLayout(output_widget)
        output_layout.setContentsMargins(0, 0, 0, 0)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Monospace", 10))

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        # Idle timer: in an interactive shell the bar reflects output activity
        # rather than the (perpetual) process lifetime, so it settles when the
        # shell goes quiet at its prompt.
        self._activity_timer = QTimer(self)
        self._activity_timer.setSingleShot(True)
        self._activity_timer.timeout.connect(self._on_activity_idle)

        output_layout.addWidget(QLabel("Terminal Output"))
        output_layout.addWidget(self.output_text)
        output_layout.addWidget(self.progress_bar)

        splitter.addWidget(output_widget)

        self.input_line = HistoryTextEdit()
        self.input_line.setPlaceholderText(
            "Type a command and press Enter (Shift+Enter for newline)..."
        )
        self.input_line.returnPressed.connect(self._send_input)
        self.input_line.setEnabled(True)

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

        input_widget = ResponsiveInputWidget(
            self.input_line, self.send_btn, self.clear_btn
        )
        input_widget.setMinimumHeight(line_height + 15)
        input_widget.setMaximumHeight(max_height)

        splitter.addWidget(input_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        main_layout.addWidget(splitter)
        return central_widget

    def _ansi_to_html(self, text):
        self._init_attributes()
        text = re.sub(r"\x1B\].*?(?:\x07|\x1B\\)", "", text)
        
        # Matches any non-color CSI sequence safely ending in a letter while excluding lowercase 'm'
        text = re.sub(r"\x1B\[[0-9;?]*[a-ln-zA-Z]", "", text)
        
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(" ", "&nbsp;")

        colors = {
            "30": "#000000",
            "31": "#cd3131",
            "32": "#0dbc79",
            "33": "#e5e510",
            "34": "#2472c8",
            "35": "#bc3fbc",
            "36": "#11a8cd",
            "37": "#e5e5e5",
            "90": "#666666",
            "91": "#f14c4c",
            "92": "#23d18b",
            "93": "#f5f543",
            "94": "#3b8eea",
            "95": "#d670d6",
            "96": "#29b8db",
            "97": "#e5e5e5",
        }

        html = ""
        if self._ansi_bold:
            html += "<b>"
        if self._ansi_color:
            html += f'<span style="color: {self._ansi_color};">'

        ansi_re = re.compile(r"\x1B\[([0-9;]*)m")
        last_end = 0

        for match in ansi_re.finditer(text):
            html += text[last_end : match.start()]
            codes = match.group(1).split(";")
            if not codes or codes == [""]:
                codes = ["0"]

            for code in codes:
                if code == "0":
                    if self._ansi_color:
                        html += "</span>"
                        self._ansi_color = None
                    if self._ansi_bold:
                        html += "</b>"
                        self._ansi_bold = False
                elif code == "1":
                    if not self._ansi_bold:
                        html += "<b>"
                        self._ansi_bold = True
                elif code in colors:
                    if self._ansi_color:
                        html += "</span>"
                    html += f'<span style="color: {colors[code]};">'
                    self._ansi_color = colors[code]

            last_end = match.end()

        html += text[last_end:]
        if self._ansi_color:
            html += "</span>"
        if self._ansi_bold:
            html += "</b>"

        return html

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
        self.output_text.repaint()

    def _start_default_shell(self):
        if sys.platform == "win32":
            shell_program = "cmd.exe"
            shell_args = ["/K"]
        else:
            shell_program = os.environ.get("SHELL", "/bin/bash")
            shell_args = ["-i"]

        self._log_terminal(
            f"\n>>> No active process. Starting default shell: {shell_program}\n"
        )
        env_data = {"type": "system"}
        self.run_command(
            str(shell_program),
            shell_args,
            str(Path.cwd()),
            "default_shell",
            env_data,
            interactive=True,
        )

        QTimer.singleShot(150, self._send_initial_newline)

    def _send_initial_newline(self):
        if (
            self.current_process
            and self.current_process.state() == QProcess.ProcessState.Running
        ):
            self.current_process.write_input("\n")

    def _get_vcvars_path(self):
        """Dynamically locates vcvars64.bat using vswhere.exe on Windows as a fallback."""
        if sys.platform != "win32":
            return None

        vswhere_path = os.path.expandvars(
            r"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
        )
        if not os.path.exists(vswhere_path):
            return None

        try:
            # Query vswhere for the latest installation containing the C++ toolchain
            result = subprocess.run(
                [
                    vswhere_path,
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-property",
                    "installationPath",
                ],
                capture_output=True,
                text=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            install_path = result.stdout.strip()
            if install_path:
                vcvars = os.path.join(
                    install_path, "VC", "Auxiliary", "Build", "vcvars64.bat"
                )
                if os.path.exists(vcvars):
                    return vcvars
        except Exception as e:
            print(f"Failed to locate MSVC via vswhere: {e}")

        return None

    def _wrap_in_msvc_batch(self, vcvars_path, inner_cmd):
        """Write a temp .bat that initialises MSVC then runs inner_cmd.

        Returns (program, args) ready for the process, i.e. ('cmd.exe',
        ['/D', '/C', <batch_path>]). The batch path is a single argument, so it
        survives QProcess quoting intact even when it contains spaces.
        The '/D' flag disables command execution from AutoRun registry settings,
        preventing I/O flow pipeline delays.
        """
        fd, bat_path = tempfile.mkstemp(prefix="msvc_run_", suffix=".bat")
        with os.fdopen(fd, "w") as f:
            # \r\n line endings for cmd.exe; abort if vcvars itself fails so we
            # don't run the build in a half-initialised environment.
            f.write("@echo off\r\n")
            # Match the UTF-8 decoding done when reading the process output, so
            # non-ASCII build/compiler messages render correctly.
            f.write("chcp 65001 >nul\r\n")
            f.write(f'call "{vcvars_path}"\r\n')
            f.write("if errorlevel 1 exit /b 1\r\n")
            f.write(f"{inner_cmd}\r\n")
        # Remember it so it can be removed once the command finishes.
        self._msvc_temp_bat = bat_path
        return "cmd.exe", ["/D", "/C", bat_path]

    def _cleanup_msvc_temp_bat(self):
        """Delete the temporary MSVC batch file, if one was created."""
        bat_path = getattr(self, "_msvc_temp_bat", None)
        if bat_path:
            try:
                os.remove(bat_path)
            except OSError:
                pass
            self._msvc_temp_bat = None

    def _terminate_current_process(self):
        """Stop and detach any currently running process.

        Used when a new command is launched while something is still running
        (typically an idle interactive shell the user is abandoning). The old
        process is detached from our handlers first so its dying output/exit
        signals don't disturb the new command, then killed.
        """
        proc = self.current_process
        if proc is None:
            return

        # Detach our slots so the kill below doesn't trigger _on_command_output
        # / _on_command_finished for the process we're discarding.
        for signal, slot in (
            (proc.output_ready, self._on_command_output),
            (proc.finished_signal, self._on_command_finished),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

        if proc.state() != QProcess.ProcessState.NotRunning:
            proc.kill()
            proc.waitForFinished(2000)

        # Tidy up anything tied to that run, then release it.
        self._cleanup_msvc_temp_bat()
        proc.deleteLater()
        self.current_process = None
        self._activity_timer.stop()
        self._interactive_session = False

    def run_command(
        self,
        program,
        args,
        working_dir,
        command_name,
        env_data,
        rustflags=None,
        refresh_packages=False,
        require_msvc=False,
        extra_env=None,
        interactive=False,
    ):
        self._init_attributes()
        
        # Intercept and correct commands to guarantee unbuffered Python and line-based logging
        program, args, env_data = self._build_env_command(program, args, env_data)

        # Close anything already running (e.g. an idle interactive shell) before
        # starting this command, so the old process can't bleed output into the
        # new one or fire its finished handler over the top of it.
        self._terminate_current_process()

        # Button policy: disable the managed-task buttons while a managed task
        # runs; for an interactive shell leave them enabled so the user can
        # launch a build -- which supersedes (and closes) the shell.
        self.set_action_buttons_enabled(interactive)

        # Progress-bar policy:
        #   * Managed task (build/install/audit): the process lifetime IS the
        #     task, so show a steady busy indicator for its whole duration even
        #     through quiet download/compile stretches.
        #   * Interactive shell: the process lives indefinitely and is idle at
        #     its prompt, so don't pin a perpetual spinner -- the bar is driven
        #     by output activity instead (see _on_command_output).
        self._interactive_session = interactive
        self._activity_timer.stop()
        if interactive:
            self.progress_bar.setVisible(False)
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setVisible(True)

        self._refresh_packages_after = refresh_packages
        self._prompt_pending = False

        self._log_terminal(f"\n>>> Running: {program} {' '.join(args)}\n")
        if rustflags:
            self._log_terminal(f">>> Environment RUSTFLAGS: {rustflags}\n")

        # --- MSVC Wrapper Logic ---
        if require_msvc and sys.platform == "win32":
            vcvars_path = ""
            
            # 1. Attempt to load the path set by the user in the UI (CUDA Tab)
            if self.settings:
                vcvars_path = self.settings.get("vcvars_path", "").strip()
                
            # 2. If UI path is empty or invalid, fallback to the background auto-detect
            if not vcvars_path or not os.path.exists(vcvars_path):
                vcvars_path = self._get_vcvars_path()

            # 3. Apply the MSVC wrapper if a valid path was found
            if vcvars_path and os.path.exists(vcvars_path):
                # Normalise: vcvars / cmd dislike forward slashes (a path saved
                # from the file dialog may contain them).
                vcvars_path = os.path.normpath(vcvars_path)
                self._log_terminal(
                    f">>> Initializing MSVC Environment via: {vcvars_path}\n"
                )
                # Write a small batch file and run it via `cmd /D /C <file>` instead
                # of passing a hand-quoted command string. Passing a complex
                # quoted string as a single QProcess argument causes Qt to quote
                # it again (turning "C:\..." into "\"C:\...\""), which cmd.exe
                # then fails to parse -> "command not found". A temp .bat is a
                # single clean argument, so no double-quoting can occur.
                arg_str = " ".join(f'"{a}"' if " " in a else a for a in args)
                inner_cmd = f'"{program}" {arg_str}'.rstrip()
                program, args = self._wrap_in_msvc_batch(vcvars_path, inner_cmd)
            else:
                self._log_terminal(
                    ">>> WARNING: require_msvc was True, but vcvars64.bat could not be found. Please set the correct path in the CUDA tab.\n"
                )

        self.current_process = EnvProcess(self)
        self.current_process.output_ready.connect(self._on_command_output)
        self.current_process.finished_signal.connect(self._on_command_finished)
        self.current_process.run_command(
            program,
            args,
            working_dir,
            env_data,
            rustflags=rustflags,
            extra_env=extra_env,
        )

        self.input_line.setFocus()

    def _send_input(self):
        self._init_attributes()
        if self._prompt_pending:
            self._log_terminal(
                "\n[Input ignored – a dialog is waiting for your answer]\n"
            )
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

        display_text = text.replace("\n", "<br>")
        self._log_terminal(
            f'<span style="color: #23d18b;"><b>$ {display_text}</b></span><br>',
            is_html=True,
        )
        self._send_to_process(text)
        self.input_line.clear()

    def _send_pending_command(self):
        if self._pending_command and self.current_process:
            display_text = self._pending_command.replace("\n", "<br>")
            self._log_terminal(
                f'<span style="color: #23d18b;"><b>$ {display_text}</b></span><br>',
                is_html=True,
            )
            self._send_to_process(self._pending_command)
            self._pending_command = None

    def _send_to_process(self, text):
        if (
            self.current_process
            and self.current_process.state() == QProcess.ProcessState.Running
        ):
            line_ending = "\r\n" if sys.platform == "win32" else "\n"
            self.current_process.write_input(text + line_ending)
        else:
            self._log_terminal("\n[Error: No process available to receive input]\n")

    def _pulse_activity_bar(self):
        """Show the busy bar while an interactive shell is producing output.

        Each output chunk restarts a short idle timer; when output stops (e.g.
        the shell is back at its prompt) the bar is hidden by _on_activity_idle.
        """
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self._activity_timer.start(400)  # hide ~0.6s after the last output

    def _on_activity_idle(self):
        # Only the interactive shell uses activity-based visibility; a managed
        # task keeps its steady bar until it actually finishes.
        if getattr(self, "_interactive_session", False):
            self.progress_bar.setVisible(False)

    def _on_command_output(self, data):
        self._init_attributes()
        if self._interactive_session:
            self._pulse_activity_bar()
        data = self._ansi_buffer + data
        self._ansi_buffer = ""

        cursor = self.output_text.textCursor()
        parts = re.split(r"(\r\n|\n|\r|\x08|\x1b\[[0-2]?K)", data)

        for part in parts:
            if not part:
                continue

            if part in ("\r\n", "\n"):
                cursor.movePosition(QTextCursor.End)
                cursor.insertHtml("<br>")
            elif part == "\r":
                self._cr_pending = True
            elif part == "\x08":
                cursor.movePosition(QTextCursor.End)
                cursor.deletePreviousChar()
            elif part.startswith("\x1b[") and part.endswith("K"):
                cursor.movePosition(QTextCursor.End)
                if part in ("\x1b[K", "\x1b[0K"):
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                elif part == "\x1b[1K":
                    cursor.movePosition(
                        QTextCursor.StartOfBlock, QTextCursor.KeepAnchor
                    )
                elif part == "\x1b[2K":
                    cursor.movePosition(QTextCursor.StartOfBlock)
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
            else:
                cursor.movePosition(QTextCursor.End)
                if self._cr_pending:
                    cursor.movePosition(
                        QTextCursor.StartOfBlock, QTextCursor.KeepAnchor
                    )
                    cursor.removeSelectedText()
                    self._cr_pending = False

                html_data = self._ansi_to_html(part)
                cursor.insertHtml(html_data)

        incomplete_match = re.search(r"\x1B\[[0-9;]*$", data)
        if incomplete_match:
            self._ansi_buffer = incomplete_match.group(0)

        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # Force PySide to push updates instantly to the desktop display window
        self.output_text.repaint()

        regex_pattern = r"([^\n]+(?:\[?y(?:es)?\]?/\[?n(?:o)?\]?(?:/\[?q(?:uit)?\]?)?|\(y(?:es)?/n(?:o)?(?:/q(?:uit)?)?\))[\s\?:]*)$"
        prompt_match = re.search(regex_pattern, data, re.IGNORECASE)
        if prompt_match and not self._prompt_pending:
            question_text = prompt_match.group(1).strip()
            self._prompt_pending = True
            self.input_line.setEnabled(False)
            QTimer.singleShot(
                50, lambda: self._handle_interactive_prompt(question_text)
            )

    def _handle_interactive_prompt(self, question_text):
        reply = QMessageBox.question(
            self.output_text,
            "Input Required",
            f"The running process requires input:\n\n{question_text}",
            QMessageBox.Yes | QMessageBox.No,
        )
        response = "y\n" if reply == QMessageBox.Yes else "n\n"
        self._log_terminal(
            f'<span style="color: #23d18b;"><b>{response.strip()}</b></span><br>',
            is_html=True,
        )
        if self.current_process:
            self.current_process.write_input(response)
        self._prompt_pending = False
        self.input_line.setEnabled(True)
        self.input_line.setFocus()

    def _on_command_finished(self, exit_code, exit_status):
        self.set_action_buttons_enabled(True)
        self._activity_timer.stop()
        self._interactive_session = False
        self.progress_bar.setVisible(False)
        self._log_terminal("\n>>> Command finished.\n\n")
        self._prompt_pending = False
        self.current_process = None
        self._cleanup_msvc_temp_bat()
        if hasattr(self, "refresh_wheel_list"):
            self.refresh_wheel_list()
        if getattr(self, "_refresh_packages_after", False) and hasattr(
            self, "refresh_installed_packages"
        ):
            self.refresh_installed_packages()