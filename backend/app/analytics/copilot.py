"""LLM Safety-Scientist Copilot — RAG-based signal-assessment drafting.

Assembles a structured pharmacovigilance signal-assessment memo grounded ONLY in
the signal's own already-computed evidence (no hallucination). The RAG context is
built from the signal dict and injected into a structured prompt sent to the local
Ollama daemon. Falls back to a high-quality deterministic memo when Ollama is
unavailable.

Sections returned:
  signal_summary | statistical_evidence | causality_assessment | clinical_context |
  regulatory_context | benefit_risk | recommendation (monitor/escalate/close) |
  recommendation_rationale | disclaimer | feature_tour | plain_english_tour
"""
from __future__ import annotations

import json
import re

from .. import llm
from .copilot_tour import attach_feature_tour

DISCLAIMER = (
    "PROTOTYPE — Synthetic data only. Evidence is derived from social-listening and "
    "surrogate analytics; not a validated pharmacovigilance submission. openFDA = US "
    "FAERS/MAUDE only; MedDRA coding is an open surrogate; not for clinical use."
)

_SYSTEM = (
    "You are an expert safety scientist at a regulatory agency. "
    "Draft a structured signal-assessment memo for internal review. "
    "CRITICAL RULES: "
    "(1) Use ONLY the evidence in the provided context block — never invent statistics, "
    "references, or facts. "
    "(2) Return valid JSON with exactly these keys: signal_summary, "
    "statistical_evidence, causality_assessment, clinical_context, regulatory_context, "
    "benefit_risk, recommendation, recommendation_rationale. "
    "(3) Each value is a plain string of 1-3 sentences. "
    "(4) recommendation must be exactly one of: monitor, escalate, close. "
    "(5) Neutral regulatory clinical tone."
)


def _fmt(v, d: int = 2) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return str(v)


