"""Gold-aware, fail-closed publication. This is not a general PII detector."""

from .gate import PublicationDecision, artifact_is_safe, gate_record
from .report import render_report, write_report
from .assembly import write_locked_artifacts

__all__ = ["PublicationDecision", "gate_record", "render_report", "write_report",
           "artifact_is_safe", "write_locked_artifacts"]
