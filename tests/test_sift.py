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
    assert list(run(rows(), Query(aggregates=[parse_aggregate("sum(price)")]))) == [
        {"sum(price)": 517.0}
    ]
    assert list(run(rows(), Query(aggregates=[parse_aggregate("count()")]))) == [{"count(*)": 4}]


def test_aggregate_skips_blanks_and_text():
    data = [{"v": "10"}, {"v": ""}, {"v": "n/a"}, {"v": "20"}]
    assert list(run(data, Query(aggregates=[parse_aggregate("avg(v)")]))) == [{"avg(v)": 15.0}]


def test_group_by():
    q = Query(aggregates=[parse_aggregate("sum(price)")], group_by=["category"])
    out = list(run(rows(), q))
    assert {r["category"]: r["sum(price)"] for r in out} == {"tools": 260.0, "outdoor": 257.0}


def test_aggregate_applies_after_filtering():
    q = Query(where=[parse_condition("price < 100")], aggregates=[parse_aggregate("count()")])
    assert list(run(rows(), q)) == [{"count(*)": 2}]


def test_bad_aggregate_is_explained():
    with pytest.raises(QueryError, match="unknown function"):
        parse_aggregate("stddev(price)")
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
    assert [json.loads(line) for line in out.getvalue().splitlines()] == [{"a": 1}, {"a": 2}]


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


# --- percentiles, median, distinct, and several aggregates at once -----------


def test_percentile_matches_the_common_definition():
    # The linear-interpolation percentile numpy, pandas and Excel all default
    # to. These values are what those tools return for the same input, which is
    # the whole reason for choosing it.
    data = [{"v": v} for v in (10, 20, 30, 40)]
    assert list(run(data, Query(aggregates=[parse_aggregate("p95(v)")]))) == [
        {"p95(v)": 38.5}
    ]

    assert list(run(data, Query(aggregates=[parse_aggregate("p0(v)")]))) == [{"p0(v)": 10.0}]
    assert list(run(data, Query(aggregates=[parse_aggregate("p100(v)")]))) == [{"p100(v)": 40.0}]


def test_median_is_p50():
    even = [{"v": v} for v in (10, 20, 30, 40)]
    assert list(run(even, Query(aggregates=[parse_aggregate("median(v)")]))) == [
        {"median(v)": 25.0}
    ]
    odd = [{"v": v} for v in (10, 20, 30)]
    assert list(run(odd, Query(aggregates=[parse_aggregate("median(v)")]))) == [
        {"median(v)": 20.0}
    ]


def test_percentile_of_nothing_is_none():
    empty = [{"v": ""}, {"v": "text"}]
    assert list(run(empty, Query(aggregates=[parse_aggregate("p95(v)")]))) == [{"p95(v)": None}]


def test_distinct_counts_spellings_not_values():
    # "1" and "1.0" are two entries in the file. Collapsing them would be a
    # claim about the data that sift is not in a position to make.
    data = [{"v": "1"}, {"v": "1.0"}, {"v": "1"}]
    assert list(run(data, Query(aggregates=[parse_aggregate("distinct(v)")]))) == [
        {"distinct(v)": 2}
    ]


def test_several_aggregates_in_one_pass():
    out = list(
        run(
            rows(),
            Query(aggregates=[parse_aggregate("count()"), parse_aggregate("avg(price)")]),
        )
    )
    assert len(out) == 1
    assert out[0]["count(*)"] == 4
    assert "avg(price)" in out[0]


def test_group_by_several_columns():
    data = [
        {"a": "x", "b": "p", "v": 1},
        {"a": "x", "b": "p", "v": 2},
        {"a": "x", "b": "q", "v": 4},
    ]
    out = list(
        run(
            data,
            Query(aggregates=[parse_aggregate("sum(v)"), parse_aggregate("count()")],
                  group_by=["a", "b"]),
        )
    )
    assert out == [
        {"a": "x", "b": "p", "sum(v)": 3.0, "count(*)": 2},
        {"a": "x", "b": "q", "sum(v)": 4.0, "count(*)": 1},
    ]


def test_percentile_above_one_hundred_is_rejected():
    with pytest.raises(QueryError):
        parse_aggregate("p150(v)")


def test_fractional_percentile():
    # A percentile need not be an integer; p99.9 is a common latency ask.
    data = [{"v": v} for v in range(1, 101)]  # 1..100
    out = list(run(data, Query(aggregates=[parse_aggregate("p99.9(v)")])))
    assert out[0]["p99.9(v)"] == pytest.approx(99.901)