def _build_context_brief(sig: dict) -> str:
    """Assemble a structured evidence brief from all fields in the signal dict."""
    drug = sig.get("drug", "unknown")
    md = sig.get("meddra") or {}
    pt = md.get("pt") or sig.get("symptom", "unknown")
    soc = md.get("soc", "")
    n = sig.get("post_count", 0)
    strength = sig.get("strength", "WEAK")
    sdr = sig.get("sdr_flag", False)
    spike = sig.get("spike_flag", False)
    spike_z = sig.get("spike_z")

    prr = sig.get("prr")
    prr_ci = sig.get("prr_ci") or [None, None]
    ror = sig.get("ror")
    ror_ci = sig.get("ror_ci") or [None, None]
    chi2 = sig.get("chi_square")
    eb05 = sig.get("eb05")
    ic025 = sig.get("ic025")

    cal_p = sig.get("calibrated_p")
    calibrated = sig.get("calibrated_signal", False)
    e_value = sig.get("e_value")

    who_umc = sig.get("who_umc", "Unassessable")
    who_score = sig.get("who_umc_score")
    factors = sig.get("who_umc_factors") or []
    severity = sig.get("severity", "Low")

    pgx = sig.get("pgx_actionable", False)
    pgx_info = sig.get("pgx") or {}
    mech = sig.get("mechanism_plausible", False)
    mech_info = sig.get("mechanism") or {}
    class_effect = sig.get("class_effect", False)
    class_info = sig.get("class_info") or {}
    smq = sig.get("smq") or []
    boxed = sig.get("boxed_warning", False)
    boxed_info = sig.get("boxed") or {}
    recall = sig.get("recall") or {}
    label = sig.get("label_evidence") or {}
    fda_ev = sig.get("fda_evidence") or {}
    lit = sig.get("literature") or {}
    hr = sig.get("hr")
    hr_ci = sig.get("hr_ci") or [None, None]
    hr_elevated = sig.get("hr_elevated", False)
    spatial = sig.get("spatial_cluster", False)
    spatial_info = sig.get("spatial") or {}
    br_verdict = sig.get("br_verdict")
    br_info = sig.get("benefit_risk") or {}
    completeness = sig.get("completeness")
    stands_out = sig.get("stands_out_in_class", False)
    ac = sig.get("active_comparator") or {}

    lines = [
        f"SIGNAL: {drug} -> {pt}",
        f"MedDRA SOC: {soc}" if soc else "",
        f"Reports (n): {n} | Strength: {strength} | SDR flag: {sdr}",
        f"Reporting spike: YES (z={_fmt(spike_z, 1)})" if spike else "Reporting spike: no",
        "",
        "=== DISPROPORTIONALITY ===",
        f"PRR={_fmt(prr)} (95% CI {_fmt(prr_ci[0])}-{_fmt(prr_ci[1])})" if prr is not None else "PRR: not computed",
        f"ROR={_fmt(ror)} (95% CI {_fmt(ror_ci[0])}-{_fmt(ror_ci[1])})" if ror is not None else "ROR: not computed",
        f"Chi2={_fmt(chi2)}" if chi2 is not None else "",
        f"EB05={_fmt(eb05)} (FDA threshold >=2; {'MEETS' if (eb05 or 0) >= 2 else 'below'})" if eb05 is not None else "EB05: not computed",
        f"IC025={_fmt(ic025)} (UMC threshold >0; {'MEETS' if (ic025 or 0) > 0 else 'below'})" if ic025 is not None else "IC025: not computed",
        "",
        "=== EMPIRICAL CALIBRATION ===",
        f"Calibrated p={_fmt(cal_p, 4)} | Survives calibration: {calibrated}" if cal_p is not None else "Calibration: not available",
        f"E-value={_fmt(e_value)} (confounder strength needed to explain away association)" if e_value else "",
        "",
        "=== WHO-UMC CAUSALITY ===",
        f"Causality: {who_umc} (score={_fmt(who_score)})",
        f"Severity: {severity}",
        f"Causality factors: {', '.join(factors)}" if factors else "Causality factors: none documented",
        "",
        "=== CLINICAL CONTEXT ===",
        (f"PGx actionable: YES | Gene: {pgx_info.get('gene')} | Allele: {pgx_info.get('allele')} | "
         f"Phenotype: {pgx_info.get('phenotype')} | Recommendation: {pgx_info.get('recommendation')}")
        if pgx else "PGx: no actionable pharmacogenomic variant for this drug-event pair",
        (f"Mechanistic plausibility: YES | Target/MoA: {mech_info.get('target_or_moa')} | "
         f"{mech_info.get('mechanism_explanation', '')}")
        if mech else "Mechanistic plausibility: not established",
        (f"Class effect: YES | Class: {class_info.get('class_name')} | "
         f"{class_info.get('member_count')} member drugs | Class EB05={_fmt(class_info.get('eb05'))}")
        if class_effect else "Class effect: not detected across ATC class members",
        (f"SMQ memberships: {', '.join([m.get('smq', '') for m in smq[:3]])}")
        if smq else "SMQ: no syndrome-level query match",
        (f"HR (Cox PH surrogate)={_fmt(hr)} (95% CI {_fmt(hr_ci[0])}-{_fmt(hr_ci[1])}) | "
         f"Elevated: {hr_elevated}")
        if hr is not None else "Hazard ratio: not computed",
        "",
        "=== REGULATORY CONTEXT ===",
        (f"Boxed warning: YES | Covers this event: {boxed_info.get('covers_event')} | "
         f"Topics: {', '.join(boxed_info.get('topics', []))}")
        if boxed else "Boxed warning: none documented",
        (f"FDA recalls: {recall.get('count', 0)} record(s) | "
         f"Latest: {(recall.get('latest') or {}).get('classification', 'n/a')}")
        if recall.get("available") else "FDA recalls: none on record",
        f"DailyMed label: {'present in SPL registry' if label.get('available') else 'not found'}",
        (f"openFDA FAERS/MAUDE: {fda_ev.get('report_count', 0)} corroborating reports")
        if fda_ev.get("available") else "openFDA FAERS/MAUDE: no corroborating reports retrieved",
        (f"PubMed literature: {lit.get('count', 0)} indexed articles")
        if lit.get("available") else "PubMed: no indexed literature for this drug-event pair",
        (f"Active-comparator: stands out in class={stands_out} | "
         f"AC-ROR={_fmt(ac.get('ac_ror'))} (CI {_fmt((ac.get('ac_ror_ci') or [None, None])[0])}-"
         f"{_fmt((ac.get('ac_ror_ci') or [None, None])[1])})")
        if ac.get("comparator_class") else "Active-comparator: not computed",
        (f"Geographic cluster: {spatial_info.get('hotspot')} | "
         f"RR={_fmt(spatial_info.get('rr'), 1)} | Observed={spatial_info.get('observed')}")
        if spatial else "Geographic cluster: not detected",
        "",
        "=== BENEFIT-RISK ===",
        (f"Verdict: {br_verdict} | NNT={_fmt(br_info.get('nnt'), 0)} for {br_info.get('indication')} | "
         f"NNH={_fmt(br_info.get('nnh'), 0)} for {pt}")
        if br_verdict else "Benefit-risk: not computed",
        "",
        "=== DOCUMENTATION QUALITY ===",
        f"vigiGrade completeness: {_fmt(completeness)}" if completeness is not None else "Completeness: not computed",
    ]
    return "\n".join(l for l in lines if l)


