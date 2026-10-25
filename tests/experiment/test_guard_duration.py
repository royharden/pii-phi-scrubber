"""Pre-dispatch failure keeps the parent's measured duration on both wires."""

from types import SimpleNamespace

import pytest

from m7.contracts import make_record
from m7.experiment.isolated import _WorkerAdapter
from m7.providers.contracts import AdapterFault


@pytest.mark.parametrize("code", ("permit_required", "cancelled", "unavailable", "truncated"))
def test_guard_failure_prediction_and_event_share_measured_duration(monkeypatch, code):
    # what_bug_this_catches: parent guard AttemptEvent had measured time, but its
    # terminal Prediction silently lost it, undercounting failed-attempt latency.
    adapter = _WorkerAdapter(
        SimpleNamespace(run_id="public-duration"), None, None,
        SimpleNamespace(arm="regex", model_id="public-fake"), None, lambda: None,
    )
    def reject():
        raise AdapterFault(code)
    monkeypatch.setattr(adapter, "_guard", reject)
    ticks = iter((10.0, 10.125))
    monkeypatch.setattr("m7.experiment.isolated.perf_counter", lambda: next(ticks))
    prediction = adapter.predict(make_record("public diagnostic", "public-duration"))
    metadata = adapter.metadata()
    assert prediction.duration_ms == 125.0
    assert metadata[0]["duration_ms"] == prediction.duration_ms
    assert metadata[0]["physical_may_have_started"] is False
    assert metadata[0]["reservation_micros"] is None
    assert prediction.error_code == code