# ── negated regex (!~) ───────────────────────────────────────────────────────
def test_negated_regex_keeps_non_matches():
    data = [{"name": "apple"}, {"name": "banana"}, {"name": "avocado"}]
    out = list(run(data, Query(where=[parse_condition("name !~ ^a")])))
    assert [r["name"] for r in out] == ["banana"]


def test_negated_regex_is_the_complement_of_match():
    data = rows()
    match = {r["name"] for r in run(data, Query(where=[parse_condition("name ~ o")]))}
    nomatch = {r["name"] for r in run(rows(), Query(where=[parse_condition("name !~ o")]))}
    assert match.isdisjoint(nomatch)
    assert match | nomatch == {r["name"] for r in rows()}


def test_negated_regex_operand_is_not_coerced():
    # The pattern side of ~ and !~ is always text, never a number.
    c = parse_condition("v !~ 10")
    assert c.op == "!~"
    assert c.value == "10"


# ── mixed-type sort no longer drops rows (regression) ────────────────────────
def test_mixed_type_sort_after_filter_keeps_every_row():
    # A --sort on a column with both numbers and text falls back to sorting as
    # text. When the rows arrive as a generator (any query with --where), that
    # fallback must not re-read an already-consumed stream and yield nothing.
    data = [{"v": v, "k": "1"} for v in ("abc", "5", "def", "9", "ghi")]
    q = Query(where=[parse_condition("k = 1")], sort_by="v")
    out = list(run(data, q))
    assert len(out) == len(data)
    assert [r["v"] for r in out] == ["5", "9", "abc", "def", "ghi"]


def test_sort_puts_missing_values_last():
    data = [{"v": 3}, {"v": None}, {"v": 1}]
    out = list(run(data, Query(sort_by="v")))
    assert [r["v"] for r in out] == [1, 3, None]


# ── formats and conversion ───────────────────────────────────────────────────
def test_json_array_round_trips_to_jsonl():
    src = '[{"a": 1}, {"a": 2}]'
    out = _io.StringIO()
    n = write(read(_io.StringIO(src), "json"), out, "jsonl")
    assert n == 2
    assert [json.loads(line) for line in out.getvalue().splitlines()] == [{"a": 1}, {"a": 2}]


def test_json_output_is_a_single_array():
    out = _io.StringIO()
    write(read(_io.StringIO('{"a": 1}\n{"a": 2}\n'), "jsonl"), out, "json")
    assert json.loads(out.getvalue()) == [{"a": 1}, {"a": 2}]


def test_json_array_must_be_a_list():
    with pytest.raises(ValueError, match="array of objects"):
        list(read(_io.StringIO('{"a": 1}'), "json"))


def test_json_array_items_must_be_objects():
    with pytest.raises(ValueError, match="item 1"):
        list(read(_io.StringIO('[{"a": 1}, 2]'), "json"))


def test_ndjson_reads_like_jsonl():
    out = list(read(_io.StringIO('{"a": 1}\n{"a": 2}\n'), "ndjson"))
    assert out == [{"a": 1}, {"a": 2}]


def test_sniff_prefers_explicit_over_extension():
    from sift.io import sniff

    assert sniff("data.csv", None) == "csv"
    assert sniff("data.jsonl", None) == "jsonl"
    assert sniff("data.ndjson", None) == "jsonl"
    assert sniff("data.json", None) == "json"
    assert sniff(None, None) == "csv"
    assert sniff("data.csv", "jsonl") == "jsonl"


def test_cli_converts_csv_to_jsonl(tmp_path, capsys):
    f = tmp_path / "d.csv"
    f.write_text(CSV, encoding="utf-8")
    assert main([str(f), "--to", "jsonl", "--select", "name,price"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0]) == {"name": "widget", "price": "10"}


# ── bounded top-N for --sort --limit ─────────────────────────────────────────
def _spread(n):
    # Unsorted, with deliberate ties, so tie-breaking order is exercised.
    return [{"v": (i * 7919) % 1000, "i": i} for i in range(n)]


@pytest.mark.parametrize("desc", [False, True])
@pytest.mark.parametrize("n", [1, 3, 25, 500, 5000])
def test_top_n_matches_a_full_sort_then_slice(desc, n):
    data = _spread(2000)
    bounded = list(run(iter(data), Query(sort_by="v", descending=desc, limit=n)))
    full = list(run(iter(data), Query(sort_by="v", descending=desc)))[:n]
    assert bounded == full


def test_top_n_on_a_mixed_column_matches_the_full_sort():
    data = [{"v": v} for v in ("abc", "5", None, "10", "def", "9", "")]
    for desc in (False, True):
        bounded = list(run(iter(data), Query(sort_by="v", descending=desc, limit=4)))
        full = list(run(iter(data), Query(sort_by="v", descending=desc)))[:4]
        assert bounded == full


