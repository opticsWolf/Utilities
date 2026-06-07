import os
import codecs
from PySide6.QtCore import QProcess, QProcessEnvironment, Signal


class EnvProcess(QProcess):
    """QProcess wrapper to run environment commands and capture output."""

    output_ready = Signal(str)
    finished_signal = Signal(int, QProcess.ExitStatus)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Use fully scoped enum for PySide6
        self.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Incremental decoder so multibyte UTF-8 characters split across two
        # read chunks are not turned into replacement characters.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._start_failed = False
        self.readyReadStandardOutput.connect(self._on_ready_read)
        self.finished.connect(self._on_finished)
        # If the program can't be launched at all, finished() is never emitted.
        # Recover explicitly so callers don't hang with disabled UI.
        self.errorOccurred.connect(self._on_error_occurred)

    def _on_ready_read(self):
        # Loop to consume all currently available bytes in the system pipeline buffer
        while self.bytesAvailable() > 0:
            raw = self.readAllStandardOutput().data()
            if not raw:
                break
            text = self._decoder.decode(raw)
            if text:
                self.output_ready.emit(text)

    def _flush_decoder(self):
        """Emit any bytes the incremental decoder was still holding."""
        try:
            tail = self._decoder.decode(b"", final=True)
        except Exception:
            tail = ""
        if tail:
            self.output_ready.emit(tail)

    def _on_error_occurred(self, error):
        # Only FailedToStart leaves us without a finished() signal; every other
        # error (Crashed, Timedout, ...) is still followed by finished().
        if error == QProcess.ProcessError.FailedToStart:
            self._start_failed = True
            self.output_ready.emit(
                f"\n>>> ERROR: Failed to start '{self.program()}'. "
                "Check that it is installed and available on your PATH.\n"
            )
            self._flush_decoder()
            # Synthesize a finished signal so the caller re-enables its UI and
            # runs its cleanup (temp files, progress bar, etc.).
            self.finished_signal.emit(-1, QProcess.ExitStatus.CrashExit)

    def _on_finished(self, exit_code, exit_status):
        if self._start_failed:
            return  # already reported via _on_error_occurred
        self._flush_decoder()
        self.finished_signal.emit(exit_code, exit_status)

    def write_input(self, text: str):
        """Writes string data to the standard input of the running process."""
        if self.state() == QProcess.ProcessState.Running:
            self.write(text.encode("utf-8"))
            # Force the data to be sent immediately to the OS pipe
            self.waitForBytesWritten(50)

    def run_command(
        self,
        program,
        args,
        working_dir=None,
        env_data=None,
        rustflags=None,
        extra_env=None,
    ):
        if working_dir:
            self.setWorkingDirectory(working_dir)

        # Reset per-run state (safe even if this instance is reused).
        self._start_failed = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        qenv = QProcessEnvironment.systemEnvironment()

        # ----- FORCE UNBUFFERED OUTPUT (For Python, Pip, UV and CLI tools) -----
        qenv.insert("PYTHONUNBUFFERED", "1")
        qenv.insert("PYTHONIOENCODING", "utf-8")
        qenv.insert("FORCE_COLOR", "1")        # Force CLI frameworks to unbuffer and retain formatting
        qenv.insert("PIP_NO_INPUT", "1")       # Ensure pip does not buffer waiting for silent inputs
        qenv.insert("UV_NO_PROGRESS", "1")     # Force uv globally to use clean, line-based output
        # --------------------------------------------------------------------

        if env_data:
            env_type = env_data.get("type")
            path_val = env_data.get("path")
            
            # Standard Virtual Environment (venv) handling
            if env_type == "venv" and path_val:
                venv_bin = os.path.join(path_val, "Scripts" if os.name == "nt" else "bin")

                qenv.insert("VIRTUAL_ENV", path_val)
                qenv.insert("PATH", venv_bin + os.pathsep + qenv.value("PATH"))

                # Safely determine the executable name (avoid double .exe on Windows)
                if os.name == "nt":
                    # On Windows, if program doesn't already end with .exe, add it
                    if not program.lower().endswith(".exe"):
                        prog_exe = program + ".exe"
                    else:
                        prog_exe = program
                else:
                    prog_exe = program

                abs_prog = os.path.join(venv_bin, prog_exe)
                if os.path.exists(abs_prog):
                    program = abs_prog
            
            # Conda Environment path injection bypass
            elif env_type == "conda" and path_val:
                qenv.insert("CONDA_PREFIX", path_val)
                
                if os.name == "nt":
                    conda_bins = [
                        path_val,
                        os.path.join(path_val, "Scripts"),
                        os.path.join(path_val, "Library", "bin"),
                        os.path.join(path_val, "Library", "usr", "bin"),
                        os.path.join(path_val, "Library", "mingw-w64", "bin"),
                    ]
                    # Filter existing directories and inject into process PATH
                    conda_paths = [p for p in conda_bins if os.path.exists(p)]
                    if conda_paths:
                        qenv.insert("PATH", os.pathsep.join(conda_paths) + os.pathsep + qenv.value("PATH"))
                    
                    if not program.lower().endswith(".exe"):
                        prog_exe = program + ".exe"
                    else:
                        prog_exe = program
                        
                    # Locate and bind the raw executable within Conda directories
                    for bin_dir in conda_bins:
                        abs_path = os.path.join(bin_dir, prog_exe)
                        if os.path.exists(abs_path):
                            program = abs_path
                            break
                else:
                    conda_bin = os.path.join(path_val, "bin")
                    qenv.insert("PATH", conda_bin + os.pathsep + qenv.value("PATH"))
                    
                    abs_prog = os.path.join(conda_bin, program)
                    if os.path.exists(abs_prog):
                        program = abs_prog

        if rustflags:
            qenv.insert("RUSTFLAGS", rustflags)

        # --- INJECT EXTRA ENVIRONMENT VARIABLES (e.g., CMAKE_ARGS) ---
        if extra_env and isinstance(extra_env, dict):
            for key, val in extra_env.items():
                qenv.insert(key, str(val))

        self.setProcessEnvironment(qenv)
        self.start(program, args)