# -*- coding: utf-8 -*-
"""
Config persistence.

Stores GUI state to a small JSON file in the platform-appropriate user-config
directory (resolved via QStandardPaths). The file is loaded on app start and
written on close, plus opportunistically on certain UI changes.

Schema (forward-compatible: unknown keys are ignored on load, missing keys fall
back to defaults — older configs continue to work after upgrades):

    {
      "version": 1,
      "scan_options": { ... ScanOptions fields ... },
      "preset":       "Standard",
      "format":       "Text",
      "last_folder":  "/path/to/last/project",
      "window": {
        "geometry":      <base64 QByteArray>,    # Qt-native: position + size
        "splitter":      [320, 880]
      }
    }
"""

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QStandardPaths

from .constants import APP_NAME, CONFIG_FILE
from .models import ScanOptions
from .presets import detect_preset


SCHEMA_VERSION = 1


# ── Paths ─────────────────────────────────────────────────────────────────────

def config_dir() -> Path:
    """
    Resolve the per-user config directory.

    QStandardPaths returns something like:
      - Linux:   ~/.config/PyCodeRadar
      - macOS:   ~/Library/Preferences/PyCodeRadar
      - Windows: %APPDATA%\\PyCodeRadar
    """
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:
        # Fallback if QApplication hasn't initialised the org/app names yet.
        base = str(Path.home() / ".config" / APP_NAME)
    return Path(base)


def config_path() -> Path:
    return config_dir() / CONFIG_FILE


# ── Load / save ───────────────────────────────────────────────────────────────

def load_config() -> Dict[str, Any]:
    """
    Read the config file. Returns an empty dict on any error so the caller
    can fall back to defaults without special-casing.
    """
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[PyCodeRadar] Could not read config ({path}): {e}")
        return {}


def save_config(data: Dict[str, Any]) -> bool:
    """Atomically write the config file. Returns True on success."""
    path = path_tmp = None
    try:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path     = config_path()
        path_tmp = path.with_suffix(path.suffix + ".tmp")
        payload  = {"version": SCHEMA_VERSION, **data}
        path_tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        path_tmp.replace(path)   # atomic on POSIX & Windows (same volume)
        return True
    except OSError as e:
        print(f"[PyCodeRadar] Could not write config ({path}): {e}")
        if path_tmp and path_tmp.exists():
            try: path_tmp.unlink()
            except OSError: pass
        return False


# ── ScanOptions <-> dict ──────────────────────────────────────────────────────

def options_to_dict(opts: ScanOptions) -> Dict[str, Any]:
    return asdict(opts)


def options_from_dict(data: Dict[str, Any]) -> ScanOptions:
    """
    Build a ScanOptions from a (possibly partial) dict.

    Missing keys fall back to dataclass defaults; unknown keys are silently
    ignored. Type-coerce lightly so old configs with stringified booleans
    still load cleanly.
    """
    opts = ScanOptions()
    valid_names = {f.name: f.type for f in fields(opts)}
    for key, value in (data or {}).items():
        if key not in valid_names:
            continue
        try:
            current = getattr(opts, key)
            if isinstance(current, bool) and not isinstance(value, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(value, int):
                value = int(value)
            elif isinstance(current, str) and not isinstance(value, str):
                value = str(value)
        except (TypeError, ValueError):
            continue
        setattr(opts, key, value)
    return opts


# ── High-level helpers used by MainWindow ─────────────────────────────────────

def load_scan_options() -> tuple:
    """
    Convenience loader.

    Returns (opts, preset_name, full_config_dict). The full dict is returned
    so the caller can also pull window geometry, last-folder, etc.
    """
    cfg     = load_config()
    raw     = cfg.get("scan_options", {}) or {}
    opts    = options_from_dict(raw)
    # Preset stored explicitly wins; otherwise reverse-detect from options.
    preset  = cfg.get("preset") or detect_preset(opts)
    return opts, preset, cfg


def build_config_payload(
    opts: ScanOptions,
    *,
    preset: Optional[str] = None,
    fmt: Optional[str] = None,
    last_folder: Optional[str] = None,
    geometry_b64: Optional[str] = None,
    splitter_sizes: Optional[list] = None,
) -> Dict[str, Any]:
    """Assemble the dict that save_config() will JSON-encode."""
    payload: Dict[str, Any] = {
        "scan_options": options_to_dict(opts),
    }
    if preset is not None:
        payload["preset"] = preset
    if fmt is not None:
        payload["format"] = fmt
    if last_folder is not None:
        payload["last_folder"] = last_folder
    window: Dict[str, Any] = {}
    if geometry_b64 is not None:
        window["geometry"] = geometry_b64
    if splitter_sizes is not None:
        window["splitter"] = list(splitter_sizes)
    if window:
        payload["window"] = window
    return payload
