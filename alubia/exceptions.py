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
