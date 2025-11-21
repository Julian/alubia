from datetime import date
from decimal import Decimal, InvalidOperation
from textwrap import dedent

import pytest

from alubia.data import (
    Amount,
    Assets,
    Expenses,
    Income,
    Liabilities,
    Posting,
    Transaction,
)
from alubia.exceptions import InvalidTransaction

TODAY = date.today()
USD100 = Amount.from_str("$100.00")
USD200 = Amount.from_str("$200.00")


class TestAccount:
    def test_account_child(self):
        assert str(Expenses.Food.Meals) == "Expenses:Food:Meals"
        assert str(Assets.Bank.Checking) == "Assets:Bank:Checking"

    def test_account_invalid(self):
        with pytest.raises(AttributeError):
            Expenses.food

    def test_dynamic_account(self):
        account = Liabilities.Credit["visa".title()]
        assert str(account) == "Liabilities:Credit:Visa"

    def test_flagged_account(self):
        assert str(~Liabilities.Credit.Visa) == "! Liabilities:Credit:Visa"

    def test_posting(self):
        account = Assets.Bank.Checking
        posting = account.posting(amount=USD100)
        assert posting == Posting(account=account, amount=USD100)

    def test_transact(self):
        assert BANK.transact(
            Liabilities.Credit.Visa.posting(amount=USD100),
            date=date.today(),
            payee="Foo",
        ) == Transaction(
            payee="Foo",
            date=date.today(),
            postings=[
                BANK.posting(),
                Liabilities.Credit.Visa.posting(amount=USD100),
            ],
        )

    def test_flagged(self):
        assert str(~Assets.Bank.Checking) == "! Assets:Bank:Checking"


BANK = Assets.Bank.Checking


class TestPosting:
    def test_posting_negation(self):
        account = Assets.Bank.Checking
        posting = Posting(account=account, amount=USD100)
        assert -posting == Posting(account=account, amount=-USD100)

    def test_transact(self):
        posting = BANK.posting(amount=USD100)
        transaction = posting.transact(
            Liabilities.Credit.Visa.posting(),
            date=date.today(),
            payee="Foo Bar",
        )
        assert transaction == Transaction(
            payee="Foo Bar",
            date=date.today(),
            postings=[
                BANK.posting(amount=USD100),
                Liabilities.Credit.Visa.posting(),
            ],
        )

    def test_transact_bare_account(self):
        posting = BANK.posting(amount=USD100)
        transaction = posting.transact(
            Liabilities.Credit.Visa,
            payee="Baz Quux",
            date=date.today(),
        )
        assert transaction == Transaction(
            date=date.today(),
            payee="Baz Quux",
            postings=[
                BANK.posting(amount=USD100),
                Liabilities.Credit.Visa.posting(),
            ],
        )

    def test_default_amount(self):
        assert Posting(account=BANK, amount=None) == Posting(account=BANK)


class TestTransaction:
    def test_explicit_two_postings_one_implicit(self):
        tx = Transaction(
            date=TODAY,
            payee="",
            postings=[
                Posting(account=Assets.Cash, amount=USD100),
                Posting(account=Income.Salary),
            ],
        )
        assert tx.explicit() == Transaction(
            date=TODAY,
            payee="",
            postings=[
                Posting(account=Assets.Cash, amount=USD100),
                Posting(account=Income.Salary, amount=-USD100),
            ],
        )

    def test_explicit_multiple_postings(self):
        tx = Transaction(
            date=TODAY,
            payee="",
            postings=[
                Posting(account=Assets.Cash, amount=USD100),
                Posting(account=Assets.Cash, amount=USD200),
                Posting(account=Income.Salary),
            ],
        )
        assert tx.explicit() == Transaction(
            date=TODAY,
            payee="",
            postings=[
                Posting(account=Assets.Cash, amount=USD100),
                Posting(account=Assets.Cash, amount=USD200),
                Posting(account=Income.Salary, amount=-(USD100 + USD200)),
            ],
        )

    def test_explicit_all_postings_have_amounts(self):
        tx = Transaction(
            date=TODAY,
            payee="",
            postings=[
                Posting(account=Assets.Cash, amount=USD100),
                Posting(account=Income.Salary, amount=-USD100),
            ],
        )
        assert tx.explicit() is tx

    def test_missing_amounts(self):
        p1 = Posting(account=Assets.Cash)
        p2 = Posting(account=Income.Salary)
        with pytest.raises(InvalidTransaction):
            Transaction(payee="", date=TODAY, postings=[p1, p2])


