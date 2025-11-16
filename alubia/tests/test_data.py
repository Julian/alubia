from datetime import date

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


BANK = Assets.Bank.Checking


class TestPosting:
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
