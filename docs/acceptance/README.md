# W8 acceptance preparation

Current disposition: **NOT_READY**. This is an evidence inventory and staffing
protocol, not an independent acceptance verdict. The W2 product packet consumes
the canonical `ExperimentReadiness/v1` assessment from `m7.experiment.readiness`;
it does not make a second readiness decision or issue permission to run anything.
Readiness facts describe available evidence; they cannot authenticate approvals.
Mock or structurally valid receipts never establish actual execution.

After the D11 producer and D8 consumer are integrated, prepare a new offline
packet from the missing-input assessment with the local environment:

```powershell
.\.venv\Scripts\python.exe -c "from m7.experiment.readiness import assess_readiness; from m7.publish.acceptance import write_acceptance_packet; write_acceptance_packet(assess_readiness(), 'report/readiness-W2-01.html')"
```

Use a new filename each time. The writer validates canonical input before opening
the new file exclusively. It renders only closed enum names/states/reasons and
numeric counts; source text, paths, prompt/completion bodies and producer exception
messages are excluded. Invalid or contradictory input fails closed. It never
opens a model, host, sealed corpus or provider connection. Missing population and
cost facts remain unavailable rather than zero; supplied counts/amounts remain
labelled readiness/mock evidence. Actual scientific arms are `NOT_MEASURED`.

`render_acceptance_packet(readiness)` also accepts the canonical model's JSON
dictionary, using `ExperimentReadiness.model_validate_json` as the only schema
authority. No readiness or authorization rules are reimplemented here. The packet
is generated preparation evidence; a future appointed reviewer must still inspect
the exact referenced artifacts rather than accept the page as proof.

## Evidence inventory for a future appointed reviewer

| Requirement | Evidence needed before W8 review | Current evidence boundary |
|---|---|---|
| M7-01: exact spans and safe logs | Original Unicode wire contract, independent metric/render counterexamples, suppression that preserves failures, inspected safe artifacts | Local fictional tests and demo exist; no claim about arbitrary real text |
| M7-02: real small-model training | Exact approved weights/tokenizer/terms, train/dev hashes, config/seed/environment, executed receipt, selected checkpoint hash, failed-trial ledger | Actual acquisition and training are held by H1/H2; no trained artifact supplied |
| M7-03: four arms and independent test families | Fresh custodian, separately audited labels/ancestry, at least 20 effective independent test blocks, fixed input denominator, base/fine parity and pre-test lock | H3 frontier and H4 sealed custody remain held; public examples are development only |
| M7-04: quality, uncertainty, timing and cost | Four real arms, exact class/micro/macro results, residual/benign masks, paired-block intervals, three-pass timing, complete cash/liability/economic evidence | Mock arithmetic and local SQLite tests are engineering evidence; real model results, invoices and economic totals are not supplied |
| M7-05: model card and safe demo | Accurate limitations, actual lineage, negative outcomes, gold-aware artifact approval and clean-environment two-minute walkthrough | Repeatable public-fictional CLI output exists; full four-arm walkthrough and human timed rehearsal remain open |
| W8 independence | Named nonauthoring reviewer, declared lineage/role overlaps, approved evidence access and independent written verdict | H6 holds formal acceptance; this team prepares the packet only |

See [validation](../VALIDATION.md), [limits](../LIMITATIONS.md),
[model card](../model-card.md) and [offline walkthrough](../demo.md). The current
run's holds are maintained by INT, not by this document. Packet consumers must use
the canonical assessment rather than treating this static inventory as live authority.

## H6 staffing and admission prerequisites

1. Roy/INT must explicitly appoint a final reviewer after actual scientific/model
   prerequisites exist. This authoring seat cannot certify its own packet, source,
   evidence, tests or metric expectations. A different label is not independence.
2. A fresh custodian must be blind to development failures and training variants.
   Existing W2 seats have seen these and must not construct/seal the held-out test
   as if blind. A separate nonauthor must audit generator/guide/label/provenance
   work; the custodian cannot certify their own labels or ancestry.
3. If a nonimplementation custodian also performs final acceptance, disclose the
   overlap and retain the separate audit of their custody/label/provenance work.
   If that auditor is unavailable, the corresponding gate remains open.
4. Appoint roles, exact evidence hashes, access boundaries and target platform
   before sharing controlled artifacts. The present packet exposes no sealed
   input/gold, private journal, prompt, completion, credential or source-value hash.
5. Independent product review must inspect licenses, split/audit lineage, actual
   training and four-arm receipts, metric counterexamples, budget reconciliation,
   failure cases and the clean offline walkthrough. A positive metric can remain
   a no-deploy result; a full suite or shape-valid manifest is insufficient.
6. Record a scoped, independently authored verdict with unresolved gaps and exact
   candidate/evidence bindings. Only the appointed reviewer supplies that verdict;
   the product packet never sets `product_acceptance=true`.

## H1–H6 handoff

H1 acquisition/rights, H2 actual local training, H3 frontier service, H4 sealed
custody/audit, H5 native trusted-host qualification and H6 independent acceptance
remain held at this W2 checkpoint. Preparing manifests, mocks, audit criteria or
this packet does not release any hold. Missing provider results remain
**NOT_MEASURED**; overall readiness remains **NOT_READY**. No charts imply four
measured arms, no mock metric implies model quality, and no privacy certification
is issued. Request concrete authorization through INT before any held operation.
