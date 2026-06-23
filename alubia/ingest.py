"""
Ingestion helpers for reading in files.
"""

from __future__ import annotations

from csv import DictReader
from typing import TYPE_CHECKING, Any, Literal
import datetime
import json
import re

from attrs import evolve, field, frozen

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


def pascal(name: str) -> str:
    """
    PascalCase a free-form name into a valid account component.

    Separators and other punctuation are dropped, so ``"MARY-ANNE FRY"`` and
    ``"John Smith Jr."`` become ``"MaryAnneFry"`` and ``"JohnSmithJr"``.
    """
    return re.sub(r"[^0-9A-Za-z]", "", name.title())


def as_is(name: str) -> str:
    """
    Return ``name`` unchanged.
    """
    return name


SANITIZERS: dict[str, Callable[[str], str]] = {
    "pascal": pascal,
    "as-is": as_is,
}


@frozen
class Match:
    """
    A successful rule lookup: which kind of rule fired, its key, the account.
    """

    kind: Literal["exact", "prefix", "dynamic"]
    key: str
    account: Account


@frozen
class DynamicRule:
    """
    A prefix-with-template rule for dynamic account lookups.

    Strips ``prefix`` off the payee, sanitizes the remainder, and returns
    ``under[sanitized_remainder]``. For example,
    ``DynamicRule("ZELLE FROM ", Income.DirectPay)`` maps
    ``"ZELLE FROM Mary-Anne"`` to ``Income:DirectPay:MaryAnne``. The default
    `pascal` sanitizer keeps the remainder a valid account component; choose
    `as_is` only when it already is one (e.g. a ticker symbol).
    """

    prefix: str
    under: Account
    sanitize: Callable[[str], str] = field(default=pascal)

    def match(self, payee: str) -> Account | None:
        """
        Return the resolved child account, or ``None`` if no prefix match.
        """
        if not payee.startswith(self.prefix):
            return None
        return self.under[self.sanitize(payee.removeprefix(self.prefix))]


@frozen
class RuleTable:
    """
    A table of payee -> account rules.

    Rules are checked in the order: ``exact`` (full string match), ``prefix``
    (first matching prefix in insertion order wins), then ``dynamic`` (prefix
    plus sanitized-name lookup under a root account). ``match`` returns
    ``None`` when nothing matched so callers can pick their own sentinel
    (e.g. ``~Expenses.Unknown``).
    """

    exact: Mapping[str, Account] = field(factory=dict)
    prefix: Mapping[str, Account] = field(factory=dict)
    dynamic: tuple[DynamicRule, ...] = field(factory=tuple, converter=tuple)

    def match(self, payee: str) -> Account | None:
        """
        Return the account matching ``payee``, or ``None`` if none matches.
        """
        result = self.match_rule(payee)
        return result.account if result is not None else None

    def match_rule(self, payee: str) -> Match | None:
        """
        Like ``match``, but also tells you which rule fired.
        """
        if payee in self.exact:
            return Match(kind="exact", key=payee, account=self.exact[payee])
        for prefix, account in self.prefix.items():
            if payee.startswith(prefix):
                return Match(kind="prefix", key=prefix, account=account)
        for rule in self.dynamic:
            account = rule.match(payee)
            if account is not None:
                return Match(kind="dynamic", key=rule.prefix, account=account)
        return None

    def tracked(self) -> Tracker:
        """
        Wrap this table in a `Tracker` that records which rules fire.
        """
        return Tracker(rules=self)

    def with_dynamic(self, *rules: DynamicRule) -> RuleTable:
        """
        Return a new table with the given dynamic rules appended.
        """
        return evolve(self, dynamic=self.dynamic + tuple(rules))

    def validate(self) -> list[str]:
        """
        Return human-readable warnings about overlapping or unreachable rules.

        An empty list means the table is unambiguous.
        """
        issues: list[str] = []
        for payee, account in self.exact.items():
            for prefix, prefixed in self.prefix.items():
                if payee.startswith(prefix):
                    # Only the first matching prefix would ever fire, and an
                    # exact rule that resolves elsewhere is a deliberate
                    # override, not a redundancy.
                    if account == prefixed:
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

        for rule in self.dynamic:
            for regular in self.prefix:
                if rule.prefix.startswith(regular):
                    issues.append(
                        f"dynamic prefix {rule.prefix!r} is unreachable: "
                        f"regular prefix {regular!r} matches first",
                    )
                    break

        dynamic_prefixes = [r.prefix for r in self.dynamic]
        issues.extend(
            f"dynamic prefix {longer!r} is unreachable: "
            f"earlier dynamic prefix {shorter!r} matches first"
            for i, shorter in enumerate(dynamic_prefixes)
            for longer in dynamic_prefixes[i + 1 :]
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
        dynamic: list[DynamicRule] = []
        for table in tables:
            exact.update(table.exact)
            prefix.update(table.prefix)
            dynamic.extend(table.dynamic)
        return cls(exact=exact, prefix=prefix, dynamic=tuple(dynamic))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RuleTable:
        """
        Build a table from a mapping with exact/prefix/dynamic sections.
        """
        dynamic: list[DynamicRule] = []
        for entry in data.get("dynamic", ()):
            sanitize_name = entry.get("sanitize", "pascal")
            if sanitize_name not in SANITIZERS:
                raise ValueError(
                    f"unknown sanitizer {sanitize_name!r}; "
                    f"known: {sorted(SANITIZERS)}",
                )
            dynamic.append(
                DynamicRule(
                    prefix=entry["prefix"],
                    under=Account.from_str(entry["under"]),
                    sanitize=SANITIZERS[sanitize_name],
                ),
            )
        return cls(
            exact={
                k: Account.from_str(v)
                for k, v in data.get("exact", {}).items()
            },
            prefix={
                k: Account.from_str(v)
                for k, v in data.get("prefix", {}).items()
            },
            dynamic=tuple(dynamic),
        )

    @classmethod
    def from_json(cls, path: Path) -> RuleTable:
        """
        Load a rule table from a JSON file.
        """
        return cls.from_mapping(json.loads(path.read_text()))


@frozen
class Tracker:
    """
    A `RuleTable` wrapper that records which rules have matched.

    Use it as a drop-in replacement for the underlying table, then call
    `unused` at the end of ingestion to find stale rules.
    """

    rules: RuleTable
    _hits: set[tuple[str, str]] = field(factory=set)

    def match(self, payee: str) -> Account | None:
        """
        Match ``payee`` and record the hit.
        """
        result = self.match_rule(payee)
        return result.account if result is not None else None

    def match_rule(self, payee: str) -> Match | None:
        """
        Match ``payee``, recording which rule fired.
        """
        result = self.rules.match_rule(payee)
        if result is not None:
            self._hits.add((result.kind, result.key))
        return result

    def unused(self) -> list[Match]:
        """
        Rules that never matched anything during this tracker's lifetime.

        For dynamic rules, ``account`` is the rule's ``under`` root account.
        """
        return (
            [
                Match(kind="exact", key=key, account=account)
                for key, account in self.rules.exact.items()
                if ("exact", key) not in self._hits
            ]
            + [
                Match(kind="prefix", key=key, account=account)
                for key, account in self.rules.prefix.items()
                if ("prefix", key) not in self._hits
            ]
            + [
                Match(kind="dynamic", key=rule.prefix, account=rule.under)
                for rule in self.rules.dynamic
                if ("dynamic", rule.prefix) not in self._hits
            ]
        )


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
