"""Public development CLI journeys with independent output and refusal oracles.

No models, provider calls, sealed inputs or imported application gate are used.
"""

import hashlib
import json
import subprocess
import sys
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import pytest

import m7

ROOT = Path(m7.__file__).resolve().parents[2]
DEMO = ROOT / "scripts" / "demo.py"
FIXTURE = ROOT / "data-development" / "public-fictional.json"


class Tables(HTMLParser):
    """Read visible table cells rather than assert a serialized HTML template."""

    def __init__(self, document):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def demo(cwd, *args):
    return subprocess.run(
        [sys.executable, str(DEMO), "--offline", *map(str, args)],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


@pytest.fixture
def completed_demo(tmp_path):
    output = tmp_path / "report.html"
    result = demo(tmp_path, "--out", output)
    assert result.returncode == 0, result.stdout
    assert result.stderr == ""
    return result, output.read_text(encoding="utf-8")


def test_development_journey_retains_miss_and_unrun_arms(completed_demo):
    # Bug caught: publication suppression must not turn one NAME miss into a TP,
    # nor make unavailable model arms look measured. Counts derive from 8 public
    # records: 13 gold entities, 12 exact matches, 1 uncued NAME miss.
    result, document = completed_demo
    assert json.loads(result.stdout) == {
        "corpus_N": 8, "held_out_result": False,
        "status": "development_report_written", "suppressed_cards": 1,
    }
    rows = Tables(document).rows
    assert ["regex", "measured", "8", "8", "8", "8", "0", "0", "1"] in rows
    for arm in ("frontier", "base", "finetuned"):
        assert [arm, "not_measured", "8", "8", "0", "0", "0", "8", "0"] in rows
    micro = next(row for row in rows if row[:3] == ["regex", "total", "micro"])
    assert micro[6:] == ["12", "0", "1", "13"]
    assert float(micro[4]) == pytest.approx(12 / 13)
    assert document.count("<h3>Output suppressed</h3>") == 1
    assert document.count("<h3>Approved synthetic development rendering</h3>") == 7
    assert "insufficient: fewer than 20 effective blocks" in document


def test_publication_excludes_every_annotated_value(completed_demo):
    # Bug caught: checking just the known missed name would miss leaks in the
    # successful cards or encoded HTML. Oracle is the public fixture's gold,
    # independently scanned without calling the application's publication gate.
    result, document = completed_demo
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    surfaces = (document, unescape(document), result.stdout, result.stderr)
    for record in fixture["records"]:
        for span in fixture["gold"][record["record_id"]]:
            value = record["log"]["message"][span["start"]:span["end"]]
            for variant in (value, escape(value, quote=True), quote(value, safe="")):
                assert all(variant not in surface for surface in surfaces)
    # Non-target content and Unicode still survive the whole CLI path.
    assert "trace_id=REQ-401 latency=731 port=8080 service=North Star" in document
    assert "😀 é" in document
    assert 'literal &quot;quote&quot; and \\ path' in document


def test_existing_destination_is_never_replaced(tmp_path):
    # Bug caught: a repeat run must not overwrite a prior edition/report.
    output = tmp_path / "report.html"
    original = b"previous-edition-sentinel"
    output.write_bytes(original)
    result = demo(tmp_path, "--out", output)
    assert result.returncode == 2 and output.read_bytes() == original
    assert json.loads(result.stdout) == {
        "status": "error", "reason": "invalid_or_unavailable_input",
    }
    assert result.stderr == ""


@pytest.mark.parametrize("failure", ["wrong_hash", "missing_hash", "missing_report"])
def test_unapproved_replay_is_refused_without_output(tmp_path, failure):
    # Bug caught: hash/missing-input failures cannot publish unchecked bytes or
    # disclose the exception body/path through the CLI's machine-readable output.
    source = tmp_path / "unapproved-sentinel.html"
    source.write_text("UNAPPROVED-PUBLIC-FIXTURE-SENTINEL", encoding="utf-8")
    output = tmp_path / "out.html"
    args = ["--out", output, "--approved-report", source]
    if failure != "missing_hash":
        args += ["--report-sha256", "0" * 64]
    if failure == "missing_report":
        args[3] = tmp_path / "missing-sentinel.html"
    result = demo(tmp_path, *args)
    assert result.returncode == 2 and not output.exists()
    assert json.loads(result.stdout) == {
        "status": "error", "reason": "invalid_or_unavailable_input",
    }
    assert result.stderr == "" and "sentinel" not in result.stdout.lower()


def test_approved_offline_replay_is_byte_exact(tmp_path, completed_demo):
    # Bug caught: a replay must copy the reviewed artifact, never regenerate a
    # different gold-free report or rerun an experiment.
    _, document = completed_demo
    source = tmp_path / "approved.html"
    raw = document.encode("utf-8")
    source.write_bytes(raw)
    output = tmp_path / "replay.html"
    result = demo(tmp_path, "--out", output, "--approved-report", source,
                  "--report-sha256", hashlib.sha256(raw).hexdigest())
    assert result.returncode == 0 and output.read_bytes() == raw
    assert json.loads(result.stdout) == {
        "status": "offline_approved_aggregate_rendered",
        "held_out_rerun": False, "product_acceptance": False,
    }
    assert result.stderr == ""
