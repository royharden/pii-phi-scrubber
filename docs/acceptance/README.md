# W8 acceptance preparation

Current disposition: **NOT_READY**. This is an evidence inventory and staffing
protocol, not an independent acceptance verdict. The W2 product packet consumes
the canonical `ExperimentReadiness/v1` assessment from `m7.experiment.readiness`;
it does not make a second readiness decision or issue permission to run anything.
Readiness facts describe available evidence; they cannot authenticate approvals.
Mock or structurally valid receipts never establish actual execution.

At the 2026-10-26 host checkpoint, INT's staged tree
`27f5c33975600bff0b55981c62d8d8f1f88356b8` passed the full combined 687-test
local gate (505 accepted-baseline + 84 RV1 + 98 RV2), root Ruff and eight host
public-development controls. W2 source is not yet installed on main, and a fresh
Docker check is pending. This is local fictional/mock/readiness validation, not
actual-model, scientific or formal W8 acceptance; see [validation](../VALIDATION.md).

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
| M7-02: real small-model training | Exact approved weights/tokenizer/terms, train/dev hashes, config/seed/environment, executed receipt, selected checkpoint hash, failed-trial ledger | H1 permits metadata lookups only; actual artifact downloads and H2 actual training remain restricted, with no trained artifact supplied |
| M7-03: four arms and independent test families | Fresh custodian, separately audited labels/ancestry, at least 20 effective independent test blocks, fixed input denominator, base/fine parity and pre-test lock | H3 frontier and H4 sealed custody remain held; public examples are development only |
| M7-04: quality, uncertainty, timing and cost | Four real arms, exact class/micro/macro results, residual/benign masks, paired-block intervals, three-pass timing, complete cash/liability/economic evidence | Mock arithmetic and local SQLite tests are engineering evidence; real model results, invoices and economic totals are not supplied |
| M7-05: model card and safe demo | Accurate limitations, actual lineage, negative outcomes, gold-aware artifact approval and clean-environment two-minute walkthrough | Repeatable public-fictional CLI output exists; full four-arm walkthrough and human timed rehearsal remain open |
| W8 independence | Named nonauthoring reviewer, declared lineage/role overlaps, approved evidence access and independent written verdict | H6 permits NOT_READY preparation only; no final acceptance reviewer is appointed |

See [validation](../VALIDATION.md), [limits](../LIMITATIONS.md),
[model card](../model-card.md) and [offline walkthrough](../demo.md). The current
run's holds are maintained by INT, not by this document. Packet consumers must use
the canonical assessment rather than treating this static inventory as live authority.

## H6 staffing and admission prerequisites

1. A separately authorized final reviewer must be appointed after actual
   scientific/model prerequisites exist. No such reviewer is currently appointed.
   This authoring seat cannot certify its own packet, source,
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

Effie's delegated decision of 2026-10-25, rather than Roy's personal signature,
permits H1 public no-login, read-only metadata/licence/terms lookups with source
URL and retrieval time recorded. This narrow operation permission does not satisfy
the canonical H1 artifact-evidence prerequisite: model/weight/backbone/tokenizer
downloads remain restricted, actual models are absent, and exact immutable
revision/hash/licence/total-size-cap approval is still required before acquisition.

H2 actual local training/evaluation, H3 live frontier calls and key provisioning,
H4 new custody/auditor seats, separated storage and sealing/opening, H5 real native
host/service qualification and H6 formal acceptance remain restricted. H6 permits
NOT_READY packet preparation; it does not appoint a final reviewer or certify a
product. Preparing manifests, mocks, audit criteria or this packet supplies no
missing approval or actual-model evidence. Missing provider results remain
**NOT_MEASURED**; overall readiness remains **NOT_READY**. No charts imply four
measured arms, no mock metric implies model quality, and no privacy certification
is issued. Request concrete authorization through INT before any held operation.
