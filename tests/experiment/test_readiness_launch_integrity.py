"""Input custody and zero-effect checks at the malformed launch join."""

import copy
from unittest.mock import patch
import warnings

import pytest

from m7.experiment.authorization import EvaluationAuthorization, ReceiptAuthority
from m7.experiment.models import LockedEdition
from m7.experiment.readiness import assess_readiness

from .test_readiness_launch_diagnostics import (
    MARKER,
    assert_held,
    malformed_launch,
    public_bound_declarations,
)


@pytest.mark.parametrize("method", ("copy", "construct"))
def test_launch_refusal_preserves_caller_inputs_and_never_executes(method, capsys):
    # what_bug_this_catches: repairing a diagnostic boundary must not sanitize
    # the caller's object in place or accidentally activate the rejected bundle.
    lock, packet = public_bound_declarations()
    lock = LockedEdition.model_validate_json(lock.model_dump_json())
    packet = EvaluationAuthorization.model_validate_json(packet.model_dump_json())
    lock.require_current()
    ReceiptAuthority.validate_binding(packet, lock)
    launch = malformed_launch("memberships", method)
    before = (lock.model_dump_json(), packet.model_dump_json(), copy.deepcopy(launch.__dict__))
    with (
        warnings.catch_warnings(record=True) as emitted,
        patch("subprocess.Popen", side_effect=AssertionError("unexpected process")) as process,
        patch("socket.create_connection", side_effect=AssertionError("unexpected network")) as network,
        patch("builtins.open", side_effect=AssertionError("unexpected file")) as opened,
        patch("pathlib.Path.open", side_effect=AssertionError("unexpected path")) as path_opened,
    ):
        warnings.simplefilter("always")
        report = assess_readiness(edition=lock, authorization=packet, launch_bundle=launch)
    for effect in (process, network, opened, path_opened):
        effect.assert_not_called()
    assert before == (lock.model_dump_json(), packet.model_dump_json(), launch.__dict__)
    assert_held(report)
    assert next(row for row in report.checks if row.name == "preregistration").state == "shape_valid"
    assert next(row for row in report.checks if row.name == "campaign_binding").state == "invalid"
    assert MARKER not in report.model_dump_json()
    assert all(MARKER not in str(item.message) for item in emitted)
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out
