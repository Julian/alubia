"""
Ingestion helpers for reading in files.
"""

from __future__ import annotations

from csv import DictReader
from typing import TYPE_CHECKING, Any
import datetime

from attrs import frozen

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from alubia.data import (
        Transaction,
        _PostingLike,  # type: ignore[reportPrivateUsage]
    )


def from_csv(
    path: Path,
    date: Callable[[dict[str, Any]], str] = lambda row: row["Date"],
    payee: Callable[[dict[str, Any]], str] = lambda row: row["Description"],
    encoding: str | None = None,
) -> Iterable[tuple[_PartialTransaction, dict[str, Any]]]:
    """
    Partially parse a given csv path.
    """
    with path.open(newline="", encoding=encoding) as contents:
        reader = DictReader(_nonempty(contents))
        for row in reader:
            row_date = datetime.date.strptime(date(row), "%m/%d/%Y")
            row_payee = payee(row).strip()
            yield _PartialTransaction(row_date, row_payee), row


def _nonempty(lines: Iterable[str]):
    for each in lines:
        line = each.strip()
        if line:
            yield line


@frozen
class _PartialTransaction:
    """
    A partially parsed transaction.
    """

    date: datetime.date
    payee: str

    def __call__(
        self,
        first: _PostingLike,
        *args: _PostingLike,
        **kwargs: Any,
    ) -> Transaction:
        return first.transact(
            *args,
            **kwargs,
            date=self.date,
            payee=self.payee,
        )
