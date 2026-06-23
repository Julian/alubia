from __future__ import annotations

import json

import pytest

from alubia.data import Assets, Expenses, Income
from alubia.exceptions import InvalidAccount
from alubia.ingest import (
    DynamicRule,
    Match,
    RuleTable,
    as_is,
    pascal,
)


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
        # same account: the exact rule adds nothing the prefix wouldn't.
        table = RuleTable(
            exact={"FOO BAR": Income.A},
            prefix={"FOO ": Income.A},
        )
        issues = table.validate()
        assert len(issues) == 1
        assert "redundant" in issues[0]
        assert "'FOO BAR'" in issues[0]
        assert "'FOO '" in issues[0]

    def test_exact_override_of_prefix_is_not_flagged(self):
        # different account: a deliberate override, not a redundancy.
        table = RuleTable(
            exact={"FOO BAR": Income.A},
            prefix={"FOO ": Income.B},
        )
        assert table.validate() == []

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


class TestSanitizers:
    def test_pascal_basic(self):
        assert pascal("mary anne") == "MaryAnne"

    def test_pascal_hyphenated(self):
        assert pascal("MARY-ANNE FRY") == "MaryAnneFry"

    def test_pascal_single(self):
        assert pascal("bob") == "Bob"

    def test_pascal_drops_punctuation(self):
        assert pascal("John Smith Jr.") == "JohnSmithJr"
        assert pascal("O'Brien") == "OBrien"

    def test_pascal_is_a_valid_component(self):
        # whatever pascal emits must be usable as an account child
        assert str(Income.DirectPay[pascal("John Smith Jr.")]) == (
            "Income:DirectPay:JohnSmithJr"
        )

    def test_as_is(self):
        assert as_is("Mary-Anne Fry") == "Mary-Anne Fry"


class TestDynamicRule:
    def test_match(self):
        rule = DynamicRule("ZELLE FROM ", Income.DirectPay, pascal)
        assert rule.match("ZELLE FROM mary anne") == Income.DirectPay.MaryAnne

    def test_no_match(self):
        rule = DynamicRule("ZELLE FROM ", Income.DirectPay, pascal)
        assert rule.match("CHECK NUMBER 401") is None

    def test_default_sanitizer_is_pascal(self):
        rule = DynamicRule("X ", Income.A)
        assert rule.match("X foo bar") == Income.A.FooBar

    def test_invalid_component_is_rejected(self):
        # as_is leaves a space in, which is not a legal account component
        rule = DynamicRule("X ", Income.A, as_is)
        with pytest.raises(InvalidAccount):
            rule.match("X foo bar")


class TestRuleTableDynamic:
    def test_match_falls_through_to_dynamic(self):
        table = RuleTable(
            dynamic=(DynamicRule("ZELLE FROM ", Income.DirectPay, pascal),),
        )
        assert table.match("ZELLE FROM bob") == Income.DirectPay.Bob

    def test_match_rule_returns_dynamic_kind(self):
        table = RuleTable(
            dynamic=(DynamicRule("ZELLE FROM ", Income.DirectPay, pascal),),
        )
        assert table.match_rule("ZELLE FROM bob") == Match(
            kind="dynamic",
            key="ZELLE FROM ",
            account=Income.DirectPay.Bob,
        )

    def test_exact_beats_dynamic(self):
        table = RuleTable(
            exact={"ZELLE FROM bob": Income.Special},
            dynamic=(DynamicRule("ZELLE FROM ", Income.DirectPay, pascal),),
        )
        assert table.match("ZELLE FROM bob") == Income.Special

    def test_prefix_beats_dynamic(self):
        table = RuleTable(
            prefix={"ZELLE FROM bob": Income.Special},
            dynamic=(DynamicRule("ZELLE FROM ", Income.DirectPay, pascal),),
        )
        assert table.match("ZELLE FROM bob smith") == Income.Special

    def test_first_dynamic_wins(self):
        table = RuleTable(
            dynamic=(
                DynamicRule("ZELLE ", Income.A),
                DynamicRule("ZELLE FROM ", Income.B),
            ),
        )
        m = table.match_rule("ZELLE FROM bob")
        assert m is not None
        assert m.key == "ZELLE "

    def test_with_dynamic_appends(self):
        rule1 = DynamicRule("A ", Income.A)
        rule2 = DynamicRule("B ", Income.B)
        table = RuleTable().with_dynamic(rule1).with_dynamic(rule2)
        assert table.dynamic == (rule1, rule2)


class TestRuleTableValidateDynamic:
    def test_regular_prefix_shadows_dynamic(self):
        table = RuleTable(
            prefix={"ZELLE ": Income.A},
            dynamic=(DynamicRule("ZELLE FROM ", Income.DirectPay),),
        )
        issues = table.validate()
        assert any(
            "dynamic prefix 'ZELLE FROM '" in i and "unreachable" in i
            for i in issues
        )

    def test_dynamic_shadows_dynamic(self):
        table = RuleTable(
            dynamic=(
                DynamicRule("ZELLE ", Income.A),
                DynamicRule("ZELLE FROM ", Income.B),
            ),
        )
        issues = table.validate()
        assert any(
            "dynamic prefix 'ZELLE FROM '" in i and "unreachable" in i
            for i in issues
        )

    def test_clean_with_dynamic(self):
        table = RuleTable(
            exact={"FOO": Income.A},
            prefix={"BAR ": Income.B},
            dynamic=(DynamicRule("ZELLE FROM ", Income.DirectPay, pascal),),
        )
        assert table.validate() == []


class TestRuleTableMergeDynamic:
    def test_merge_concatenates_dynamic(self):
        rule1 = DynamicRule("A ", Income.A)
        rule2 = DynamicRule("B ", Income.B)
        a = RuleTable(dynamic=(rule1,))
        b = RuleTable(dynamic=(rule2,))
        assert RuleTable.merge(a, b).dynamic == (rule1, rule2)


class TestTrackerDynamic:
    def test_records_dynamic_hit(self):
        rule = DynamicRule("ZELLE FROM ", Income.DirectPay, pascal)
        tracker = RuleTable(dynamic=(rule,)).tracked()
        tracker.match("ZELLE FROM bob")
        assert tracker.unused() == []

    def test_unused_dynamic_reports_under(self):
        rule = DynamicRule("ZELLE FROM ", Income.DirectPay, pascal)
        tracker = RuleTable(dynamic=(rule,)).tracked()
        assert tracker.unused() == [
            Match(
                kind="dynamic",
                key="ZELLE FROM ",
                account=Income.DirectPay,
            ),
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

    def test_from_mapping_dynamic(self):
        table = RuleTable.from_mapping(
            {
                "dynamic": [
                    {
                        "prefix": "ZELLE FROM ",
                        "under": "Income:DirectPay",
                        "sanitize": "pascal",
                    },
                ],
            },
        )
        assert table.match("ZELLE FROM mary anne") == Income.DirectPay.MaryAnne

    def test_from_mapping_dynamic_default_sanitizer(self):
        table = RuleTable.from_mapping(
            {
                "dynamic": [
                    {"prefix": "X ", "under": "Income:A"},
                ],
            },
        )
        assert table.match("X foo") == Income.A.Foo

    def test_from_mapping_unknown_sanitizer(self):
        with pytest.raises(ValueError, match="unknown sanitizer 'snake'"):
            RuleTable.from_mapping(
                {
                    "dynamic": [
                        {
                            "prefix": "X ",
                            "under": "Income:A",
                            "sanitize": "snake",
                        },
                    ],
                },
            )
