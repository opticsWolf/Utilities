"""
Background scanner thread for import detection and version resolution.
"""

import os
import sys
import re
import json
import urllib.request
import importlib.metadata
import subprocess
from PySide6.QtCore import QThread, Signal


class DependencyScannerThread(QThread):
    progress = Signal(str)
    finished = Signal(dict)   # {normalized_pkg_name: {'pypi_name': str, 'import_name': str, 'installed': str|None, 'latest': str|None, 'dev': bool}}

    def __init__(self, project_root, python_exe, detect_dev):
        super().__init__()
        self.project_root = project_root
        self.python_exe = python_exe
        self.detect_dev = detect_dev

    def run(self):
        self.progress.emit("Scanning Python files for imports...")
        prod_imports, dev_imports = self._extract_imports_with_dev()
        if not prod_imports and not dev_imports:
            self.finished.emit({})
            return

        all_imports = prod_imports.union(dev_imports)

        self.progress.emit("Filtering standard library modules...")
        third_party = self._filter_stdlib(all_imports)

        self.progress.emit("Mapping imports to PyPI package names...")
        pkg_map = self._map_imports_to_pypi(third_party)

        self.progress.emit("Checking installed & latest versions...")
        result = self._resolve_versions(pkg_map, prod_imports, dev_imports)

        self.finished.emit(result)

    # ------------------------------------------------------------------
    # AST extraction with dev/test detection
    # ------------------------------------------------------------------
    def _extract_imports_with_dev(self):
        import ast
        from pathlib import Path
        prod_imports = set()
        dev_imports = set()
        root_path = Path(self.project_root)
        for py_file in root_path.rglob("*.py"):
            # Skip virtual environment and cache folders
            if '.venv' in py_file.parts or 'env' in py_file.parts or '__pycache__' in py_file.parts:
                continue

            # Determine if this file is considered a test file
            is_test = False
            if self.detect_dev:
                parts = py_file.parts
                # Folder named 'tests' or 'test' (case‑insensitive)
                if any(part.lower() in ('tests', 'test') for part in parts):
                    is_test = True
                # Filename patterns
                if py_file.name == 'conftest.py' or py_file.name.endswith('_test.py'):
                    is_test = True

            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=str(py_file))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split('.')[0]
                            if is_test:
                                dev_imports.add(top)
                            else:
                                prod_imports.add(top)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            top = node.module.split('.')[0]
                            if is_test:
                                dev_imports.add(top)
                            else:
                                prod_imports.add(top)
            except (SyntaxError, UnicodeDecodeError):
                continue
        return prod_imports, dev_imports

    # ------------------------------------------------------------------
    # Filter out standard library modules
    # ------------------------------------------------------------------
    def _filter_stdlib(self, imports):
        # Python 3.10+ has sys.stdlib_module_names
        try:
            stdlib = sys.stdlib_module_names
        except AttributeError:
            # Fallback for older Python: a small static list (approx)
            stdlib = {
                'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio',
                'asyncore', 'atexit', 'audioop', 'base64', 'bdb', 'binascii',
                'binhex', 'bisect', 'builtins', 'bz2', 'cProfile', 'calendar',
                'cgi', 'cgitb', 'chunk', 'cmath', 'cmd', 'code', 'codecs',
                'codeop', 'collections', 'colorsys', 'compileall', 'concurrent',
                'configparser', 'contextlib', 'contextvars', 'copy', 'copyreg',
                'crypt', 'csv', 'ctypes', 'curses', 'dataclasses', 'datetime',
                'dbm', 'decimal', 'difflib', 'dis', 'distutils', 'doctest',
                'email', 'encodings', 'enum', 'errno', 'faulthandler', 'fcntl',
                'filecmp', 'fileinput', 'fnmatch', 'fractions', 'ftplib',
                'functools', 'gc', 'getopt', 'getpass', 'gettext', 'glob',
                'graphlib', 'gzip', 'hashlib', 'heapq', 'hmac', 'html',
                'http', 'idlelib', 'imaplib', 'imghdr', 'imp', 'importlib',
                'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword',
                'lib2to3', 'linecache', 'locale', 'logging', 'lzma', 'mailbox',
                'mailcap', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder',
                'msilib', 'msvcrt', 'multiprocessing', 'netrc', 'nis', 'nntplib',
                'nt', 'ntpath', 'nturl2path', 'numbers', 'opcode', 'operator',
                'optparse', 'os', 'ossaudiodev', 'pathlib', 'pdb', 'pickle',
                'pickletools', 'pipes', 'pkgutil', 'platform', 'plistlib',
                'poplib', 'posix', 'posixpath', 'pprint', 'profile', 'pstats',
                'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc', 'queue',
                'quopri', 'random', 're', 'readline', 'reprlib', 'resource',
                'rlcompleter', 'runpy', 'sched', 'secrets', 'select',
                'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'smtpd',
                'smtplib', 'sndhdr', 'socket', 'socketserver', 'spwd',
                'sqlite3', 'ssl', 'stat', 'statistics', 'string', 'stringprep',
                'struct', 'subprocess', 'sunau', 'symbol', 'symtable',
                'sys', 'sysconfig', 'syslog', 'tabnanny', 'tarfile', 'telnetlib',
                'tempfile', 'termios', 'test', 'textwrap', 'threading',
                'time', 'timeit', 'token', 'tokenize', 'trace',
                'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo',
                'types', 'typing', 'unicodedata', 'unittest', 'urllib',
                'uu', 'uuid', 'venv', 'warnings', 'wave', 'weakref',
                'webbrowser', 'winreg', 'winsound', 'wsgiref', 'xdrlib',
                'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib'
            }
        # Keep only modules that are not in the standard library
        return {mod for mod in imports if mod not in stdlib and not mod.startswith('_')}

    # ------------------------------------------------------------------
    # Map import names to PyPI distribution names
    # ------------------------------------------------------------------
    def _map_imports_to_pypi(self, imports):
        # Use importlib.metadata.packages_distributions() (Python >=3.10)
        try:
            dist_map = importlib.metadata.packages_distributions()
        except (ImportError, AttributeError):
            dist_map = {}

        # Manual overrides for common mismatches
        overrides = {
            'bs4': 'beautifulsoup4',
            'PIL': 'pillow',
            'cv2': 'opencv-python',
            'sklearn': 'scikit-learn',
            'yaml': 'pyyaml',
            'dateutil': 'python-dateutil',
            'gi': 'pygobject',
            'zmq': 'pyzmq',
            'MySQLdb': 'mysqlclient',
            'psycopg2': 'psycopg2-binary',
            'IPython': 'ipython',
            'dotenv': 'python-dotenv',
        }

        mapping = {}
        for mod in imports:
            if mod in overrides:
                mapping[mod] = overrides[mod]
                continue
            found = dist_map.get(mod, [])
            if found:
                mapping[mod] = found[0]
                continue
            # Fallback: lower case, replace underscores with hyphens
            fallback = mod.lower().replace('_', '-')
            mapping[mod] = fallback
        # Return dict {normalized_package_name: original_import_name}
        normalized = {pkg_name: mod for mod, pkg_name in mapping.items()}
        return normalized

    # ------------------------------------------------------------------
    # Resolve installed and latest versions
    # ------------------------------------------------------------------
    def _resolve_versions(self, pkg_map, prod_imports, dev_imports):
        result = {}
        total = len(pkg_map)
        for idx, (pkg_name, import_name) in enumerate(pkg_map.items()):
            self.progress.emit(f"Checking {import_name} ({idx+1}/{total})...")
            installed = self._get_installed_version(pkg_name)
            latest = self._get_latest_version(pkg_name)
            # Dev detection: appears in dev_imports but NOT in prod_imports
            dev = (import_name in dev_imports) and (import_name not in prod_imports)
            result[pkg_name] = {
                'pypi_name': pkg_name,
                'import_name': import_name,
                'installed': installed,
                'latest': latest,
                'dev': dev,
            }
        return result

    def _get_installed_version(self, pkg_name):
        """Run `python -c "import importlib.metadata; print(version(...))"` in the project env."""
        try:
            cmd = [self.python_exe, "-c", f"import importlib.metadata; print(importlib.metadata.version('{pkg_name}'))"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=self.project_root)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _get_latest_version(self, pkg_name):
        """Query PyPI JSON API."""
        url = f"https://pypi.org/pypi/{pkg_name}/json"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                return data['info']['version']
        except Exception:
            return None