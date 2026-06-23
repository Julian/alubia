"""
Stuff which went wrong.
"""


class InvalidTransaction(Exception):
    """
    A transaction is invalid.
    """


class InvalidOperation(Exception):
    """
    An invalid operation was performed on an amount.
    """


class InvalidAccount(Exception):
    """
    An account name is not a valid beancount account.
    """
