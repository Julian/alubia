from __future__ import annotations

import json

from alubia.data import Assets, Expenses, Income
from alubia.ingest import Match, RuleTable


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


class TestMatchRule:
    def test_exact_returns_match(self):
        table = RuleTable(exact={"FOO": Income.A})
        assert table.match_rule("FOO") == Match(
            kind="exact",
            key="FOO",
            account=Income.A,
        )

    def test_prefix_returns_match(self):
        table = RuleTable(prefix={"BAR ": Income.B})
        assert table.match_rule("BAR baz") == Match(
            kind="prefix",
            key="BAR ",
            account=Income.B,
        )

    def test_no_match(self):
        assert RuleTable(exact={"FOO": Income.A}).match_rule("X") is None


class TestTracker:
    def test_records_exact_hits(self):
        table = RuleTable(exact={"FOO": Income.A, "BAR": Income.B})
        tracker = table.tracked()
        tracker.match("FOO")
        assert tracker.unused() == [
            Match(kind="exact", key="BAR", account=Income.B),
        ]

    def test_records_prefix_hits(self):
        table = RuleTable(prefix={"P ": Income.P, "Q ": Income.Q})
        tracker = table.tracked()
        tracker.match("P thing")
        assert tracker.unused() == [
            Match(kind="prefix", key="Q ", account=Income.Q),
        ]

    def test_no_hits(self):
        table = RuleTable(
            exact={"X": Income.X},
            prefix={"Y ": Income.Y},
        )
        tracker = table.tracked()
        assert tracker.unused() == [
            Match(kind="exact", key="X", account=Income.X),
            Match(kind="prefix", key="Y ", account=Income.Y),
        ]

    def test_all_hit(self):
        table = RuleTable(exact={"X": Income.X}, prefix={"Y ": Income.Y})
        tracker = table.tracked()
        tracker.match("X")
        tracker.match("Y stuff")
        assert tracker.unused() == []

    def test_unmatched_payee_no_hit(self):
        table = RuleTable(exact={"X": Income.X})
        tracker = table.tracked()
        tracker.match("nope")
        assert tracker.unused() == [
            Match(kind="exact", key="X", account=Income.X),
        ]

    def test_match_returns_account(self):
        table = RuleTable(exact={"FOO": Income.A})
        tracker = table.tracked()
        assert tracker.match("FOO") == Income.A
        assert tracker.match("nope") is None

    def test_match_rule_returns_match(self):
        table = RuleTable(prefix={"P ": Income.P})
        tracker = table.tracked()
        assert tracker.match_rule("P x") == Match(
            kind="prefix",
            key="P ",
            account=Income.P,
        )

    def test_duplicate_hits_counted_once(self):
        table = RuleTable(exact={"X": Income.X, "Y": Income.Y})
        tracker = table.tracked()
        tracker.match("X")
        tracker.match("X")
        assert tracker.unused() == [
            Match(kind="exact", key="Y", account=Income.Y),
        ]


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
