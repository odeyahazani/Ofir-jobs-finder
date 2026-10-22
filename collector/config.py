"""Load simple KEY=value local config without executing shell commands or substitutions."""
import os
import re
import shlex
from .store import ROOT


def load_local_config():
    file = ROOT / ".env.local"
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, raw = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        try:
            parts = shlex.split(raw, comments=True)
        except ValueError:
            raise ValueError(f"Invalid quoting for configuration name {key}") from None
        if len(parts) > 1:
            raise ValueError(f"Quote the value for configuration name {key}")
        os.environ.setdefault(key, parts[0] if parts else "")
