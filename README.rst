==========
``alubia``
==========

|PyPI| |Pythons| |CI|

.. |PyPI| image:: https://img.shields.io/pypi/v/alubia.svg
  :alt: PyPI version
  :target: https://pypi.org/project/alubia/

.. |Pythons| image:: https://img.shields.io/pypi/pyversions/alubia.svg
  :alt: Supported Python versions
  :target: https://pypi.org/project/alubia/

.. |CI| image:: https://github.com/Julian/alubia/workflows/CI/badge.svg
  :alt: Build status
  :target: https://github.com/Julian/alubia/actions?query=workflow%3ACI


Example
=======

.. code-block:: python

    from datetime import date

    from alubia.data import Amount, Assets, Expenses

    USD = Amount.for_commodity("USD")
    CHECKING = Assets.Checking
    GROCERIES = Expenses.Groceries

    transaction = GROCERIES.transact(
        CHECKING.posting(amount=USD("-50")),
        date=date(2024, 1, 1),
        payee="Grocery Store",
    )

    # Serialize the transaction to beancount format
    print(tx.explicit().serialize())

Outputs:

.. code-block:: text

    2024-01-01 * "Grocery Store"
      Expenses:Groceries                                                                        50.00 USD
      Assets:Checking                                                                          -50.00 USD
