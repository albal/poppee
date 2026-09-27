"""Where Poppee keeps its files.

Everything can be relocated with environment variables, which is handy for
portable installs and for tests:

* ``POPPEE_CONFIG_DIR`` - config.toml and client_secret.json
* ``POPPEE_DATA_DIR``   - OAuth tokens, state.json and logs
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

_APP_DIR_NAME = "poppee"


def config_dir() -> Path:
    env = os.environ.get("POPPEE_CONFIG_DIR")
    return Path(env) if env else platformdirs.user_config_path(_APP_DIR_NAME, appauthor=False)


def data_dir() -> Path:
    env = os.environ.get("POPPEE_DATA_DIR")
    return Path(env) if env else platformdirs.user_data_path(_APP_DIR_NAME, appauthor=False)


def config_file() -> Path:
    return config_dir() / "config.toml"


def tokens_dir() -> Path:
    return data_dir() / "tokens"


def state_file() -> Path:
    return data_dir() / "state.json"


def lock_file() -> Path:
    return data_dir() / "poppee.lock"


def log_file() -> Path:
    return data_dir() / "logs" / "poppee.log"
