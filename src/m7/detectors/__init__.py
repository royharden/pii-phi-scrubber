"""Permit-independent deterministic baseline and explicit adapter exports."""
from .regex import detect_regex
from .frontier import anchor_frontier
from .model import ModelPermit, TokenSpan, detect_model

__all__ = ['detect_regex', 'anchor_frontier', 'ModelPermit', 'TokenSpan', 'detect_model']
