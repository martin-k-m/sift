import io as _io
import json

import pytest

from sift.cli import main
from sift.io import read, write
from sift.query import Query, QueryError, coerce, parse_aggregate, parse_condition, run

CSV = "name,price,category\nwidget,10,tools\ngadget,250,tools\nrope,7,outdoor\ntent,250,outdoor\n"


def rows():
    return list(read(_io.StringIO(CSV), "csv"))


# ── coercion ────────────────────────────────────────────────────────────────
def test_numbers_are_read_as_numbers():
    assert coerce("10") == 10
    assert coerce("1.5") == 1.5
    assert coerce("-3") == -3


def test_leading_zeros_stay_text():
    # An identifier like 007 must survive the round trip; turning it into 7
    # loses exactly the thing that made it a key.
    assert coerce("007") == "007"
    assert coerce("0") == 0  # a bare zero is still a number


def test_text_is_left_alone():
    assert coerce("widget") == "widget"
    assert coerce("") == ""


# ── filtering ───────────────────────────────────────────────────────────────
def test_numeric_comparison_is_not_string_comparison():
    out = list(run(rows(), Query(where=[parse_condition("price > 100")])))
    assert {r["name"] for r in out} == {"gadget", "tent"}


def test_conditions_combine():
    q = Query(where=[parse_condition("price > 100"), parse_condition("category = outdoor")])
    assert [r["name"] for r in run(rows(), q)] == ["tent"]


def test_regex_match():
    out = list(run(rows(), Query(where=[parse_condition("name ~ ^t")])))
    assert [r["name"] for r in out] == ["tent"]


def test_mixed_types_filter_rather_than_crash():
    data = [{"v": "5"}, {"v": "abc"}, {"v": "9"}]
    out = list(run(data, Query(where=[parse_condition("v > 6")])))
    assert [r["v"] for r in out] == ["9"]


def test_unknown_column_names_the_columns_it_has():
    with pytest.raises(QueryError, match="no column 'nope'"):
        list(run(rows(), Query(where=[parse_condition("nope = 1")])))


# ── projection, sorting, limit ──────────────────────────────────────────────
def test_select_keeps_order_asked_for():
    out = list(run(rows(), Query(select=["price", "name"])))
    assert list(out[0]) == ["price", "name"]


def test_sort_is_numeric():
    out = list(run(rows(), Query(sort_by="price")))
    assert [r["name"] for r in out] == ["rope", "widget", "gadget", "tent"]


def test_sort_descending():
    out = list(run(rows(), Query(sort_by="price", descending=True)))
    assert out[0]["name"] in {"gadget", "tent"}


def test_limit_stops_early():
    consumed = []

    def counting():
        for r in rows():
            consumed.append(r)
            yield r

    out = list(run(counting(), Query(limit=2)))
    assert len(out) == 2
    # Streaming means the third row is never read, not read and discarded.
    assert len(consumed) == 2


def test_limit_zero_is_empty():
    assert list(run(rows(), Query(limit=0))) == []


# ── aggregation ─────────────────────────────────────────────────────────────
def test_sum_and_avg():
    assert list(run(rows(), Query(aggregate=parse_aggregate("sum(price)")))) == [
        {"sum(price)": 517.0}
    ]
    assert list(run(rows(), Query(aggregate=parse_aggregate("count()")))) == [{"count(*)": 4}]


def test_aggregate_skips_blanks_and_text():
    data = [{"v": "10"}, {"v": ""}, {"v": "n/a"}, {"v": "20"}]
    assert list(run(data, Query(aggregate=parse_aggregate("avg(v)")))) == [{"avg(v)": 15.0}]


def test_group_by():
    out = list(run(rows(), Query(aggregate=parse_aggregate("sum(price)"), group_by="category")))
    assert {r["category"]: r["sum(price)"] for r in out} == {"tools": 260.0, "outdoor": 257.0}


def test_aggregate_applies_after_filtering():
    q = Query(where=[parse_condition("price < 100")], aggregate=parse_aggregate("count()"))
    assert list(run(rows(), q)) == [{"count(*)": 2}]


def test_bad_aggregate_is_explained():
    with pytest.raises(QueryError, match="unknown function"):
        parse_aggregate("median(price)")
    with pytest.raises(QueryError, match=r"sum\(price\)"):
        parse_aggregate("not a call")


def test_condition_without_operator_is_explained():
    with pytest.raises(QueryError, match="no comparison"):
        parse_condition("price")


# ── round trips ─────────────────────────────────────────────────────────────
def test_jsonl_round_trip():
    src = '{"a": 1}\n\n{"a": 2}\n'
    out = _io.StringIO()
    n = write(read(_io.StringIO(src), "jsonl"), out, "jsonl")
    assert n == 2  # the blank line is skipped, not an error
    assert [json.loads(l) for l in out.getvalue().splitlines()] == [{"a": 1}, {"a": 2}]


def test_csv_header_follows_the_projection():
    out = _io.StringIO()
    write(run(rows(), Query(select=["name"])), out, "csv")
    assert out.getvalue().splitlines()[0] == "name"


def test_empty_result_writes_nothing():
    out = _io.StringIO()
    assert write(run(rows(), Query(where=[parse_condition("price > 9999")])), out, "csv") == 0
    assert out.getvalue() == ""


def test_malformed_jsonl_names_the_line():
    with pytest.raises(ValueError, match="line 2"):
        list(read(_io.StringIO('{"a":1}\nnot json\n'), "jsonl"))


# ── the CLI ─────────────────────────────────────────────────────────────────
def test_cli_end_to_end(tmp_path, capsys):
    f = tmp_path / "d.csv"
    f.write_text(CSV, encoding="utf-8")
    assert main([str(f), "--where", "price > 100", "--select", "name", "--sort", "name"]) == 0
    assert capsys.readouterr().out.splitlines() == ["name", "gadget", "tent"]


def test_cli_reports_a_bad_query_without_a_traceback(tmp_path, capsys):
    f = tmp_path / "d.csv"
    f.write_text(CSV, encoding="utf-8")
    assert main([str(f), "--where", "price"]) == 2
    assert "no comparison" in capsys.readouterr().err


def test_cli_rejects_group_by_without_agg(tmp_path, capsys):
    f = tmp_path / "d.csv"
    f.write_text(CSV, encoding="utf-8")
    assert main([str(f), "--group-by", "category"]) == 2
    assert "needs --agg" in capsys.readouterr().err


def test_cli_missing_file_is_a_message_not_a_stack(capsys):
    assert main(["definitely-not-here.csv"]) == 1
    assert "definitely-not-here.csv" in capsys.readouterr().err
