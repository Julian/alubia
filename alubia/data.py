"""
Something like beancount's own API with some niceties.
"""

from __future__ import annotations

from _pydecimal import Decimal  # the C module obfuscates exception messages
from functools import total_ordering
from typing import TYPE_CHECKING, Any, Literal, Protocol

from attrs import evolve, field, frozen
from rpds import Queue

from alubia.exceptions import InvalidOperation, InvalidTransaction

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date

    from attrs import Attribute


def _to_beancount_account_str(parts: Iterable[str]):
    return ":".join(parts)


_DEFAULT_WIDTH = 100


@frozen
class Transaction:
    """
    A beancount transaction.
    """

    date: date
    postings: Sequence[Posting] = field()
    payee: str
    narration: str = ""

    @postings.validator  # ty:ignore[unresolved-attribute] (ty#267)
    def _check(
        self,
        attribute: Attribute[Sequence[Posting]],
        value: Sequence[Posting],
    ):
        implicit = {posting for posting in value if posting.amount is None}
        if len(implicit) > 1:
            raise InvalidTransaction(
                f"Multiple postings have implicit amounts: {implicit}",
            )

    def commented(self):
        """
        Comment out this transaction.
        """
        return _Commented(self)

    def explicit(self):
        """
        A version of this transaction where all postings have explicit amounts.
        """
        if not self.postings:
            return self

        implicit: int | None = None
        commodities: set[str] = set()
        total: Amount | int = 0
        postings: list[Posting | None] = []
        for i, posting in enumerate(self.postings):
            if posting.amount is None:
                assert implicit is None, "somehow multiple implicit postings??"
                implicit = i
                postings.append(None)
            else:
                commodities.add(posting.amount.commodity)
                if len(commodities) == 1:  # otherwise we'll fail if implicit
                    total += posting.amount
                    postings.append(posting)
        if implicit is None:
            return self
        if len(commodities) > 1:
            raise InvalidTransaction(
                "Cannot balance a transaction with multiple commodities "
                f"{commodities}",
            )

        postings[implicit] = -evolve(self.postings[implicit], amount=total)
        return evolve(self, postings=postings)

    def serialize(self, width: int = _DEFAULT_WIDTH):
        """
        Export this transaction to beancount's format.
        """
        narration = f' "{self.narration}"' if self.narration else ""
        lines = [f'{self.date} * "{self.payee}"{narration}']
        lines.extend(
            f"  {posting.serialize(width)}" for posting in self.postings
        )
        return "\n".join(lines)


@frozen
class Posting:
    """
    A leg of a transaction (i.e. a single account and amount).
    """

    account: Account = field(alias="account", repr=str)
    amount: Amount | None = field(default=None)
    comment: str | None = field(default=None)

    def __neg__(self):
        if self.amount is None:
            return NotImplemented
        return evolve(self, amount=-self.amount)

    def serialize(self, width: int):
        """
        Export this posting to beancount's line format.
        """
        comment = f" ; {self.comment}" if self.comment else ""
        if not self.amount:
            return f"{self.account}{comment}"

        amount = str(self.amount)
        padding = width - len(amount)
        return f"{self.account:<{padding}}{amount}{comment}"

    def transact(self, *postings: _PostingLike, **kwargs: Any):
        """
        Create a transaction with this posting in it.
        """
        combined: list[Posting] = [self]
        combined.extend(each.posting() for each in postings)
        return Transaction(postings=combined, **kwargs)

    def posting(self):
        """
        We are already one.
        """
        return self


@frozen
class Account:
    """
    A beancount account.
    """

    _parts: Queue[str] = field(
        alias="parts",
        converter=Queue,
        repr=_to_beancount_account_str,
    )
    _prefix: str = field(alias="prefix", default="")

    def __getattr__(self, name: str):
        """
        Get a child of this account if the name part is valid.
        """
        if not name[0].isupper():
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'",
            )
        return self.child(name)

    def __getitem__(self, name: str):
        """
        Get a child of this account.
        """
        return self.child(name)

    def __invert__(self):
        """
        Mark this account flagged when it is part of a posting.
        """
        prefix = "" if self._prefix else "! "
        return evolve(self, prefix=prefix)

    def __format__(self, spec: str):
        return format(str(self), spec)

    def __str__(self):
        return f"{self._prefix}{_to_beancount_account_str(self._parts)}"

    def balance(self, date: date, amount: Amount, width: int = _DEFAULT_WIDTH):
        """
        Emit a balance assertion on this account.
        """
        without_prefix = width - 29
        return f"{date} balance {self:<{without_prefix}} {amount}"

    def child(self, name: str):
        """
        A child of this account.
        """
        return evolve(self, parts=self._parts.enqueue(name))

    def posting(self, **kwargs: Any) -> Posting:
        """
        A posting for this account.
        """
        return Posting(account=self, **kwargs)

    def transact[**P](self, *args: Posting, **kwargs: P.kwargs):
        """
        Transact on this account as an implicit posting.
        """
        return self.posting().transact(*args, **kwargs)


