"""Single source of truth for the application's name and version.

User-facing strings must read APP_NAME rather than hardcode the name
(SPEC.md header: renaming is a find-replace plus pyproject.toml).
"""

APP_NAME = "dryfire"
CONFIG_DIR = f".{APP_NAME}"
__version__ = "0.4.0"
