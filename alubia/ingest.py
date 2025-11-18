"""
Ingestion helpers for reading in files.
"""

from __future__ import annotations

from csv import DictReader
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def from_csv(
    path: Path,
    date_from: str = "Date",
    payee_from: str = "Description",
) -> Iterable[tuple[date, str, dict[str, Any]]]:
    """
    Partially parse a given csv path.
    """
    with path.open(newline="") as contents:
        reader = DictReader(contents)
        for row in reader:
            date_str = row.pop(date_from)
            row_date = date.strptime(date_str, "%m/%d/%Y")
            payee = row.pop(payee_from).strip()
            yield row_date, payee, row