def _deterministic_assessment(sig: dict) -> dict:
    """Build a fully deterministic structured assessment memo from the signal dict."""
    drug = sig.get("drug", "the drug")
    md = sig.get("meddra") or {}
    pt = md.get("pt") or sig.get("symptom", "the reaction")
    n = sig.get("post_count", 0)
    strength = sig.get("strength", "WEAK")
    sdr = sig.get("sdr_flag", False)
    spike = sig.get("spike_flag", False)

    prr = sig.get("prr")
    prr_ci = sig.get("prr_ci") or [None, None]
    ror = sig.get("ror")
    ror_ci = sig.get("ror_ci") or [None, None]
    chi2 = sig.get("chi_square")
    eb05 = sig.get("eb05")
    ic025 = sig.get("ic025")

    calibrated = sig.get("calibrated_signal", False)
    cal_p = sig.get("calibrated_p")
    e_value = sig.get("e_value")

    who_umc = sig.get("who_umc", "Unassessable")
    who_score = sig.get("who_umc_score", 0.0)
    factors = sig.get("who_umc_factors") or []
    severity = sig.get("severity", "Low")

    hr = sig.get("hr")
    hr_ci = sig.get("hr_ci") or [None, None]
    hr_elevated = sig.get("hr_elevated", False)

    pgx = sig.get("pgx_actionable", False)
    pgx_info = sig.get("pgx") or {}
    mech = sig.get("mechanism_plausible", False)
    mech_info = sig.get("mechanism") or {}
    class_effect = sig.get("class_effect", False)
    class_info = sig.get("class_info") or {}
    smq = sig.get("smq") or []

    boxed = sig.get("boxed_warning", False)
    boxed_info = sig.get("boxed") or {}
    recall = sig.get("recall") or {}
    label = sig.get("label_evidence") or {}
    fda_ev = sig.get("fda_evidence") or {}
    lit = sig.get("literature") or {}
    stands_out = sig.get("stands_out_in_class", False)
    ac = sig.get("active_comparator") or {}
    spatial = sig.get("spatial_cluster", False)
    spatial_info = sig.get("spatial") or {}
    br_verdict = sig.get("br_verdict")
    br_info = sig.get("benefit_risk") or {}

    # --- Signal summary ---
    sig_parts = [
        f"A {strength.lower()} disproportionality signal has been identified between "
        f"{drug} and {pt} based on {n} social-listening report(s)."
    ]
    if sdr:
        sig_parts.append("The pair meets the Signal of Disproportionate Reporting (SDR) criterion.")
    if spike:
        sig_parts.append("A statistically significant reporting spike is currently active, warranting priority review.")
    signal_summary = " ".join(sig_parts)

    # --- Statistical evidence ---
    stat_parts = []
    if prr is not None:
        ci_str = (f" (95% CI {_fmt(prr_ci[0])}-{_fmt(prr_ci[1])})"
                  if all(x is not None for x in prr_ci) else "")
        stat_parts.append(f"PRR={_fmt(prr)}{ci_str}")
    if ror is not None:
        ci_str = (f" (95% CI {_fmt(ror_ci[0])}-{_fmt(ror_ci[1])})"
                  if all(x is not None for x in ror_ci) else "")
        stat_parts.append(f"ROR={_fmt(ror)}{ci_str}")
    if chi2 is not None:
        stat_parts.append(f"chi2={_fmt(chi2)}")
    if eb05 is not None:
        flag = "meets" if (eb05 or 0) >= 2 else "below"
        stat_parts.append(f"EB05={_fmt(eb05)} ({flag} FDA threshold of >=2)")
    if ic025 is not None:
        flag = "meets" if (ic025 or 0) > 0 else "below"
        stat_parts.append(f"IC025={_fmt(ic025)} ({flag} UMC threshold of >0)")
    statistical_evidence = "; ".join(stat_parts) + "." if stat_parts else "Disproportionality statistics not yet computed."
    if calibrated and cal_p is not None:
        statistical_evidence += f" The signal survives empirical-null calibration (calibrated p={_fmt(cal_p, 4)})."
    elif cal_p is not None:
        statistical_evidence += f" Empirical calibration p={_fmt(cal_p, 4)} (does not meet p<0.05 threshold)."
    if e_value:
        statistical_evidence += (
            f" E-value={_fmt(e_value)}: an unmeasured confounder would need to be associated with "
            f"both the drug and the event by a factor of >={_fmt(e_value)}-fold to fully explain the association."
        )

    # --- Causality assessment ---
    caus_parts = [
        f"WHO-UMC deterministic causality: {who_umc} (composite score={_fmt(who_score)}).",
        f"Signal severity: {severity}.",
    ]
    if factors:
        caus_parts.append(f"Causality-supporting factors: {', '.join(factors)}.")
    if hr is not None:
        hr_ci_str = ""
        if all(x is not None for x in hr_ci):
            hr_ci_str = f" (95% CI {_fmt(hr_ci[0])}-{_fmt(hr_ci[1])})"
        elev = " — elevated (CI lower bound > 1)" if hr_elevated else ""
        caus_parts.append(
            f"Social-listening Cox PH surrogate: HR={_fmt(hr)}{hr_ci_str}{elev}."
        )
    causality_assessment = " ".join(caus_parts)

    # --- Clinical context ---
    clin_parts = []
    if pgx:
        gene = pgx_info.get("gene", "unknown gene")
        allele = pgx_info.get("allele", "")
        pheno = pgx_info.get("phenotype", "")
        rec = pgx_info.get("recommendation", "")
        clin_parts.append(
            f"Pharmacogenomic (PGx) actionable variant: {gene} {allele} ({pheno}). "
            f"CPIC/PharmGKB surrogate recommendation: {rec}."
        )
    else:
        clin_parts.append("No actionable pharmacogenomic variant identified for this drug-event pair.")

    if mech:
        target = mech_info.get("target_or_moa", "unknown MoA")
        expl = mech_info.get("mechanism_explanation", "")
        clin_parts.append(f"Mechanistic plausibility: {target}. {expl}")
    else:
        clin_parts.append("Mechanistic plausibility not established in the knowledge base.")

    if class_effect:
        class_name = class_info.get("class_name", "the drug class")
        n_class = class_info.get("member_count", "multiple")
        class_eb05 = class_info.get("eb05")
        clin_parts.append(
            f"Class effect detected: {n_class} member(s) of {class_name} report this event "
            f"(class-level EB05={_fmt(class_eb05)})."
        )
    if smq:
        smq_names = [m.get("smq") for m in smq[:3] if m.get("smq")]
        if smq_names:
            clin_parts.append(f"SMQ syndrome membership: {'; '.join(smq_names)}.")
    clinical_context = " ".join(clin_parts)

    # --- Regulatory context ---
    reg_parts = []
    if boxed:
        topics = ", ".join(boxed_info.get("topics", []))
        covers = boxed_info.get("covers_event", False)
        reg_parts.append(
            f"The drug carries an FDA boxed warning{' that covers this specific event' if covers else ''}. "
            f"Warning topics: {topics}."
        )
    else:
        reg_parts.append("No FDA boxed warning documented for this drug.")

    if recall.get("available"):
        count = recall.get("count", 0)
        cls = (recall.get("latest") or {}).get("classification", "")
        reg_parts.append(
            f"FDA recall/enforcement: {count} record(s) on file"
            f"{f' (latest: {cls})' if cls else ''}."
        )
    else:
        reg_parts.append("No FDA recall or enforcement records retrieved.")

    if label.get("available"):
        reg_parts.append("Product is present in the DailyMed SPL label registry.")

    if fda_ev.get("available"):
        reg_parts.append(
            f"openFDA FAERS/MAUDE corroboration: ~{fda_ev.get('report_count', 0)} reports."
        )
    else:
        reg_parts.append("No openFDA FAERS/MAUDE corroborating reports retrieved.")

    if lit.get("available"):
        reg_parts.append(f"PubMed literature: {lit.get('count', 0)} indexed articles for this drug-event pair.")

    if stands_out:
        reg_parts.append(
            f"Active-comparator analysis: {drug} stands out within its ATC class "
            f"(AC-ROR={_fmt(ac.get('ac_ror'))})."
        )

    if spatial:
        reg_parts.append(
            f"Geographic cluster detected in {spatial_info.get('hotspot')} "
            f"(relative risk {_fmt(spatial_info.get('rr'), 1)}x)."
        )
    regulatory_context = " ".join(reg_parts)

    # --- Benefit-risk ---
    if br_verdict:
        nnt = br_info.get("nnt")
        nnh = br_info.get("nnh")
        indication = br_info.get("indication", "its approved indication")
        br_text = f"Quantitative benefit-risk verdict: {br_verdict}. "
        if nnt and nnh:
            br_text += f"NNT={_fmt(nnt, 0)} for benefit ({indication}); NNH={_fmt(nnh, 0)} for harm ({pt})."
            try:
                ratio = float(nnh) / float(nnt)
                br_text += f" NNH/NNT ratio={_fmt(ratio)}: a ratio >1 favours benefit, <1 favours harm."
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    else:
        br_text = (
            "Quantitative benefit-risk analysis (BRAT/MCDA surrogate) has not been computed for this signal. "
            "Benefit-risk inference should be based on the disproportionality and causality evidence above."
        )
    benefit_risk = br_text

    # --- Recommendation (rule-based) ---
    esc_score = 0
    if strength == "STRONG":
        esc_score += 2
    elif strength == "MODERATE":
        esc_score += 1
    if who_umc in ("Certain", "Probable"):
        esc_score += 2
    elif who_umc == "Possible":
        esc_score += 1
    if calibrated:
        esc_score += 1
    if boxed:
        esc_score += 1
    if spike:
        esc_score += 1
    if pgx:
        esc_score += 1
    if hr_elevated:
        esc_score += 1
    if br_verdict == "Unfavourable":
        esc_score += 1
    if stands_out:
        esc_score += 1

    weak_signal = (n <= 2 and strength == "WEAK" and who_umc in ("Unlikely", "Unassessable")
                   and not calibrated)
    if weak_signal:
        recommendation = "close"
        rec_rationale = (
            f"Signal is weak (PRR={_fmt(prr)}, n={n}) with {who_umc} causality and insufficient "
            f"evidence to distinguish from background noise. No calibration signal detected. "
            f"Recommend closing pending new evidence."
        )
    elif esc_score >= 5:
        recommendation = "escalate"
        esc_reasons = []
        if strength in ("STRONG", "MODERATE"):
            esc_reasons.append(f"{strength.lower()} disproportionality (PRR={_fmt(prr)}, EB05={_fmt(eb05)})")
        if who_umc in ("Certain", "Probable"):
            esc_reasons.append(f"{who_umc} WHO-UMC causality")
        if calibrated:
            esc_reasons.append("calibrated signal")
        if boxed:
            esc_reasons.append("boxed warning drug")
        if pgx:
            esc_reasons.append(f"actionable PGx variant ({pgx_info.get('gene', '')})")
        if spike:
            esc_reasons.append("active reporting spike")
        rec_rationale = (
            f"Multiple escalation criteria met: {'; '.join(esc_reasons)}. "
            f"Severity={severity}. Recommend formal review by the medical review committee."
        )
    else:
        recommendation = "monitor"
        rec_rationale = (
            f"{strength} signal with {who_umc} causality and {severity} severity. "
            f"Evidence does not yet meet escalation threshold (score={esc_score}/5). "
            f"Continue active surveillance; reassess if case count increases, causality "
            f"strengthens, or new corroborating evidence emerges."
        )

    return {
        "signal_summary": signal_summary,
        "statistical_evidence": statistical_evidence,
        "causality_assessment": causality_assessment,
        "clinical_context": clinical_context,
        "regulatory_context": regulatory_context,
        "benefit_risk": benefit_risk,
        "recommendation": recommendation,
        "recommendation_rationale": rec_rationale,
        "disclaimer": DISCLAIMER,
    }


