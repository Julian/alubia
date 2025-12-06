"""
Ingestion helpers for reading in files.
"""

from __future__ import annotations

from csv import DictReader
from typing import TYPE_CHECKING, Any
import datetime
import re

from attrs import frozen

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from alubia.data import (
        Transaction,
        _PostingLike,  # type: ignore[reportPrivateUsage]
        _TransactionLike,  # type: ignore[reportPrivateUsage]
    )


type Row = dict[str, str]


def _to_date(row: Row) -> datetime.date:
    if "Date" in row:
        raw = row["Date"]
    elif "date" in row:
        raw = row["date"]
    else:
        raise ValueError(f"Can't guess where the date is in {row}")

    parts = re.split("[-/]", raw)
    fmt = "%Y/%m/%d" if len(parts[0]) == 4 else "%m/%d/%Y"  # noqa: PLR2004
    return datetime.date.strptime("/".join(parts), fmt)


def from_csv(
    path: Path,
    date: Callable[[Row], datetime.date] = _to_date,
    payee: Callable[[Row], str] = lambda row: row["Description"],
    encoding: str | None = None,
) -> Iterable[tuple[_PartialTransaction, dict[str, Any]]]:
    """
    Partially parse a given csv path.
    """
    with path.open(newline="", encoding=encoding) as contents:
        reader = DictReader(_nonempty(contents))
        for row in reader:
            row_payee = payee(row).strip()
            yield _PartialTransaction(date(row), row_payee), row


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

    def commented(
        self,
        *args: _PostingLike,
        **kwargs: Any,
    ) -> _TransactionLike:
        return self(*args, **kwargs).commented()
