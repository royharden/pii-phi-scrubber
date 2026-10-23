"""Assemble in memory, scan all public surfaces, then write a NEW artifact set."""
from __future__ import annotations

import json
from pathlib import Path

from m7.contracts import LogRecord, Span
from .gate import artifact_is_safe
from .report import render_report


def write_locked_artifacts(bundle: dict, destination: str | Path, *,
                            sources: tuple[tuple[LogRecord, tuple[Span, ...]], ...]) -> dict:
    from m7.experiment.result import public_aggregate
    safe = public_aggregate(bundle)
    result_text = json.dumps(safe, sort_keys=True, allow_nan=False, separators=(',', ':')) + '\n'
    report_text = render_report(safe)
    approved = artifact_is_safe(result_text + '\n' + report_text, sources)
    if not approved:
        # Do not change upstream measurements or publish the rejected document.
        result_text = json.dumps({'schema_version': 'ArtifactSuppressed/v1',
                                  'status': 'suppressed', 'reason': 'assembled_value_detected',
                                  'artifact_assembly_failures_N': 1}) + '\n'
        report_text = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                       '<title>Artifact suppressed</title><h1>Output suppressed</h1>'
                       '<p>Gold-aware artifact validation rejected this publication. '
                       'Original failures remain in the private evaluation journal.</p></html>')
        if not artifact_is_safe(result_text + '\n' + report_text, sources):
            raise ValueError('suppression_card_not_safe_to_publish')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / 'aggregate.json').open('x', encoding='utf-8') as handle:
        handle.write(result_text)
    with (destination / 'index.html').open('x', encoding='utf-8') as handle:
        handle.write(report_text)
    return {'status': 'published_safe_artifacts' if approved else 'artifacts_suppressed',
            'product_acceptance': False}


__all__ = ['write_locked_artifacts']