def test_top_n_does_not_buffer_the_input():
    import tracemalloc

    def peak(q):
        data = _spread(200_000)  # built outside the measurement window
        tracemalloc.start()
        list(run(iter(data), q))
        _, p = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return p

    bounded = peak(Query(sort_by="v", limit=10))
    full = peak(Query(sort_by="v"))
    # The real margin is orders of magnitude; 50x cannot trip on allocator noise.
    assert full > bounded * 50, f"bounded={bounded} full={full}"


def test_top_n_reports_a_missing_sort_column():
    with pytest.raises(QueryError, match="no such column"):
        list(run(iter(rows()), Query(sort_by="nope", limit=3)))


def test_sort_with_limit_zero_yields_nothing():
    assert list(run(iter(rows()), Query(sort_by="price", limit=0))) == []


def test_numbers_sort_before_text_in_a_mixed_column():
    data = [{"v": v} for v in ("n/a", "10", None, "9", "abc")]
    out = [r["v"] for r in run(iter(data), Query(sort_by="v"))]
    assert out == ["9", "10", "abc", "n/a", None]


# ── real-world input: BOMs, encodings, oversized fields ──────────────────────
def test_an_excel_byte_order_mark_does_not_rename_the_first_column(tmp_path):
    f = tmp_path / "excel.csv"
    f.write_bytes("name,price\r\nwidget,10\r\n".encode("utf-8-sig"))
    assert main([str(f), "--where", "name = widget"]) == 0


def test_a_non_utf8_file_says_which_flag_fixes_it(tmp_path, capsys):
    f = tmp_path / "latin.csv"
    f.write_bytes("name,price\r\ncaf\xe9,10\r\n".encode("cp1252"))
    assert main([str(f)]) == 1
    err = capsys.readouterr().err
    assert "--encoding" in err
    assert str(f) in err


def test_the_encoding_flag_reads_the_file(tmp_path, capsys):
    f = tmp_path / "latin.csv"
    f.write_bytes("name,price\r\ncaf\xe9,10\r\n".encode("cp1252"))
    assert main([str(f), "--encoding", "cp1252"]) == 0
    assert "caf\xe9" in capsys.readouterr().out


def test_an_unknown_encoding_is_a_query_error_not_a_traceback(tmp_path, capsys):
    f = tmp_path / "a.csv"
    f.write_text("a\n1\n")
    assert main([str(f), "--encoding", "no-such-codec"]) == 2
    assert "unknown encoding" in capsys.readouterr().err


def test_a_field_larger_than_the_csv_default_limit_is_read(tmp_path):
    f = tmp_path / "big.csv"
    f.write_text("a,b\n" + "x" * 200_000 + ",2\n", newline="")
    assert main([str(f), "--select", "b"]) == 0


def test_a_csv_error_becomes_a_message_with_a_line_number():
    # Squeezing the field limit is the cheapest way to provoke a _csv.Error.
    import csv as _csv

    previous = _csv.field_size_limit(10)
    try:
        src = _io.StringIO("a,b\n" + "x" * 50 + ",2\n")
        with pytest.raises(ValueError, match="line 2"):
            list(read(src, "csv"))
    finally:
        _csv.field_size_limit(previous)


def test_the_raised_field_limit_is_still_a_limit():
    import csv as _csv

    from sift.io import MAX_FIELD_SIZE

    assert _csv.field_size_limit() == MAX_FIELD_SIZE
    assert MAX_FIELD_SIZE < 2**31 - 1


def test_embedded_newlines_and_quotes_survive_a_round_trip():
    src = 'name,note\n"a,b","line one\nline two"\n"q","say ""hi"""\n'
    got = list(read(_io.StringIO(src), "csv"))
    assert got[0]["name"] == "a,b"
    assert got[0]["note"] == "line one\nline two"
    assert got[1]["note"] == 'say "hi"'
    out = _io.StringIO()
    write(iter(got), out, "csv")
    assert list(read(_io.StringIO(out.getvalue()), "csv")) == got


def test_an_empty_file_is_no_rows_not_an_error(tmp_path, capsys):
    f = tmp_path / "empty.csv"
    f.write_text("")
    assert main([str(f)]) == 0
    assert capsys.readouterr().out == ""


def test_a_header_with_no_rows_is_no_rows_not_an_error(tmp_path, capsys):
    f = tmp_path / "headeronly.csv"
    f.write_text("a,b\n")
    assert main([str(f), "--where", "a > 1"]) == 0
    assert capsys.readouterr().out == ""
