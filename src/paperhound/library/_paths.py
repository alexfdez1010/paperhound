"""Library filesystem location resolution."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DIR = Path.home() / ".paperhound" / "library"


def library_dir() -> Path:
    """Return the library root, honouring ``PAPERHOUND_LIBRARY_DIR``."""
    env = os.environ.get("PAPERHOUND_LIBRARY_DIR")
    return Path(env) if env else _DEFAULT_DIR
