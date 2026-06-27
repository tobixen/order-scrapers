"""Optional TOML configuration for per-shop defaults.

Looks at ``~/.config/order-scrapers/config.toml`` (override with
``$ORDER_SCRAPERS_CONFIG``). Every key is optional; command-line flags always
take precedence. Example::

    [aliexpress]
    output = "~/regnskap/aliexpress-history.jsonl"

    [decathlon]
    browser = "firefox"
    country = "bg"
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ENV_VAR = "ORDER_SCRAPERS_CONFIG"


def config_path() -> Path:
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "order-scrapers" / "config.toml"


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def shop_config(shop: str, path: Path | None = None) -> dict:
    """Return the ``[<shop>]`` table from the config (empty dict if absent)."""
    section = load_config(path).get(shop, {})
    return section if isinstance(section, dict) else {}


def cfg_path(section: dict, field: str, default: str | Path) -> Path:
    """Resolve a path-valued config field, expanding ``~``; fall back to default."""
    value = section.get(field, default)
    return Path(value).expanduser()
