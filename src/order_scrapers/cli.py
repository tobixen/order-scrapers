"""Shared argparse scaffolding for the shop history commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__


def base_parser(description: str) -> argparse.ArgumentParser:
    """An ArgumentParser with a standard ``--version``/``-V`` flag."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--version", "-V", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def add_store_args(parser: argparse.ArgumentParser, default_output: Path) -> None:
    """Add the common output / update-all / dry-run options."""
    parser.add_argument(
        "-o", "--output", type=Path, default=default_output,
        help=f"append-only JSONL history file (default: {default_output})",
    )
    parser.add_argument(
        "--update-all", action="store_true",
        help="re-collect everything and rewrite changed records (instead of only "
        "appending new ones)",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="show what would change without writing the file",
    )
