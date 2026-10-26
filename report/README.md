# Static report destination

No measured held-out four-arm result is committed here. R03 public development
controls generated HTML through the keyless demo/eval entrypoints on a combined
candidate; see [validation](../docs/VALIDATION.md) for the evidence boundary.
Commands write a new HTML path explicitly chosen by the operator. Existing artifacts are never overwritten.
The report contains only whitelisted numeric aggregates and separately supplied
gold-gated development cards; loaded result publication fields are not trusted.
Raw held-out source, gold span tables and provider outputs must remain excluded.
If the whole-artifact scan of a locked edition finds a gold value in the assembled
JSON or HTML, both files are replaced by suppression documents (the single-report
path replaces only its HTML); if a suppression document would itself be unsafe,
nothing is written. Upstream measurements are unchanged either way.
Cell wording: `N/A (n/d)` (zero denominator; macro counts defined classes),
`insufficient` (in an Interval column: too few blocks or valid draws), `unknown` (unreconciled cost
status), `not measured` (no value available: never run, not reconciled or not computed).
The reviewed R03 source adds Interval-state cells to the harm-rate and paired
class/micro tables; these use fixed wording rather than arbitrary diagnostic text.