class TestAmount:
    def test_from_str_dollars(self):
        amount = Amount.from_str("$100.00")
        assert amount == Amount(commodity="USD", number=Decimal(100))

    def test_from_str_negative_dollars(self):
        amount = Amount.from_str("-$200.00")
        assert amount == -Amount(commodity="USD", number=Decimal(200))

    def test_from_str_accounting_notation(self):
        amount = Amount.from_str("($100.00)")
        assert amount == Amount(commodity="USD", number=Decimal(-100))

    def test_from_str_commodity(self):
        amount = Amount.from_str("100.00", commodity="STUFF")
        assert amount == Amount(commodity="STUFF", number=Decimal(100))

    def test_from_str_invalid(self):
        with pytest.raises(NotImplementedError):
            Amount.from_str("asdf")

    def test_from_str_commodity_conflict(self):
        with pytest.raises(InvalidOperation):
            Amount.from_str("$100.00", commodity="STUFF")

    def test_zero(self):
        zero_usd = Amount.from_str("$100.00").zero()
        assert zero_usd == Amount(commodity="USD", number=Decimal(0))

    def test_add(self):
        assert USD100 + USD200 == Amount(commodity="USD", number=Decimal(300))

    def test_div(self):
        assert USD200 / 2 == USD100

    def test_neg(self):
        assert -USD100 == Amount(commodity="USD", number=Decimal(-100))

    def test_gt(self):
        assert USD100 > 0

    def test_lt(self):
        assert USD100 < USD200

    def test_str_exact_dollar(self):
        amount = Amount(commodity="USD", number=Decimal(100))
        assert str(amount) == "100 USD"

    def test_str_cents(self):
        amount = Amount(commodity="USD", number=Decimal("100.23"))
        assert str(amount) == "100.23 USD"

    def test_str_quantized_round_down(self):
        amount = Amount(commodity="USD", number=Decimal("100.23456"))
        assert str(amount) == "100.23 USD"

    def test_str_quantized_round_up(self):
        amount = Amount(commodity="USD", number=Decimal("100.23566"))
        assert str(amount) == "100.24 USD"

    def test_str_held_at(self):
        amount = Amount(
            commodity="FOO",
            number=Decimal(37),
            held_at=USD100,
        )
        assert str(amount) == "37 FOO {100.00 USD}"

    def test_str_label(self):
        amount = Amount(
            commodity="FOO",
            number=Decimal(37),
            label="stuff",
        )
        assert str(amount) == '37 FOO {"stuff"}'

    def test_str_held_at_with_label(self):
        amount = Amount(
            commodity="FOO",
            number=Decimal(37),
            held_at=USD200,
            label="stuff",
        )
        assert str(amount) == '37 FOO {200.00 USD, "stuff"}'

    def test_str_total_cost(self):
        amount = Amount(
            commodity="FOO",
            number=Decimal(37),
            total_cost=USD100,
        )
        assert str(amount) == "37 FOO @@ 100.00 USD"


class TestCommented:
    def test_transaction(self):
        nye = date(2025, 12, 31)
        tx = (
            BANK.posting(amount=USD100)
            .transact(
                Assets.Foo,
                date=nye,
                payee="Lunch",
            )
            .commented()
        )
        expected = dedent(
            """\
            ; 2025-12-31 * "Lunch"
            ;   Assets:Bank:Checking                    100.00 USD
            ;   Assets:Foo
            """,
        ).strip()
        assert tx.serialize(width=50) == expected
