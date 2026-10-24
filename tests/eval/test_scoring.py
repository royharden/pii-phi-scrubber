"""Hand-derived exact-span scoring cases (plan: Evaluation and acceptance).

Every expected number below is derived in comments from the message text and
the plan's rules: one-to-one exact (start,end,label) matching after dedup, wrong
label = FP(pred class) + FN(gold class), partial overlap earns no TP, zero
denominators are null with reasons, failed records stay in the population.
"""
from m7.contracts import Span
from m7.eval import Observation, score

# M: "name=Ann Lee mail=a@b.io tel=555-0100 acct=A123"
#     0    5      12    18    24   29      37    43  47
# "name=" is 0..4, "Ann Lee" = [5,12) (7 cp), " mail=" 12..17, "a@b.io" = [18,24) (6 cp),
# " tel=" 24..28, "555-0100" = [29,37) (8 cp), " acct=" 37..42, "A123" = [43,47) (4 cp).
M = "name=Ann Lee mail=a@b.io tel=555-0100 acct=A123"
assert len(M) == 47
GOLD_M = (Span(start=5, end=12, label="NAME"), Span(start=18, end=24, label="EMAIL"),
          Span(start=29, end=37, label="PHONE"), Span(start=43, end=47, label="ACCOUNT_ID"))
# Gold mask = 7 + 6 + 8 + 4 = 25 codepoints; benign = 47 - 25 = 22.

# B: "latency 4821 ms" -> "4821" = [8,12) (4 cp); a benign number, no gold. Length 15.
B = "latency 4821 ms"
assert len(B) == 15


def obs(record_id, message, gold, predicted=(), *, available=True, structure=True,
        block="b0", slice_name="normal"):
    return Observation(record_id, block, slice_name, len(message), tuple(gold),
                       tuple(predicted), available, structure)


def mixed_prediction():
    return (Span(start=5, end=12, label="NAME"),         # exact -> NAME TP
            Span(start=5, end=12, label="NAME"),         # duplicate triple -> deduped, not FP
            Span(start=18, end=22, label="EMAIL"),       # partial -> EMAIL FP + EMAIL FN
            Span(start=29, end=37, label="ACCOUNT_ID"),  # wrong class exact bounds -> ACCOUNT FP + PHONE FN
            Span(start=43, end=47, label="ACCOUNT_ID"))  # exact -> ACCOUNT TP


def test_exact_strict_counts_per_class_and_micro():
    m = score([obs("r1", M, GOLD_M, mixed_prediction())])
    pc = m["per_class"]
    # NAME tp1 fp0 fn0; EMAIL tp0 fp1 fn1; PHONE tp0 fp0 fn1; ACCOUNT tp1 fp1 fn0.
    assert (pc["NAME"]["tp"], pc["NAME"]["fp"], pc["NAME"]["fn"]) == (1, 0, 0)
    assert (pc["EMAIL"]["tp"], pc["EMAIL"]["fp"], pc["EMAIL"]["fn"]) == (0, 1, 1)
    assert (pc["PHONE"]["tp"], pc["PHONE"]["fp"], pc["PHONE"]["fn"]) == (0, 0, 1)
    assert (pc["ACCOUNT_ID"]["tp"], pc["ACCOUNT_ID"]["fp"], pc["ACCOUNT_ID"]["fn"]) == (1, 1, 0)
    # Micro: tp 2, fp 2, fn 2 -> P = 2/4, R = 2/4, F1 = 4/(4+2+2) = 0.5.
    micro = m["micro"]
    assert (micro["tp"], micro["fp"], micro["fn"]) == (2, 2, 2)
    assert micro["precision"]["value"] == 0.5 and micro["recall"]["value"] == 0.5
    assert micro["f1"]["value"] == 0.5
    assert micro["support"] == 4 and micro["predicted_count"] == 4
    # ACCOUNT: P = 1/2, R = 1/1, F1 = 2/(2+1+0) = 2/3.
    assert pc["ACCOUNT_ID"]["precision"]["value"] == 0.5
    assert pc["ACCOUNT_ID"]["recall"]["value"] == 1.0
    assert abs(pc["ACCOUNT_ID"]["f1"]["value"] - 2 / 3) < 1e-12


def test_wrong_class_exact_boundary_is_fp_plus_fn_not_tp():
    # Only PHONE gold; predicted the exact PHONE interval as ACCOUNT_ID.
    m = score([obs("r1", M, GOLD_M[2:3], (Span(start=29, end=37, label="ACCOUNT_ID"),))])
    assert m["per_class"]["PHONE"]["tp"] == 0 and m["per_class"]["PHONE"]["fn"] == 1
    assert m["per_class"]["ACCOUNT_ID"]["fp"] == 1 and m["per_class"]["ACCOUNT_ID"]["tp"] == 0
    assert (m["micro"]["tp"], m["micro"]["fp"], m["micro"]["fn"]) == (0, 1, 1)
    # Codepoint harm is label-blind: the 8 PHONE codepoints are fully covered.
    assert m["residual_sensitive_codepoints"]["numerator"] == 0
    assert m["residual_sensitive_codepoints"]["denominator"] == 8


