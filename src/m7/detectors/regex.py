"""Narrow documented English context rules; no gold or lexicon lookup."""
import re

from m7.contracts import LogRecord, Prediction, Span

PLACEHOLDER = re.compile(r'\[(?:NAME|EMAIL|PHONE|ACCOUNT_ID|REDACTED)_\d+\]')
EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?![\w-])(?!\.[\w-])')
ACCOUNT = re.compile(r'\b(?:account(?:_id)?|customer(?:_id)?|user_id)\s*[:=#]\s*(?P<value>[A-Za-z0-9][A-Za-z0-9_-]{2,63})\b', re.IGNORECASE)
NAME = re.compile(r'\b(?:person|name|user)\s*[:=]\s*(?P<value>[A-Z][a-z]+(?:-[A-Z][a-z]+)? (?:[A-Z]\. )?[A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b')
PHONE = re.compile(r'\b(?:phone|tel|mobile)\s*[:=]\s*(?P<value>(?:\+[1-9]\d{6,14}|(?:\+1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4})(?:\s*(?:ext\.?|x)\s*\d{1,6})?)(?!\d)', re.IGNORECASE)


def detect_regex(record: LogRecord, run_id: str = 'development') -> Prediction:
    message = record.log.message
    protected = [m.span() for m in PLACEHOLDER.finditer(message)]
    spans = []
    emails = [m.span() for m in EMAIL.finditer(message)]
    for label, pattern, group in [('EMAIL', EMAIL, 0), ('ACCOUNT_ID', ACCOUNT, 'value'), ('NAME', NAME, 'value'), ('PHONE', PHONE, 'value')]:
        for match in pattern.finditer(message):
            start, end = match.span(group)
            if any(start < b and a < end for a, b in protected):
                continue
            if label != 'EMAIL' and any(start < b and a < end for a, b in emails):
                continue
            spans.append(Span(start=start, end=end, label=label))
    return Prediction(run_id=run_id, record_id=record.record_id, content_sha256=record.content_sha256, arm='regex', model_id='context-regex-v1', attempt_id='attempt-1', status='ok', spans=tuple(spans))
