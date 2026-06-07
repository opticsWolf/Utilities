# -*- coding: utf-8 -*-
"""
PyCodeRadar launcher.

This is a thin wrapper kept for backwards compatibility with the old
single-file `PyCodeRadar.py` invocation. The real code now lives in the
`pycoderadar/` package — see `pycoderadar/app.py:main`.

Usage:
    python PyCodeRadar.py
    # or, equivalently:
    python -m pycoderadar
"""

from pycoderadar.app import main


if __name__ == "__main__":
    main()
