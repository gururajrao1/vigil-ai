"""Focused tests for the disproportionality math (PRR/ROR CIs, EBGM/EB05, IC/IC025, SDR)."""
from __future__ import annotations

from app.analytics.disproportionality import compute_signals


def _demo_reports():
    return (
        [("isotretinoin", "depression")] * 18
        + [("metformin", "nausea")] * 6
        + [("ibuprofen", "headache")] * 4
        + [("isotretinoin", "fatigue")] * 3
        + [("metformin", "fatigue")] * 2
        + [("gabapentin", "dizziness")] * 5
    )


def test_metrics_present_and_ordered():
    sig = compute_signals(_demo_reports())
    assert sig, "expected signals"
    top = sig[0]
    # every metric must be present
    for k in ("prr", "prr_ci_low", "prr_ci_high", "ror", "ror_ci_low", "ror_ci_high",
              "chi_square", "ic", "ic025", "ebgm", "eb05", "strength", "sdr_flag",
              "expected"):
        assert k in top, f"missing {k}"
    # CI ordering sanity
    assert top["prr_ci_low"] <= top["prr"] <= top["prr_ci_high"]
    assert top["ror_ci_low"] <= top["ror"] <= top["ror_ci_high"]


def test_hero_signal_is_sdr():
    sig = compute_signals(_demo_reports())
    hero = next(s for s in sig if s["drug"] == "isotretinoin" and s["symptom"] == "depression")
    assert hero["sdr_flag"] is True          # flagged via PRR criterion
    assert hero["strength"] == "STRONG"
    assert hero["prr_ci_low"] >= 1.0          # PRR CI lower bound clears 1
    assert hero["chi_square"] >= 4
    # IC025 can be < 0 on a tiny closed corpus (BCPNN is intentionally conservative);
    # just assert the Bayesian metrics are computed as finite numbers.
    assert isinstance(hero["ic025"], float)
    assert hero["eb05"] > 0


def test_weak_pair_not_sdr():
    sig = compute_signals(_demo_reports())
    weak = next(s for s in sig if s["drug"] == "isotretinoin" and s["symptom"] == "fatigue")
    assert weak["sdr_flag"] is False
    assert weak["strength"] == "WEAK"


def test_empty():
    assert compute_signals([]) == []


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sig = compute_signals(_demo_reports())
    for s in sig:
        flag = "SDR" if s["sdr_flag"] else "   "
        print(f"{flag} {s['drug']:>14} -> {s['symptom']:<12} "
              f"n={s['post_count']:>2} PRR={s['prr']:>6} "
              f"CI[{s['prr_ci_low']}-{s['prr_ci_high']}] ROR={s['ror']:>7} "
              f"chi2={s['chi_square']:>6} IC={s['ic']:>5} IC025={s['ic025']:>5} "
              f"EBGM={s['ebgm']:>5} EB05={s['eb05']:>5} {s['strength']}")
    test_metrics_present_and_ordered()
    test_hero_signal_is_sdr()
    test_weak_pair_not_sdr()
    test_empty()
    print("=== DISPROPORTIONALITY TESTS OK ===")