def test_partial_span_is_fp_plus_fn_and_leaves_residual_codepoints():
    # Gold EMAIL [18,24); predicted [18,22) -> strict FP 1 + FN 1, no TP.
    m = score([obs("r1", M, GOLD_M[1:2], (Span(start=18, end=22, label="EMAIL"),))])
    e = m["per_class"]["EMAIL"]
    assert (e["tp"], e["fp"], e["fn"]) == (0, 1, 1)
    assert e["precision"]["value"] == 0.0 and e["recall"]["value"] == 0.0
    # Overlap measure defined by the scorer is codepoint residual: 22,23 uncovered = 2 of 6.
    r = m["residual_sensitive_codepoints"]
    assert (r["numerator"], r["denominator"]) == (2, 6)
    assert m["records_with_residual"]["numerator"] == 1


def test_duplicate_identical_prediction_counted_once():
    # Contract: identical (start,end,label) triples are deduplicated -> 1 TP, 0 FP.
    dup = (Span(start=5, end=12, label="NAME"), Span(start=5, end=12, label="NAME"))
    m = score([obs("r1", M, GOLD_M[:1], dup)])
    assert (m["per_class"]["NAME"]["tp"], m["per_class"]["NAME"]["fp"]) == (1, 0)
    assert m["micro"]["predicted_count"] == 1


def test_mixed_macro_has_null_precision_when_a_class_is_undefined():
    m = score([obs("r1", M, GOLD_M, mixed_prediction())])
    pc = m["per_class"]
    # PHONE predicted 0 -> precision 0/0 = null; recall 0/1 = 0; F1 0/(0+0+1) = 0.
    assert pc["PHONE"]["precision"] == {"value": None, "numerator": 0, "denominator": 0,
                                        "null_reason": "zero_denominator"}
    assert pc["PHONE"]["recall"]["value"] == 0.0 and pc["PHONE"]["f1"]["value"] == 0.0
    assert m["macro"]["precision"]["value"] is None
    assert m["macro"]["precision"]["null_reason"] == "undefined_class"
    assert m["macro"]["precision"]["defined_classes"] == 3
    # Macro recall: (1 + 0 + 0 + 1)/4 = 0.5; macro F1: (1 + 0 + 0 + 2/3)/4 = 5/12.
    assert m["macro"]["recall"]["value"] == 0.5
    assert abs(m["macro"]["f1"]["value"] - 5 / 12) < 1e-12
    # Masks: predicted cover 7 + 4 + 8 + 4 = 23 of 25 gold cp; residual 2. No benign cp removed.
    assert (m["residual_sensitive_codepoints"]["numerator"], m["residual_sensitive_codepoints"]["denominator"]) == (2, 25)
    assert (m["benign_codepoints_redacted"]["numerator"], m["benign_codepoints_redacted"]["denominator"]) == (0, 22)


def test_benign_number_not_fn_but_predicted_span_is_fp():
    unredacted = score([obs("b1", B, ())])
    # No gold anywhere -> FN 0 for every class; no predictions -> FP 0.
    assert all(c["fn"] == 0 and c["fp"] == 0 for c in unredacted["per_class"].values())
    assert unredacted["benign_record_overredaction"]["numerator"] == 0
    flagged = score([obs("b1", B, (), (Span(start=8, end=12, label="ACCOUNT_ID"),))])
    a = flagged["per_class"]["ACCOUNT_ID"]
    assert (a["tp"], a["fp"], a["fn"]) == (0, 1, 0)
    # 4 of 15 benign codepoints removed; the single benign record is over-redacted.
    assert (flagged["benign_codepoints_redacted"]["numerator"], flagged["benign_codepoints_redacted"]["denominator"]) == (4, 15)
    assert (flagged["benign_record_overredaction"]["numerator"], flagged["benign_record_overredaction"]["denominator"]) == (1, 1)
    # No gold codepoints at all -> residual ratio undefined, not 0.
    assert flagged["residual_sensitive_codepoints"]["value"] is None


def test_combined_population_sums_counts():
    m = score([obs("r1", M, GOLD_M, mixed_prediction()),
               obs("b1", B, (), (Span(start=8, end=12, label="ACCOUNT_ID"),))])
    # ACCOUNT fp 1 (r1) + 1 (b1) = 2; micro fp 2 + 1 = 3 -> P = 2/5, R = 2/4.
    assert m["per_class"]["ACCOUNT_ID"]["fp"] == 2
    assert (m["micro"]["tp"], m["micro"]["fp"], m["micro"]["fn"]) == (2, 3, 2)
    assert m["micro"]["precision"]["value"] == 0.4 and m["micro"]["recall"]["value"] == 0.5
    # Benign cp: 22 (r1) + 15 (b1) = 37; removed 0 + 4 = 4.
    assert (m["benign_codepoints_redacted"]["numerator"], m["benign_codepoints_redacted"]["denominator"]) == (4, 37)
    assert m["corpus_N"] == 2 and m["answered_N"] == 2


