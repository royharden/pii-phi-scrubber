"""Hand-built OperatorHost must be rejected before selection/custody data reads."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import m7
from m7.data.access import IsolationGuard
from m7.data.filesystem import CustodyFilesystem
from m7.experiment.activation import OperatorHost


@pytest.mark.parametrize("missing", ["verify_receipt", "isolation_guard", "custody_filesystem"])
def test_missing_mandatory_host_control_precedes_additional_reads(monkeypatch, capsys, missing):
    # Bug caught: dataclass isinstance alone accepts None mandatory controls,
    # allowing locked evaluator to read more inputs before it refuses the host.
    scripts = Path(m7.__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("m7_review_eval_cli", scripts / "eval.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    fields = dict(verify_receipt=lambda *_: True, registry_factory=lambda: {}, cost_summary=lambda: {},
                  custody_filesystem=object.__new__(CustodyFilesystem),
                  isolation_guard=object.__new__(IsolationGuard))
    fields[missing] = None
    host = OperatorHost(**fields)
    reads = []

    def bounded_load(path, schema):
        reads.append(path)
        assert path in ("lock", "authorization"), "read before rejecting missing host control"
        return object()

    monkeypatch.setattr(cli, "load_boundary", bounded_load)
    monkeypatch.setattr(cli.importlib, "import_module", lambda _: SimpleNamespace(factory=lambda _: host))
    args = SimpleNamespace(**{key: key for key in (
        "lock", "authorization", "selection_lock", "targets", "custody_bundle", "custody_lifecycle", "journal", "out",
    )}, operator_host="reviewed_host:factory", run_timing=False)
    assert cli.execute_locked(args) == 3
    assert json.loads(capsys.readouterr().out) == {
        "status": "unavailable", "reason": "authenticated_operator_host_unavailable",
        "product_acceptance": False,
    }
    assert reads == ["lock", "authorization"]
