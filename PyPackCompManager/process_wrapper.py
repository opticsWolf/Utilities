import os
from PySide6.QtCore import QProcess, QProcessEnvironment, Signal

class EnvProcess(QProcess):
    """QProcess wrapper to run environment commands and capture output."""
    output_ready = Signal(str)
    finished_signal = Signal(int, QProcess.ExitStatus)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProcessChannelMode(QProcess.MergedChannels)
        self.readyReadStandardOutput.connect(self._on_ready_read)
        self.finished.connect(self._on_finished)

    def _on_ready_read(self):
        data = self.readAllStandardOutput().data().decode('utf-8', errors='replace')
        self.output_ready.emit(data)

    def _on_finished(self, exit_code, exit_status):
        self.finished_signal.emit(exit_code, exit_status)

    def write_input(self, text: str):
        """Writes string data to the standard input of the running process."""
        if self.state() == QProcess.ProcessState.Running:
            # QProcess expects byte data; encode the string to UTF-8
            self.write(text.encode('utf-8'))

    def run_command(self, program, args, working_dir=None, env_data=None, rustflags=None):
        if working_dir:
            self.setWorkingDirectory(working_dir)
            
        qenv = QProcessEnvironment.systemEnvironment()

        if env_data and env_data.get("type") == "venv":
            path_val = env_data["path"]
            venv_bin = os.path.join(path_val, "Scripts" if os.name == "nt" else "bin")
            
            qenv.insert("VIRTUAL_ENV", path_val)
            qenv.insert("PATH", venv_bin + os.pathsep + qenv.value("PATH"))
            
            prog_exe = program + (".exe" if os.name == "nt" else "")
            abs_prog = os.path.join(venv_bin, prog_exe)
            if os.path.exists(abs_prog):
                program = abs_prog

        if rustflags:
            qenv.insert("RUSTFLAGS", rustflags)

        self.setProcessEnvironment(qenv)
        self.start(program, args)