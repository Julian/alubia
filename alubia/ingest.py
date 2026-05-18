"""
Ingestion helpers for reading in files.
"""

from __future__ import annotations

from csv import DictReader
from typing import TYPE_CHECKING, Any
import datetime
import json
import re

from attrs import field, frozen

from alubia.data import Account

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
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
    narration: Callable[[Row], str | None] = lambda row: None,
    encoding: str | None = None,
) -> Iterable[tuple[_PartialTransaction, dict[str, Any]]]:
    """
    Partially parse a given csv path.
    """
    with path.open(newline="", encoding=encoding) as contents:
        reader = DictReader(_nonempty(contents))
        for row in reader:
            partial = _PartialTransaction(
                date=date(row),
                payee=payee(row).strip(),
                narration=narration(row),
            )
            yield partial, row


def _nonempty(lines: Iterable[str]):
    for each in lines:
        line = each.strip()
        if line:
            yield line


@frozen
class RuleTable:
    """
    A table of payee -> account rules.

    Rules are checked in the order: ``exact`` (full string match), then
    ``prefix`` (first matching prefix in insertion order wins). ``match``
    returns ``None`` when nothing matched so callers can pick their own
    sentinel (e.g. ``~Expenses.Unknown``).
    """

    exact: Mapping[str, Account] = field(factory=dict)
    prefix: Mapping[str, Account] = field(factory=dict)

    def match(self, payee: str) -> Account | None:
        """
        Return the account matching ``payee``, or ``None`` if none matches.
        """
        if payee in self.exact:
            return self.exact[payee]
        for prefix, account in self.prefix.items():
            if payee.startswith(prefix):
                return account
        return None

    def validate(self) -> list[str]:
        """
        Return human-readable warnings about overlapping or unreachable rules.

        An empty list means the table is unambiguous.
        """
        issues: list[str] = []
        for payee in self.exact:
            for prefix in self.prefix:
                if payee.startswith(prefix):
                    issues.append(
                        f"exact rule {payee!r} is redundant with "
                        f"prefix rule {prefix!r}",
                    )
                    break

        prefixes = list(self.prefix)
        issues.extend(
            f"prefix rule {longer!r} is unreachable: "
            f"earlier prefix {shorter!r} matches first"
            for i, shorter in enumerate(prefixes)
            for longer in prefixes[i + 1 :]
            if longer.startswith(shorter)
        )
        return issues

    @classmethod
    def merge(cls, *tables: RuleTable) -> RuleTable:
        """
        Combine multiple tables; later tables win on conflict.
        """
        exact: dict[str, Account] = {}
        prefix: dict[str, Account] = {}
        for table in tables:
            exact.update(table.exact)
            prefix.update(table.prefix)
        return cls(exact=exact, prefix=prefix)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Mapping[str, str]]) -> RuleTable:
        """
        Build a table from a nested mapping with ``exact`` / ``prefix`` keys.
        """
        return cls(
            exact={
                k: Account.from_str(v)
                for k, v in data.get("exact", {}).items()
            },
            prefix={
                k: Account.from_str(v)
                for k, v in data.get("prefix", {}).items()
            },
        )

    @classmethod
    def from_json(cls, path: Path) -> RuleTable:
        """
        Load a rule table from a JSON file.
        """
        return cls.from_mapping(json.loads(path.read_text()))


@frozen
class _PartialTransaction:
    """
    A partially parsed transaction.
    """

    date: datetime.date
    payee: str
    narration: str | None

    def __call__(
        self,
        first: _PostingLike,
        *args: _PostingLike,
        **kwargs: Any,
    ) -> Transaction:
        kwargs.setdefault("narration", self.narration)
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
