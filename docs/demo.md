# Offline two-minute journey

R03 public development controls have exercised the keyless CLI journey and generated
development HTML through the demo/eval entrypoints. The combined candidate also
passed local gate, suppression and report tests; see [validation](VALIDATION.md).
This is a synthetic development journey, not a measured four-arm experiment or a
timed two-minute rehearsal. Final main integration remains an INT decision.

The development path runs only the public fictional fixture. Its eight examples are
one development block. Regex is a deterministic baseline; frontier/base/fine remain
unmeasured unless actual separately authorized backends execute. The uncued-name
miss stays in upstream residual-leak metrics and its rendering is suppressed. Both
per-record and whole-document publication gates are required before writing HTML.

Future approved four-arm reports are replayed byte-for-byte, without network/model
calls, gold access or new artifact assembly:

```powershell
python scripts/demo.py --offline --approved-report path/to/approved/index.html `
  --report-sha256 <externally-recorded-approved-html-sha256> --out report/replay.html
```

The output filename must be new. Missing/mismatched hashes fail closed. This replay
command requires an independently approved report and its actual recorded hash;
R03 public development output does not supply a measured four-arm experiment.

Suggested rehearsal after actual safe results exist:

- 0:00-0:20: explain the fictional English/single-message/four-class boundary; show
  only the explicitly public development input, including a benign trace identifier.
- 0:20-0:50: view the saved four-arm accounting and safe development rendering; show
  a suppression card and explain that suppression does not improve detection scores.
- 0:50-1:20: compare unconditional per-class/micro/macro and normal/challenge quality,
  residual/overredaction/unavailable masks, paired uncertainty/undefined draws, controlled
  cold/warm timing and known cash versus unresolved/economic unknowns.
- 1:20-1:45: inspect the separately approved lineage, independent family/custody audit,
  actual training receipt and pre-test target/config lock. A template is not a receipt.
- 1:45-2:00: read the locked per-class and fine-minus-base/no-increased-leak gates,
  negative/no-deploy result and limitations. Even a passing candidate requires
  independent product acceptance; this is not a real privacy deployment.

Keep held-out raw messages, gold/prediction tables, prompts, completions and native
private journals out of the demo. The public report contains aggregates and value-free
failure counts only. Re-rendering an edition with changed code requires a new
gold-aware artifact validation; offline mode copies only the previously approved bytes.
