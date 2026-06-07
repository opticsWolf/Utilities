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
        raw = self.readAllStandardOutput().data()
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

        # ----- FORCE UNBUFFERED OUTPUT (especially for Python) -----
        qenv.insert("PYTHONUNBUFFERED", "1")
        qenv.insert("PYTHONIOENCODING", "utf-8")
        # -----------------------------------------------------------

        if env_data and env_data.get("type") == "venv":
            path_val = env_data["path"]
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

        if rustflags:
            qenv.insert("RUSTFLAGS", rustflags)

        # --- INJECT EXTRA ENVIRONMENT VARIABLES (e.g., CMAKE_ARGS) ---
        if extra_env and isinstance(extra_env, dict):
            for key, val in extra_env.items():
                qenv.insert(key, str(val))

        self.setProcessEnvironment(qenv)
        self.start(program, args)