def _sign(value: str):
    if value.startswith("-"):
        create, rest = Amount.debit, value[1:]
    elif value.startswith("(") and value.endswith(")"):
        create, rest = Amount.debit, value[1:-1]
    else:
        create, rest = Amount, value
    return create, rest.replace(",", "")


@frozen
@total_ordering
class Amount:
    """
    A number of a specific commodity.
    """

    number: Decimal
    commodity: str
    label: str = ""
    held_at: Amount | None = None
    cost: _TotalCost | _UnitCost | None = None

    @classmethod
    def for_commodity(cls, commodity: str):
        """
        Return a callable which parses strings into the given commodity.
        """

        def parse(value: str, **kwargs: Any) -> Amount:
            create, rest = _sign(value)
            return create(number=Decimal(rest), commodity=commodity, **kwargs)

        return parse

    @classmethod
    def from_str(cls, value: str, **kwargs: Any) -> Amount:
        """
        Extract an amount from a string.
        """
        create, rest = _sign(value)
        match rest[0]:
            case "$":
                commodity = "USD"
            case "£":
                commodity = "GBP"
            case "€":
                commodity = "EUR"
            case _:
                raise NotImplementedError(value)
        return create(number=Decimal(rest[1:]), commodity=commodity, **kwargs)

    @classmethod
    def debit(cls, **kwargs: Any):
        """
        A convenience constructor for negative amounts.
        """
        return -cls(**kwargs)

    def __add__(self, other: Amount):
        if other.commodity != self.commodity:
            return NotImplemented

        held_at = self.held_at
        if held_at:
            if not other.held_at:
                return NotImplemented
            held_at += other.held_at
        elif other.held_at:
            return NotImplemented

        cost = self.cost
        if cost is None:
            cost = other.cost
        elif other.cost is not None and other.cost != self.cost:
            raise InvalidOperation("Incompatible costs")

        return evolve(
            self,
            cost=cost,
            number=self.number + other.number,
            held_at=held_at,
        )

    def __bool__(self):
        return bool(self.number)

    def __neg__(self):
        return evolve(self, number=-self.number)

    def __truediv__(self, n: int):
        held_at: Amount | None = (
            None if self.held_at is None else self.held_at / n
        )
        cost = None if self.cost is None else self.cost / n
        return evolve(
            self,
            number=self.number / n,
            held_at=held_at,
            cost=cost,
        )

    def __lt__(self, other: Amount | Literal[0]):
        if other == 0:
            other = self.zero()
        elif (
            self.__class__ is not other.__class__
            or self.commodity != other.commodity
        ):
            return NotImplemented
        return self.number < other.number

    def __radd__(self, other: Literal[0]):
        if other != 0:
            return NotImplemented
        return self

    def __rmul__(self, other: Decimal):
        return evolve(self, number=other * self.number)

    def __str__(self):
        parts: list[str] = []
        if self.held_at:
            parts.append(str(self.held_at))
        if self.label:
            parts.append(f'"{self.label}"')
        braced = f" {{{', '.join(parts)}}}" if parts else ""

        cost = "" if self.cost is None else str(self.cost)
        return f"{self.number} {self.commodity}{braced}{cost}"

    def total_cost(self):
        """
        A total cost of this amount.
        """
        return _TotalCost(amount=self)

    def unit_cost(self):
        """
        A unit cost of this amount.
        """
        return _UnitCost(amount=self)

    def zero(self):
        """
        Zero in this commodity.
        """
        return evolve(self, number=Decimal(0))


@frozen
class _TotalCost:
    amount: Amount

    def __str__(self):
        return f" @@ {self.amount}"

    def __truediv__(self, n: int):
        return evolve(self, amount=self.amount / n)


@frozen
class _UnitCost:
    amount: Amount

    def __str__(self):
        return f" @ {self.amount}"

    def __truediv__(self, n: int):
        return evolve(self, amount=self.amount / n)


@frozen
class _Commented:
    """
    A commented out beancount item.
    """

    _wrapped: Transaction

    def commented(self):
        """
        We're already there.
        """
        return self

    def explicit(self):
        return self.__class__(self._wrapped.explicit())

    def serialize(self, width: int = _DEFAULT_WIDTH):
        serialized: str = self._wrapped.serialize(width - 2)
        return "".join(f"; {line}" for line in serialized.splitlines(True))


class _PostingLike(Protocol):
    """
    A thing which can be treated like a posting.

    Basically a posting or an account.
    """

    def posting(self) -> Posting: ...

    def transact(
        self,
        *postings: _PostingLike,
        **kwargs: Any,
    ) -> Transaction: ...


class _TransactionLike(Protocol):
    """
    A thing which can be treated like a transaction.
    """

    def commented(self) -> _TransactionLike: ...

    def explicit(self) -> _TransactionLike: ...

    def serialize(self, width: int = _DEFAULT_WIDTH) -> str: ...


Assets = Account(["Assets"])  # ty:ignore[invalid-argument-type] (ty#972)
Expenses = Account(["Expenses"])  # ty:ignore[invalid-argument-type] (ty#972)
Income = Account(["Income"])  # ty:ignore[invalid-argument-type] (ty#972)
Liabilities = Account(["Liabilities"])  # ty:ignore[invalid-argument-type] (ty#972)
