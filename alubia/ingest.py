"""
Ingestion helpers for reading in files.
"""

from __future__ import annotations

from csv import DictReader
from typing import TYPE_CHECKING, Any
import datetime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path


def from_csv(
    path: Path,
    date: Callable[[dict[str, Any]], str] = lambda row: row["Date"],
    payee: Callable[[dict[str, Any]], str] = lambda row: row["Description"],
) -> Iterable[tuple[datetime.date, str, dict[str, Any]]]:
    """
    Partially parse a given csv path.
    """
    with path.open(newline="") as contents:
        reader = DictReader(contents)
        for row in reader:
            row_date = datetime.date.strptime(date(row), "%m/%d/%Y")
            yield row_date, payee(row).strip(), row
