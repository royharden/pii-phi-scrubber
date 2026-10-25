# Limits and unresolved evidence

R03 has executed local synthetic tests and public development controls on a
combined candidate: see [validation](VALIDATION.md) for scope and evidence.
Actual frontier/base/fine-tuned model inference, training, controlled real-model
timing, sealed evaluation and independent product acceptance remain unperformed.
Passing fixture/test-double checks does not close those experiment gates.

Only English fictional NAME, EMAIL, PHONE and ACCOUNT_ID in one decoded JSON message
are supported. Offsets use Python Unicode codepoints without normalization. The bound
is 1,024 codepoints; model-specific token limits still require preflight. Other log
formats, languages, real PHI, arbitrary sensitive classes and production use are not
covered. Usernames derived from names and uncued opaque IDs are outside the narrow
label definition; supported text-visible full names can still be missed by regex.

The public fixture deliberately includes an uncued-name miss. Publication hides the
unsafe rendering while scoring retains its residual leak. The gold-aware gate knows
only annotated entities, can reject coincidental substrings and cannot guarantee
privacy for arbitrary text. It does not replace independent annotation or safe custody.

Small hand-authored development examples cannot establish statistical power, general
privacy performance or separate causal gains from entity versus template novelty.
Unmeasured arms, absent costs and insufficient cluster intervals are unknown, not zero.
The report labels them `not measured`, `unknown` and `insufficient`; a metric with a
zero denominator reads `N/A (0/0)`. The adoption floor table shows an undefined
fine-tuned precision or recall as `N/A (n/d)` and an undefined lower recall bound
as `not measured`. In the reviewed R03 source candidate, the harm-rate and paired
class/micro difference tables also include an Interval column with fixed wording
for a defined interval, insufficient blocks, insufficient valid draws or no measurement.
Partially supplied category compute metadata is rejected; fully absent legacy
metadata stays unknown. Compute time is never converted into a cost figure.
Fine-tuning can lose to the baseline; no model improvement is promised.

The mechanical split auditor checks only declared ancestor tokens and components.
It cannot discover undeclared shared generators, verify labels, enforce custody or
certify independent authorship. A structurally valid training permit/receipt similarly
cannot authenticate approvals, licenses or real execution. Future independent audit
must examine the actual pinned artifacts and custody process.

The sealed activation path requires an externally provisioned trusted operator host,
authenticated D4 native-isolation/file-policy capability and D5 pre-test target lock.
No OS enforcement, receipt issuer, provider-aware tokenizer or approved environment
is fabricated here. Synthetic integration tests do not qualify these interfaces
against an actual trusted host, provider or native enforcement boundary.
Uncertain journal begins cannot be retried; abandoned writer locks and torn writes
require authorized investigation. Timing interruptions remain incomplete rather than
silently rerunning passes. Cold initialization excludes unverified process/OS cache
effects; network frontier figures cannot establish provider-server startup latency.
Offline replay is restricted to byte-identical approved reports and never reopens gold.