def test_all_empty_class_is_null_never_zero_or_one():
    # Only EMAIL gold and an exact EMAIL prediction. NAME/PHONE/ACCOUNT have tp=fp=fn=0.
    m = score([obs("r1", M, GOLD_M[1:2], GOLD_M[1:2])])
    for label in ("NAME", "PHONE", "ACCOUNT_ID"):
        for metric in ("precision", "recall", "f1"):
            v = m["per_class"][label][metric]
            assert v["value"] is None, (label, metric)
            assert (v["numerator"], v["denominator"], v["null_reason"]) == (0, 0, "zero_denominator")
    assert m["per_class"]["EMAIL"]["f1"]["value"] == 1.0
    for metric in ("precision", "recall", "f1"):
        assert m["macro"][metric]["value"] is None
        assert m["macro"][metric]["defined_classes"] == 1


def test_empty_population_reports_nulls():
    m = score([])
    assert m["corpus_N"] == 0
    assert m["micro"]["precision"]["value"] is None
    assert m["unavailable"]["value"] is None and m["unavailable"]["null_reason"] == "zero_denominator"


def test_failed_record_stays_in_denominator_as_full_miss():
    # Correct spans attached, but the attempt failed: they must be ignored.
    ok = obs("r1", M, GOLD_M, GOLD_M)
    failed = obs("r2", M, GOLD_M, GOLD_M, available=False, structure=False)
    m = score([ok, failed])
    # Each class: tp 1 (r1), fn 1 (r2) -> recall 1/2; precision 1/1.
    for label in ("NAME", "EMAIL", "PHONE", "ACCOUNT_ID"):
        c = m["per_class"][label]
        assert (c["tp"], c["fp"], c["fn"]) == (1, 0, 1)
        assert c["recall"]["value"] == 0.5 and c["precision"]["value"] == 1.0
    # Residual: r2 full gold mask 25 of total 50.
    assert (m["residual_sensitive_codepoints"]["numerator"], m["residual_sensitive_codepoints"]["denominator"]) == (25, 50)
    assert (m["records_with_residual"]["numerator"], m["records_with_residual"]["denominator"]) == (1, 2)
    assert (m["unavailable"]["numerator"], m["unavailable"]["denominator"]) == (1, 2)
    assert m["unsafe_or_unavailable"]["numerator"] == 1
    assert (m["corpus_N"], m["answered_N"], m["error_N"]) == (2, 1, 1)
    assert m["structure_failures"] == 0


def test_failed_benign_record_is_unavailable_but_not_a_leak():
    m = score([obs("b1", B, (), available=False, structure=False)])
    assert m["records_with_residual"]["numerator"] == 0
    assert m["residual_sensitive_codepoints"]["value"] is None  # 0/0
    assert (m["unavailable"]["numerator"], m["unsafe_or_unavailable"]["numerator"]) == (1, 1)
    # Failure contributes zero measured benign redaction (cannot earn or lose privacy).
    assert m["benign_codepoints_redacted"]["numerator"] == 0
    assert m["benign_record_overredaction"]["numerator"] == 0


def test_renderer_failure_keeps_detection_counts_but_is_full_leak_and_unavailable():
    # Detector spans are exactly right; renderer failed (structure invalid).
    m = score([obs("r1", M, GOLD_M, GOLD_M, available=True, structure=False)])
    assert (m["micro"]["tp"], m["micro"]["fp"], m["micro"]["fn"]) == (4, 0, 0)
    assert (m["residual_sensitive_codepoints"]["numerator"], m["residual_sensitive_codepoints"]["denominator"]) == (25, 25)
    assert m["benign_codepoints_redacted"]["numerator"] == 0
    assert m["structure_failures"] == 1
    assert m["unavailable"]["numerator"] == 1 and m["unsafe_or_unavailable"]["numerator"] == 1
    assert m["answered_N"] == 0


def test_overlapping_predictions_union_mask_not_double_counted():
    # Two overlapping predictions over EMAIL [18,24): [18,22) EMAIL and [20,24) NAME.
    # Union covers 18..23 = 6 cp -> residual 0; strict: EMAIL fp1 fn1, NAME fp1.
    m = score([obs("r1", M, GOLD_M[1:2], (Span(start=18, end=22, label="EMAIL"),
                                          Span(start=20, end=24, label="NAME")))])
    assert m["residual_sensitive_codepoints"]["numerator"] == 0
    assert m["per_class"]["EMAIL"]["fn"] == 1 and m["per_class"]["NAME"]["fp"] == 1
    assert m["benign_codepoints_redacted"]["numerator"] == 0
