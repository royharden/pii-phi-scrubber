"""Every public uncertainty row carries fixed state wording, including paired/harm rows."""

import re

import pytest

from m7.publish import render_report


@pytest.mark.parametrize("interval,state", [
    ({"interval": [0.1, 0.3], "null_reason": None}, "defined"),
    ({"interval": None, "null_reason": "insufficient_units"},
     "insufficient: fewer than 20 effective blocks"),
    ({"interval": None, "null_reason": "insufficient_valid_draws"},
     "insufficient: fewer than 1,800 valid draws"),
    ({}, "not measured"),
    ({"interval": None, "null_reason": "<script>source-value</script>"}, "not measured"),
])
def test_harm_and_paired_quality_rows_explain_interval_state(interval, state):
    # what_bug_this_catches: absent interval cells were ambiguous and paired
    # class/micro rows omitted the reason that prevented a scientific interval.
    intervals = {"residual_sensitive_codepoints": interval,
                 "per_class": {"NAME": {"recall": interval}}, "micro": {"f1": interval}}
    document = render_report({"schema_version": "EvaluationBundle/v2",
                              "arms": [{"arm": "regex", "intervals": intervals}],
                              "paired": {"total": intervals}})
    rows = re.findall(r"<tr>.*?</tr>", document)
    harm = [row for row in rows if
            "<th>regex</th><th>total</th><th>residual_sensitive_codepoints</th>" in row]
    paired = [row for row in rows if row.startswith("<tr><th>total</th><th>NAME</th><th>recall</th>")]
    assert harm and paired
    assert all(f"<td>{state}</td>" in row for row in (*harm, *paired))
    assert "source-value" not in document
