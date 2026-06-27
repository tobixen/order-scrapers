"""Append-only order/purchase history builders (JSONL) for various web shops."""

from __future__ import annotations

try:
    from ._version import __version__
except ImportError:  # not built yet (e.g. running from a plain checkout)
    __version__ = "0+unknown"

__all__ = ["__version__"]
