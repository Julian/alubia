from __future__ import annotations

import json

from alubia.data import Assets, Expenses, Income
from alubia.ingest import RuleTable


class TestRuleTable:
    def test_exact_match(self):
        table = RuleTable(exact={"FOO": Income.Foo})
        assert table.match("FOO") == Income.Foo

    def test_prefix_match(self):
        table = RuleTable(prefix={"GITHUB SPONSORS ": Income.GitHubSponsors})
        assert table.match("GITHUB SPONSORS julian") == Income.GitHubSponsors

    def test_exact_beats_prefix(self):
        table = RuleTable(
            exact={"FOO BAR": Income.Exact},
            prefix={"FOO ": Income.Prefix},
        )
        assert table.match("FOO BAR") == Income.Exact

    def test_first_prefix_wins(self):
        table = RuleTable(
            prefix={
                "PAY": Income.Short,
                "PAYROLL ": Income.Long,
            },
        )
        assert table.match("PAYROLL JAN") == Income.Short

    def test_no_match(self):
        table = RuleTable(exact={"FOO": Income.Foo})
        assert table.match("BAR") is None

    def test_flagged_account(self):
        table = RuleTable.from_mapping(
            {"exact": {"Mystery": "! Expenses:Unknown"}},
        )
        assert table.match("Mystery") == ~Expenses.Unknown


class TestRuleTableValidate:
    def test_clean(self):
        table = RuleTable(
            exact={"FOO": Income.A},
            prefix={"BAR ": Income.B},
        )
        assert table.validate() == []

    def test_exact_redundant_with_prefix(self):
        table = RuleTable(
            exact={"FOO BAR": Income.A},
            prefix={"FOO ": Income.B},
        )
        issues = table.validate()
        assert len(issues) == 1
        assert "redundant" in issues[0]
        assert "'FOO BAR'" in issues[0]
        assert "'FOO '" in issues[0]

    def test_unreachable_prefix(self):
        table = RuleTable(
            prefix={
                "PAY": Income.A,
                "PAYROLL ": Income.B,
            },
        )
        issues = table.validate()
        assert len(issues) == 1
        assert "unreachable" in issues[0]
        assert "'PAYROLL '" in issues[0]


class TestRuleTableMerge:
    def test_combines(self):
        a = RuleTable(exact={"X": Income.A}, prefix={"P ": Income.P})
        b = RuleTable(exact={"Y": Income.B}, prefix={"Q ": Income.Q})
        merged = RuleTable.merge(a, b)
        assert merged == RuleTable(
            exact={"X": Income.A, "Y": Income.B},
            prefix={"P ": Income.P, "Q ": Income.Q},
        )

    def test_later_overrides_earlier(self):
        a = RuleTable(exact={"X": Income.A})
        b = RuleTable(exact={"X": Income.B})
        assert RuleTable.merge(a, b).exact["X"] == Income.B

    def test_no_args(self):
        assert RuleTable.merge() == RuleTable()


class TestRuleTableLoading:
    def test_from_mapping(self):
        table = RuleTable.from_mapping(
            {
                "exact": {"Mystery Deposit": "Income:Misc"},
                "prefix": {"GITHUB SPONSORS ": "Income:GitHubSponsors"},
            },
        )
        assert table.match("Mystery Deposit") == Income.Misc
        assert table.match("GITHUB SPONSORS julian") == Income.GitHubSponsors

    def test_from_mapping_empty(self):
        assert RuleTable.from_mapping({}) == RuleTable()

    def test_from_json(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(
            json.dumps(
                {
                    "exact": {"FOO": "Assets:Bank:Checking"},
                    "prefix": {"BAR ": "Expenses:Misc"},
                },
            ),
        )
        table = RuleTable.from_json(path)
        assert table.match("FOO") == Assets.Bank.Checking
        assert table.match("BAR baz") == Expenses.Misc