def generate_assessment(signal_dict: dict, allow_llm: bool = True) -> dict:
    """Return a structured signal-assessment memo dict with a 'source' key.

    When allow_llm=True (default), tries the local Ollama daemon first and falls
    back to the deterministic template.  When allow_llm=False (bulk / offline
    mode), returns the deterministic memo immediately.
    """
    fallback = _deterministic_assessment(signal_dict)

    if not allow_llm:
        return attach_feature_tour({**fallback, "source": "deterministic"}, signal_dict)

    context_brief = _build_context_brief(signal_dict)
    prompt = (
        "Draft a structured pharmacovigilance signal-assessment memo from the evidence "
        "brief below. Use ONLY the provided data — never invent numbers or references. "
        "Return ONLY valid JSON.\n\n"
        "=== SIGNAL EVIDENCE BRIEF ===\n"
        f"{context_brief}\n"
        "=== END BRIEF ===\n\n"
        "Required JSON keys: signal_summary, statistical_evidence, causality_assessment, "
        "clinical_context, regulatory_context, benefit_risk, recommendation (one of: "
        "monitor/escalate/close), recommendation_rationale.\n"
        "Each value must be a string of 1-3 sentences."
    )

    raw = llm.generate(prompt, system=_SYSTEM, temperature=0.15, want_json=True)

    if raw and len(raw) > 50:
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    pass

        if isinstance(parsed, dict):
            required = {
                "signal_summary", "statistical_evidence", "causality_assessment",
                "clinical_context", "regulatory_context", "benefit_risk",
                "recommendation", "recommendation_rationale",
            }
            for k in required:
                if k not in parsed or not parsed[k]:
                    parsed[k] = fallback.get(k, "")
            if parsed.get("recommendation") not in ("monitor", "escalate", "close"):
                parsed["recommendation"] = fallback["recommendation"]
            parsed["disclaimer"] = DISCLAIMER
            return attach_feature_tour({**parsed, "source": "llm"}, signal_dict)

    return attach_feature_tour({**fallback, "source": "deterministic"}, signal_dict)
