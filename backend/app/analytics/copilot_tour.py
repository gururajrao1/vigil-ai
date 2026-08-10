"""Plain-English feature tour + Q&A for Signal Detail.

Maps every analysis panel (Remine -> Cox -> MaxSPRT -> triangulation ->
4-gate AE, etc.) into non-domain language so the AI Signal Copilot can
explain what the numbers mean without removing the technical UI.
"""
from __future__ import annotations

import re
from typing import Any


def _g(sig: Any, key: str, default: Any = None) -> Any:
    if isinstance(sig, dict):
        return sig.get(key, default)
    return getattr(sig, key, default)


def _f(v: Any, d: int = 2) -> str:
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def _pct(v: Any) -> str:
    try:
        x = float(v)
        if x <= 1.0:
            return f"{x * 100:.0f}%"
        return f"{x:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _product(sig: Any) -> str:
    return _g(sig, "drug") or _g(sig, "product_name") or "this product"


def _event(sig: Any) -> str:
    md = _g(sig, "meddra") or {}
    if isinstance(md, dict) and md.get("pt"):
        return md["pt"]
    return _g(sig, "symptom") or _g(sig, "event_term") or "this event"


def _n(sig: Any) -> int:
    try:
        return int(_g(sig, "post_count") or _g(sig, "ae_count") or 0)
    except (TypeError, ValueError):
        return 0


def build_feature_tour(sig: Any) -> list[dict[str, str]]:
    """Ordered walkthrough of features present on this signal."""
    tour: list[dict[str, str]] = []
    product = _product(sig)
    event = _event(sig)
    n = _n(sig)

    tour.append({
        "id": "remine",
        "title": "Remine (find more similar posts)",
        "what_it_is": (
            "Remine re-searches your social-listening archive for posts that look like "
            "this product-event story, including optional product exclusions so you can "
            "check whether the pattern still holds without a confounding brand."
        ),
        "what_numbers_say": (
            f"This signal currently rests on {n} adverse-event-flagged post"
            f"{'' if n == 1 else 's'} mentioning {product} with {event}."
        ),
        "so_what": (
            "Use Remine when you want more raw patient language to read — it does not "
            "by itself prove the drug or device caused the event."
        ),
    })

    prr = _g(sig, "prr")
    ror = _g(sig, "ror")
    chi2 = _g(sig, "chi_square") if _g(sig, "chi_square") is not None else _g(sig, "chi2")
    strength = _g(sig, "strength") or "WEAK"
    if prr is not None or ror is not None:
        meaning = (
            f"PRR {_f(prr)} means this pair shows up about {_f(prr)}x as often as you would "
            f"expect from the rest of the database. ROR {_f(ror)} is a similar odds-based "
            f"view. chi-square {_f(chi2)} asks whether that excess is unlikely to be random "
            f"(higher = more surprising)."
        )
        try:
            prr_f, chi_f = float(prr or 0), float(chi2 or 0)
        except (TypeError, ValueError):
            prr_f, chi_f = 0.0, 0.0
        if prr_f >= 2 and chi_f >= 4 and n >= 3:
            so = (
                "By classic screening rules this looks like a STRONG disproportionality "
                "flag — still a screen, not a confirmed causal finding."
            )
        elif prr_f >= 1.5 and n >= 2:
            so = "This is a MODERATE statistical nudge — worth reading, not panicking."
        else:
            so = "The association is statistically WEAK or sparse — treat as exploratory."
        tour.append({
            "id": "disproportionality",
            "title": "Disproportionality (PRR, ROR, chi-square)",
            "what_it_is": (
                "A 2x2 contingency check: how often this product+event appears versus "
                "everything else. Think of it as an 'is this unusually common?' smoke alarm."
            ),
            "what_numbers_say": meaning + f" Current tier: {strength}.",
            "so_what": so,
        })

    eb05 = _g(sig, "eb05")
    ic025 = _g(sig, "ic025")
    if eb05 is not None or ic025 is not None:
        tour.append({
            "id": "bayesian",
            "title": "Bayesian shrinkage (EB05 / IC025)",
            "what_it_is": (
                "When case counts are small, raw PRR can look scary by chance. EBGM/EB05 "
                "and BCPNN IC025 pull extreme ratios toward the average and report a "
                "cautious lower bound."
            ),
            "what_numbers_say": (
                f"EB05 = {_f(eb05)} (FDA-style screen often looks for >=2). "
                f"IC025 = {_f(ic025)} (UMC-style screen often looks for >0)."
            ),
            "so_what": (
                "If PRR looks strong but EB05/IC025 do not, small-number inflation is "
                "likely — do not escalate on PRR alone."
            ),
        })

    spike = bool(_g(sig, "spike_flag") or _g(sig, "spike"))
    trend = _g(sig, "trend_score")
    if trend is None:
        trend = _g(sig, "trend_slope")
    spike_z = _g(sig, "spike_z")
    if spike or trend is not None:
        tour.append({
            "id": "trend",
            "title": "Trend & spike detection",
            "what_it_is": (
                "Daily mention counts are checked for a rising pattern and for a recent "
                "day that is unusually high versus history (z-score)."
            ),
            "what_numbers_say": (
                f"Spike flag: {'YES — recent day looks anomalous' if spike else 'no'}"
                f"{f' (z={_f(spike_z, 1)})' if spike_z is not None else ''}. "
                f"Trend score: {_f(trend, 4)} (higher/positive = rising mentions)."
            ),
            "so_what": (
                "A spike means talk is suddenly louder — real safety issue, news cycle, "
                "or bot wave. Always check Trust and Remine posts."
            ),
        })

    maxsprt = _g(sig, "maxsprt") or {}
    if not isinstance(maxsprt, dict):
        maxsprt = {}
    llr = maxsprt.get("llr") if maxsprt.get("llr") is not None else _g(sig, "maxsprt_llr")
    crossed = bool(maxsprt.get("crossed") or _g(sig, "maxsprt_crossed"))
    if llr is not None or crossed:
        cv = maxsprt.get("critical_value") or maxsprt.get("cv")
        tour.append({
            "id": "maxsprt",
            "title": "MaxSPRT sequential surveillance",
            "what_it_is": (
                "A continuous keep-looking-until-evidence-is-strong-enough test "
                "(Poisson MaxSPRT), used in vaccine and drug safety surveillance."
            ),
            "what_numbers_say": (
                f"Log-likelihood ratio (LLR) = {_f(llr)}. Critical boundary ~ {_f(cv)}. "
                f"{'Boundary CROSSED — sequential alarm is on.' if crossed else 'Still below the stop boundary.'}"
            ),
            "so_what": (
                "Crossing MaxSPRT is a formal statistical alarm on accumulating data — "
                "still based on social counts here, not validated ICSRs."
            ),
        })

    hr = _g(sig, "hr")
    hr_detail = _g(sig, "hr_detail") or {}
    if not isinstance(hr_detail, dict):
        hr_detail = {}
    if hr is None:
        hr = hr_detail.get("hr")
    hr_ci = _g(sig, "hr_ci") or []
    if not isinstance(hr_ci, (list, tuple)):
        hr_ci = [hr_detail.get("hr_lo"), hr_detail.get("hr_hi")]
    if hr is not None:
        lo = hr_ci[0] if len(hr_ci) > 0 else hr_detail.get("hr_lo")
        hi = hr_ci[1] if len(hr_ci) > 1 else hr_detail.get("hr_hi")
        elevated = bool(_g(sig, "hr_elevated"))
        tour.append({
            "id": "cox",
            "title": "Cox proportional hazards (time-to-event)",
            "what_it_is": (
                "Compares how quickly the event appears after product mention versus a "
                "baseline — a survival-analysis style relative risk over time."
            ),
            "what_numbers_say": (
                f"Hazard ratio (HR) ~ {_f(hr)}. Rough 95% interval: {_f(lo)}-{_f(hi)}. "
                f"{'Marked elevated (lower CI > 1).' if elevated else 'Not marked as elevated.'} "
                "HR > 1 means faster/more event timing associated with the product in this model."
            ),
            "so_what": (
                "HR is not proof of causation; confounding is large. Use it as a timing "
                "lens next to PRR and triangulation."
            ),
        })

    calib = _g(sig, "calibration") or {}
    if not isinstance(calib, dict):
        calib = {}
    e_value = calib.get("e_value") if calib.get("e_value") is not None else _g(sig, "e_value")
    cal_p = _g(sig, "calibrated_p")
    if e_value is not None or cal_p is not None or calib:
        tour.append({
            "id": "calibration",
            "title": "Sensitivity / E-value (how hard is confounding?)",
            "what_it_is": (
                "Asks how strong an unmeasured confounder would need to be to explain away "
                "the observed association, plus empirical-null calibration of the p-value."
            ),
            "what_numbers_say": (
                f"E-value ~ {_f(e_value)}. Calibrated p ~ {_f(cal_p, 4)}. "
                f"Survives calibration: {bool(_g(sig, 'calibrated_signal'))}."
            ),
            "so_what": (
                "Low E-value means a modest confounder could erase the signal — stay humble "
                "in benefit-risk language."
            ),
        })

    label_f = _g(sig, "label_filter") or {}
    novelty = None
    if isinstance(label_f, dict) and label_f:
        novelty = label_f.get("tag") or label_f.get("novelty_tier") or label_f.get("novelty")
    if not novelty:
        novelty = _g(sig, "label_novelty")
    if novelty and novelty != "unknown":
        weber = (label_f.get("weber") if isinstance(label_f, dict) else None) or {}
        gates = (label_f.get("alert_gates") if isinstance(label_f, dict) else None) or {}
        tour.append({
            "id": "label_filter",
            "title": "Label vs novel (in-label / unexpected)",
            "what_it_is": (
                "Compares the event to what is already written in the product label "
                "(DailyMed/openFDA when online; local lexicon offline). Weber-style "
                "gates can raise the bar for alerts near launch windows."
            ),
            "what_numbers_say": (
                f"Status: {novelty}. "
                f"In-label: {(label_f or {}).get('is_in_label') if isinstance(label_f, dict) else '—'}. "
                f"Weber adjusted: {gates.get('weber_adjusted', weber.get('weber_adjusted', '—'))}. "
                f"Effective PRR gate >= {_f(gates.get('prr_min'))}."
            ),
            "so_what": (
                "NOVEL / unexpected findings usually deserve more urgency than well-known "
                "labeled effects — unless severity or spike is extreme."
            ),
        })

    who = _g(sig, "who_umc")
    who_score = _g(sig, "who_umc_score")
    causality_block = _g(sig, "causality_assessment")
    naranjo = _g(sig, "naranjo") or {}
    if isinstance(causality_block, dict):
        who_blk = causality_block.get("who_umc") or {}
        if isinstance(who_blk, dict) and who_blk.get("category"):
            who = who or who_blk.get("category")
            who_score = who_score if who_score is not None else who_blk.get("score")
        if causality_block.get("naranjo"):
            naranjo = causality_block.get("naranjo") or naranjo
    if not isinstance(naranjo, dict):
        naranjo = {}
    if who or naranjo.get("category"):
        tour.append({
            "id": "causality",
            "title": "Causality (WHO-UMC + Naranjo)",
            "what_it_is": (
                "Structured checklists used by PV teams: Did the timing fit? Did stopping "
                "help (dechallenge)? Did restarting worsen (rechallenge)? Any other cause?"
            ),
            "what_numbers_say": (
                f"WHO-UMC category: {who or '—'} (score {_f(who_score)}). "
                f"Naranjo: {naranjo.get('category') or '—'} "
                f"(score {_f(naranjo.get('score'), 0)}). "
                "Certain/Probable/Definite lean toward drug-related; Unlikely/Unassessable "
                "mean evidence is thin or contradictory."
            ),
            "so_what": (
                "Social text often lacks dechallenge/rechallenge detail, so Possible or "
                "Unassessable is common — that is uncertainty, not innocence."
            ),
        })

    tri = _g(sig, "triangulation") or {}
    if isinstance(tri, dict) and (tri.get("urgency_tier") or tri.get("pillars") or tri.get("agreement")):
        pillars = tri.get("pillars") or []
        pillar_bits = []
        for p in pillars:
            if isinstance(p, dict):
                pillar_bits.append(
                    f"{p.get('name') or p.get('pillar') or '?'}: "
                    f"{'pass' if p.get('passed') else 'fail'} (score {_f(p.get('score'))})"
                )
        tour.append({
            "id": "triangulation",
            "title": "Evidence triangulation (social x FAERS/MAUDE x RWD)",
            "what_it_is": (
                "Checks whether independent lenses agree: public social talk, "
                "US FAERS/MAUDE spontaneous reports, and any local real-world / OMOP-style "
                "counts. Agreement raises confidence; conflict raises caution."
            ),
            "what_numbers_say": (
                f"Badge: {tri.get('badge') or tri.get('agreement') or '—'}. "
                f"Urgency: {tri.get('urgency_tier') or '—'}. "
                f"Pillars passed: {tri.get('n_pillars_passed', '—')}/3. "
                f"Triangulated risk score: {_f(tri.get('triangulated_risk_score'))}. "
                + (" | ".join(pillar_bits) if pillar_bits else "")
            ),
            "so_what": (
                "Social-only signals need more caution. Concordant social + FAERS is "
                "stronger for prioritization (still not a regulatory conclusion)."
            ),
        })

    comp = _g(sig, "completeness_detail") or {}
    mean_c = None
    if isinstance(comp, dict):
        mean_c = comp.get("mean_completeness")
    if mean_c is None:
        mean_c = _g(sig, "completeness")
    if mean_c is not None:
        tour.append({
            "id": "completeness",
            "title": "Report completeness (vigiGrade-style)",
            "what_it_is": (
                "Scores how much useful clinical detail is in the supporting posts "
                "(dose, timing, outcome, etc.) — documentation quality, not causality."
            ),
            "what_numbers_say": (
                f"Mean completeness {_f(mean_c)} "
                f"(grade {(comp or {}).get('grade') if isinstance(comp, dict) else '—'}). "
                f"{'Well-documented' if (_g(sig, 'well_documented') or (isinstance(comp, dict) and comp.get('well_documented'))) else 'Poorly documented'} "
                f"across {(comp or {}).get('n_posts', n) if isinstance(comp, dict) else n} posts."
            ),
            "so_what": (
                "Low completeness means you are flying half-blind — ask for richer narratives "
                "or FAERS cases before strong action."
            ),
        })

    trust = _g(sig, "trust_score")
    trust_label = _g(sig, "trust_label")
    if trust is not None or trust_label:
        tour.append({
            "id": "trust",
            "title": "Trust & Sybil risk (are the posts real?)",
            "what_it_is": (
                "Heuristics for coordinated/bot-like or low-trust posting that can inflate "
                "mention counts without a true patient safety story."
            ),
            "what_numbers_say": (
                f"Trust score: {_f(trust)}. Label: {trust_label or '—'}. "
                "high = more credible discourse; sybil/low = treat counts skeptically."
            ),
            "so_what": (
                "If the statistical alarm is loud but trust is poor, investigate manipulation "
                "before escalating to medical review."
            ),
        })

    life = _g(sig, "lifecycle_status") or _g(sig, "lifecycle_state") or _g(sig, "lifecycle")
    priority = _g(sig, "priority_score")
    if life or priority is not None:
        tour.append({
            "id": "lifecycle",
            "title": "Signal lifecycle & priority",
            "what_it_is": (
                "Where this pair sits in the review workflow (new -> under review -> closed) "
                "and a composite priority score for triage queues."
            ),
            "what_numbers_say": (
                f"Lifecycle: {life or '—'}. Priority score: {_f(priority)}. "
                "Higher priority = jump the queue for human eyes."
            ),
            "so_what": (
                "Priority is a workload tool — it encodes urgency heuristics, not a final "
                "medical judgment."
            ),
        })

    thread = _g(sig, "thread_score") or {}
    if isinstance(thread, dict) and thread.get("rag"):
        tour.append({
            "id": "thread_score",
            "title": "Evidence thread score (RAG)",
            "what_it_is": (
                "Summarizes corroborating vs contradicting posts and attaches a Red/Amber/Green "
                "confidence style score for the discussion thread."
            ),
            "what_numbers_say": (
                f"RAG={thread.get('rag')}, confidence {_pct(thread.get('confidence'))}. "
                f"Corroborating={thread.get('corroborating')}, "
                f"contradicting={thread.get('contradicting')}, "
                f"AE-flagged={thread.get('ae_flagged')} of n={thread.get('n_posts')}."
            ),
            "so_what": (
                "Red with many corroborating AE posts = louder patient signal; lots of "
                "contradiction = dig into mixed experiences."
            ),
        })

    if _g(sig, "mechanism_plausible") or _g(sig, "mechanism"):
        mech = _g(sig, "mechanism") or {}
        if not isinstance(mech, dict):
            mech = {}
        tour.append({
            "id": "mechanism",
            "title": "Biological mechanism plausibility",
            "what_it_is": (
                "Does a known pharmacology or device failure mode make this event biologically "
                "believable?"
            ),
            "what_numbers_say": (
                f"Plausible: {bool(_g(sig, 'mechanism_plausible'))}. "
                f"{mech.get('mechanism_explanation') or mech.get('target_or_moa') or mech.get('summary') or 'See mechanism panel.'}"
            ),
            "so_what": (
                "Plausible mechanism raises prior belief; absence of mechanism does not rule "
                "out rare idiosyncratic reactions."
            ),
        })

    if _g(sig, "pgx_actionable") or _g(sig, "pgx"):
        pgx = _g(sig, "pgx") or {}
        tour.append({
            "id": "pgx",
            "title": "Pharmacogenomics (PGx)",
            "what_it_is": (
                "Known gene-drug interactions that can make some patients more susceptible "
                "to this kind of harm."
            ),
            "what_numbers_say": (
                str(pgx) if not isinstance(pgx, dict)
                else f"Gene {pgx.get('gene')} {pgx.get('allele')} ({pgx.get('phenotype')}). "
                     f"Recommendation: {pgx.get('recommendation') or '—'}."
            ),
            "so_what": "May support targeted risk minimization (testing, dose, contraindication).",
        })

    if _g(sig, "class_effect") or _g(sig, "class_info") or _g(sig, "active_comparator"):
        class_info = _g(sig, "class_info") or {}
        ac = _g(sig, "active_comparator") or {}
        tour.append({
            "id": "class_effect",
            "title": "Class effect / active comparator",
            "what_it_is": (
                "Checks whether sibling products in the same class show the same event, "
                "and compares against an active comparator when available."
            ),
            "what_numbers_say": (
                f"Class effect: {bool(_g(sig, 'class_effect'))}. "
                f"{(class_info.get('class_name') if isinstance(class_info, dict) else '') or ''} "
                f"Stands out in class: {bool(_g(sig, 'stands_out_in_class'))}. "
                f"AC-ROR: {_f((ac or {}).get('ac_ror') if isinstance(ac, dict) else None)}."
            ),
            "so_what": (
                "Class-wide patterns suggest a shared mechanism; product-specific patterns "
                "suggest formulation, device design, or use-pattern issues."
            ),
        })

    smq = _g(sig, "smq") or []
    if smq:
        names = [m.get("smq") for m in smq[:4] if isinstance(m, dict) and m.get("smq")]
        tour.append({
            "id": "smq",
            "title": "SMQ (Standardised MedDRA Query)",
            "what_it_is": (
                "Groups related preferred terms into a syndrome-level safety topic "
                "so you do not miss a pattern spread across codes."
            ),
            "what_numbers_say": f"Matched SMQ(s): {', '.join(names) or 'see panel'}.",
            "so_what": "Useful for spotting class-of-event themes beyond a single PT.",
        })

    if _g(sig, "boxed_warning"):
        boxed = _g(sig, "boxed") or {}
        tour.append({
            "id": "boxed",
            "title": "Boxed / black-box warning context",
            "what_it_is": "US labels may already carry the strongest warning for related risks.",
            "what_numbers_say": (
                f"Boxed warning present. Covers this event: "
                f"{(boxed or {}).get('covers_event') if isinstance(boxed, dict) else '—'}. "
                f"Topics: {', '.join((boxed or {}).get('topics', []) if isinstance(boxed, dict) else []) or '—'}."
            ),
            "so_what": "Known boxed risks still matter if volume, severity, or novelty of presentation changes.",
        })

    if _g(sig, "spatial_cluster") or _g(sig, "spatial"):
        spatial = _g(sig, "spatial") or {}
        tour.append({
            "id": "spatial",
            "title": "Spatial / geographic clustering",
            "what_it_is": "Looks for regional hotspots in mention geography.",
            "what_numbers_say": (
                f"Hotspot: {(spatial or {}).get('hotspot') if isinstance(spatial, dict) else '—'}. "
                f"RR~{_f((spatial or {}).get('rr') if isinstance(spatial, dict) else None, 1)}."
            ),
            "so_what": "Clusters can reflect true local risk, language communities, or media events.",
        })

    if _g(sig, "is_vaccine") or _g(sig, "vaccine"):
        vaccine = _g(sig, "vaccine") or {}
        tour.append({
            "id": "vaccine",
            "title": "Vaccine AESI / Brighton context",
            "what_it_is": (
                "For vaccines, adverse events of special interest and Brighton Collaboration "
                "case definitions add structured seriousness context."
            ),
            "what_numbers_say": (
                f"AESI: {_g(sig, 'aesi') or (vaccine.get('aesi') if isinstance(vaccine, dict) else None) or '—'}. "
                "See vaccine panel for Brighton level / SCRI notes."
            ),
            "so_what": "Use AESI/Brighton panels to align with vaccine-safety review norms.",
        })

    fda = _g(sig, "fda_evidence") or {}
    if isinstance(fda, dict) and (fda.get("available") or fda.get("report_count") or fda.get("count") or fda.get("source")):
        tour.append({
            "id": "faers_maude",
            "title": "openFDA FAERS / MAUDE corroboration",
            "what_it_is": (
                "US spontaneous reporting databases (drugs = FAERS, devices = MAUDE)."
            ),
            "what_numbers_say": (
                f"Available: {fda.get('available')}. Source: {fda.get('source') or '—'}. "
                f"Related report count: {fda.get('report_count', fda.get('count', '—'))}."
            ),
            "so_what": (
                "Presence supports that regulators already see related reports; "
                "absence does not prove safety."
            ),
        })

    lit = _g(sig, "literature") or {}
    if isinstance(lit, dict) and lit.get("available"):
        tour.append({
            "id": "literature",
            "title": "Literature (PubMed-style)",
            "what_it_is": "Indexed articles mentioning this product-event pair when enrichment succeeded.",
            "what_numbers_say": f"About {lit.get('count', '—')} indexed hit(s).",
            "so_what": "Published cases raise prior concern but publication bias cuts both ways.",
        })

    recall = _g(sig, "recall") or {}
    if isinstance(recall, dict) and recall.get("available"):
        tour.append({
            "id": "recall",
            "title": "FDA recalls / enforcement",
            "what_it_is": "OpenFDA enforcement/recall records linked to the product when available.",
            "what_numbers_say": f"{recall.get('count', 0)} record(s) on file.",
            "so_what": "Recalls are product-quality or labeling actions — related but not the same as an AE signal.",
        })

    br_verdict = _g(sig, "br_verdict")
    br = _g(sig, "benefit_risk") or {}
    if br_verdict or (isinstance(br, dict) and br):
        tour.append({
            "id": "benefit_risk",
            "title": "Benefit-risk snapshot",
            "what_it_is": (
                "A crude composite balancing indication benefit cues against harm signals "
                "for triage discussion — not a CHMP/FDA decision."
            ),
            "what_numbers_say": (
                f"Verdict: {br_verdict or '—'}. "
                f"NNT={_f((br or {}).get('nnt') if isinstance(br, dict) else None, 0)}, "
                f"NNH={_f((br or {}).get('nnh') if isinstance(br, dict) else None, 0)}."
            ),
            "so_what": "Use as a conversation starter with medical and benefit-risk committees.",
        })

    tour.append({
        "id": "ontology",
        "title": "Product ontology (brand <-> generic <-> codes)",
        "what_it_is": (
            "Maps brand names to generics, ATC/RxNorm (drugs) or GMDN/FDA product codes "
            "(devices) so the same molecule/device is not split across aliases."
        ),
        "what_numbers_say": (
            f"Signal product string: {product}. "
            f"ATC: {_g(sig, 'drug_atc') or '—'}. "
            f"GMDN: {_g(sig, 'device_gmdn') or '—'}."
        ),
        "so_what": "Wrong identity = wrong signal. Always confirm coding before escalation.",
    })

    tour.append({
        "id": "four_gate",
        "title": "4-gate adverse-event detector",
        "what_it_is": (
            "Every supporting post is scored with four yes/no gates: (1) product entity "
            "present, (2) symptom/malfunction entity present, (3) NEGATIVE sentiment, "
            "(4) symptom is not negated. Confidence blends sentiment magnitude "
            "(ae_confidence ~ |sentiment|*0.9 + 0.1)."
        ),
        "what_numbers_say": (
            f"{n} post(s) passed the AE path for {product} + {event}. "
            "Open any supporting post to see the gate trace (which gates fired)."
        ),
        "so_what": (
            "This is how VigilAI decides a social post is an AE candidate. Gate failures "
            "explain false positives (e.g. 'not nausea' fails negation gate)."
        ),
    })

    tour.append({
        "id": "disclaimer",
        "title": "How to read this page (important)",
        "what_it_is": (
            "VigilAI is a prototype social-listening + openFDA triangulation workbench. "
            "MedDRA coding is an open surrogate; E2B exports are demo templates."
        ),
        "what_numbers_say": (
            "None of these panels alone equals a confirmed adverse drug reaction or device "
            "incident for regulatory submission."
        ),
        "so_what": (
            "Use the Copilot to translate numbers; use medical review to decide action. "
            "Not for clinical use."
        ),
    })

    return tour


def tour_as_narrative(tour: list[dict[str, str]], bottom: dict | None = None) -> str:
    parts = []
    if bottom:
        parts.append(
            f"BOTTOM LINE ({bottom.get('label')}): {bottom.get('headline')}\n"
            f"Next step: {bottom.get('next_step')}\n"
        )
    parts.append(
        "Per-panel takeaways (technical panels remain the source of truth):\n"
    )
    for i, step in enumerate(tour, 1):
        take = step.get("takeaway") or step.get("so_what") or ""
        parts.append(
            f"{i}. [{step.get('verdict', 'neutral').upper()}] {step['title']}\n"
            f"   Takeaway: {take}\n"
        )
    return "\n".join(parts)


def attach_feature_tour(assessment: dict, sig: Any) -> dict:
    """Return assessment with feature_tour + bottom_line + plain_english_tour."""
    from .copilot_verdicts import apply_verdicts

    tour = build_feature_tour(sig)
    tour, bottom = apply_verdicts(tour, sig)
    out = dict(assessment or {})
    out["feature_tour"] = tour
    out["bottom_line"] = bottom
    out["plain_english_tour"] = tour_as_narrative(tour, bottom)
    out["audience_note"] = (
        "Read the bottom line first. Each panel below is tagged concerning / mixed / "
        "reassuring so you do not need to decode the jargon. Technical charts stay unchanged."
    )
    return out


# Fallback glosses when a metric is not populated on this particular signal
_GLOSSARY = {
    "remine": (
        "Remine (find more similar posts)",
        "Re-searches the archive for posts like this product-event story.",
        "Use it to gather more patient language; it does not prove causation.",
    ),
    "disproportionality": (
        "Disproportionality (PRR, ROR, chi-square)",
        "A 2x2 check of whether this product+event is unusually common vs the rest of the database.",
        "It is a smoke alarm for screening — not a confirmed causal finding.",
    ),
    "bayesian": (
        "Bayesian shrinkage (EB05 / IC025)",
        "Pulls extreme ratios toward the average when counts are small.",
        "If PRR looks scary but EB05/IC025 do not, distrust small-N inflation.",
    ),
    "trend": (
        "Trend and spike detection",
        "Looks for rising daily mentions and anomalous recent days (z-score).",
        "A spike can be real risk, news, or bots — check Trust too.",
    ),
    "maxsprt": (
        "MaxSPRT sequential surveillance",
        "Keeps testing as data accumulate and alarms when LLR crosses a boundary.",
        "A crossed boundary is a formal statistical alarm on social counts here.",
    ),
    "cox": (
        "Cox proportional hazards (time-to-event)",
        "Estimates whether the event appears faster after product mention (hazard ratio).",
        "HR > 1 means faster timing in the model — still not proof of causation.",
    ),
    "calibration": (
        "Sensitivity / E-value",
        "Asks how strong a hidden confounder must be to erase the association.",
        "Low E-value means modest bias could explain the finding away.",
    ),
    "label_filter": (
        "Label vs novel",
        "Compares the event to what the product label already lists.",
        "Novel/unexpected usually deserves more urgency than known labeled effects.",
    ),
    "causality": (
        "Causality (WHO-UMC + Naranjo)",
        "Checklist for timing, dechallenge, rechallenge, and alternate causes.",
        "Possible/Unassessable often means missing detail in social text.",
    ),
    "triangulation": (
        "Evidence triangulation",
        "Checks whether social, FAERS/MAUDE, and RWD lenses agree.",
        "Agreement raises priority; social-only needs more caution.",
    ),
    "completeness": (
        "Report completeness (vigiGrade-style)",
        "Scores how much clinical detail is documented in supporting posts.",
        "Low completeness means weak documentation — not weak causality per se.",
    ),
    "trust": (
        "Trust and Sybil risk",
        "Heuristics for bot-like or coordinated posting.",
        "Loud stats + low trust = investigate manipulation first.",
    ),
    "lifecycle": (
        "Signal lifecycle and priority",
        "Workflow state and triage priority for human review.",
        "Priority is a queue tool, not a final medical judgment.",
    ),
    "thread_score": (
        "Evidence thread score",
        "Red/Amber/Green summary of corroborating vs contradicting posts.",
        "Use it to see how mixed the patient stories are.",
    ),
    "mechanism": (
        "Biological mechanism plausibility",
        "Whether pharmacology or device failure modes make the event believable.",
        "Plausible mechanism raises prior belief; absence does not rule out rare reactions.",
    ),
    "pgx": (
        "Pharmacogenomics (PGx)",
        "Gene-drug interactions that can raise susceptibility in some patients.",
        "May support testing or dosing risk-minimization.",
    ),
    "class_effect": (
        "Class effect / active comparator",
        "Whether sibling products show the same event.",
        "Class-wide patterns suggest shared mechanism.",
    ),
    "smq": (
        "SMQ (Standardised MedDRA Query)",
        "Groups related terms into a syndrome-level safety topic.",
        "Helps spot patterns spread across multiple codes.",
    ),
    "boxed": (
        "Boxed warning context",
        "Strongest US label warning for related risks.",
        "Known boxed risks still matter if volume or presentation changes.",
    ),
    "spatial": (
        "Spatial clustering",
        "Looks for geographic hotspots in mentions.",
        "Can reflect true local risk, language communities, or media events.",
    ),
    "vaccine": (
        "Vaccine AESI / Brighton",
        "Structured vaccine-safety seriousness context.",
        "Aligns review with vaccine-safety norms.",
    ),
    "faers_maude": (
        "openFDA FAERS / MAUDE",
        "US spontaneous reports for drugs (FAERS) or devices (MAUDE).",
        "Presence supports regulatory awareness; absence is not proof of safety.",
    ),
    "literature": (
        "Literature",
        "Indexed articles for the product-event pair when enrichment succeeded.",
        "Publication bias cuts both ways.",
    ),
    "recall": (
        "FDA recalls / enforcement",
        "OpenFDA recall or enforcement records for the product.",
        "Related to quality/labeling actions, not identical to an AE signal.",
    ),
    "benefit_risk": (
        "Benefit-risk snapshot",
        "Crude balance of benefit vs harm for triage discussion.",
        "Not a regulatory benefit-risk decision.",
    ),
    "ontology": (
        "Product ontology",
        "Maps brand, generic, and coding systems so aliases do not split the signal.",
        "Wrong identity = wrong signal.",
    ),
    "four_gate": (
        "4-gate adverse-event detector",
        "Requires product entity, symptom/malfunction, negative sentiment, and non-negated symptom.",
        "Gate traces explain why a post was or was not counted as an AE candidate.",
    ),
    "disclaimer": (
        "How to read this page",
        "Prototype social-listening + openFDA triangulation workbench.",
        "Not for clinical use or regulatory submission.",
    ),
}


def answer_question(sig: Any, question: str, tour: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Offline-first Q&A over the feature tour + key signal fields."""
    from .copilot_verdicts import apply_verdicts, build_bottom_line

    q = (question or "").strip()
    if not q:
        return {
            "answer": (
                "Ask for a conclusion — e.g. 'Is this bad?', 'Should I worry?', "
                "'What's the bottom line?', or name a metric like PRR / EB05 / MaxSPRT."
            ),
            "matched_feature": None,
            "source": "deterministic",
        }
    if tour is None:
        tour, _ = apply_verdicts(build_feature_tour(sig), sig)
    elif tour and not tour[0].get("takeaway"):
        tour, _ = apply_verdicts(tour, sig)
    q_l = q.lower()

    if re.search(r"bottom.?line|should i worry|is (this|it) (bad|good|safe|serious|okay|ok)|overall|conclude|conclusion|what do (you|i) (think|do)|summar", q_l):
        bottom = build_bottom_line(sig)
        bits = [f"**{bottom['label']}**", "", bottom["headline"], ""]
        if bottom.get("alarms"):
            bits.append("Why it looks concerning:")
            bits.extend(f"• {a}" for a in bottom["alarms"])
            bits.append("")
        if bottom.get("coolers"):
            bits.append("Why you should not panic yet:")
            bits.extend(f"• {c}" for c in bottom["coolers"])
            bits.append("")
        bits.append(f"**What to do:** {bottom['next_step']}")
        return {
            "answer": "\n".join(bits),
            "matched_feature": "bottom_line",
            "bottom_line": bottom,
            "source": "deterministic",
        }

    hints = [
        (r"\bremine|re-?mine|similar post", "remine"),
        (r"\bprr|ror|chi|disproport|contingen|strength|strong|moderate|weak", "disproportionality"),
        (r"\beb05|ebgm|ic025|bcpnn|bayes|shrink", "bayesian"),
        (r"\bspike|trend|slope|z-?score", "trend"),
        (r"\bmaxsprt|llr|sequential|kulldorff", "maxsprt"),
        (r"\bcox|hazard|\bhr\b|survival|time-?to-?event", "cox"),
        (r"\be-?value|calibrat|confound|bias factor", "calibration"),
        (r"\blabel|novel|weber|dailymed|in-?label|unexpected", "label_filter"),
        (r"\bnaranjo|who-?umc|causalit|dechallenge|rechallenge", "causality"),
        (r"\btriangul|faers|maude|concord|agree|pillar", "triangulation"),
        (r"\bcompleteness|vigigrade|document", "completeness"),
        (r"\btrust|sybil|bot|fake", "trust"),
        (r"\blifecycle|priority|triage|queue|what should i|recommend|next step|escalate", "lifecycle"),
        (r"\bthread|rag\b|corroborat|hierarch", "thread_score"),
        (r"\bmechanism|biolog|pathway", "mechanism"),
        (r"\bpgx|pharma.?genom|gene", "pgx"),
        (r"\bclass effect|comparator|sibling|atc class", "class_effect"),
        (r"\bsmq|standardised meddra|syndrome", "smq"),
        (r"\bboxed|black.?box", "boxed"),
        (r"\bspatial|geo|region|cluster|hotspot", "spatial"),
        (r"\bvaccine|aesi|brighton", "vaccine"),
        (r"\bontology|generic|brand|atc|rxnorm|gmdn", "ontology"),
        (r"\b4-?gate|four.?gate|gate trace|ae detect|sentiment|negat", "four_gate"),
        (r"\bbenefit|risk.?benefit|\bnnt\b|\bnnh\b", "benefit_risk"),
        (r"\bliterature|pubmed|paper", "literature"),
        (r"\brecall|enforcement", "recall"),
        (r"\bdisclaimer|clinical use|prototype", "disclaimer"),
    ]

    matched_id = None
    for pattern, fid in hints:
        if re.search(pattern, q_l):
            matched_id = fid
            break

    if not matched_id:
        best, best_n = None, 0
        tokens = set(re.findall(r"[a-z0-9]+", q_l))
        for step in tour:
            bag = set(re.findall(r"[a-z0-9]+", (step["title"] + " " + step["id"]).lower()))
            n_hit = len(tokens & bag)
            if n_hit > best_n:
                best_n, best = n_hit, step["id"]
        if best_n >= 1:
            matched_id = best

    step = next((s for s in tour if s["id"] == matched_id), None) if matched_id else None

    if step:
        take = step.get("takeaway") or step.get("so_what") or ""
        verdict = (step.get("verdict") or "neutral").upper()
        answer = (
            f"**{step['title']}** — {verdict}\n\n"
            f"**Bottom line for you:** {take}\n\n"
            f"{step.get('what_it_is', '')}\n\n"
            f"**Numbers on this signal:** {step.get('what_numbers_say', '')}"
        )
        return {"answer": answer, "matched_feature": step["id"], "source": "deterministic"}

    if matched_id and matched_id in _GLOSSARY:
        title, what, so = _GLOSSARY[matched_id]
        answer = (
            f"**{title}**\n\n{what}\n\n"
            f"**On this signal:** This panel is not populated (or not triggered) for the "
            f"current pair — the definition above still applies when you see it elsewhere.\n\n"
            f"**So what:** {so}"
        )
        return {"answer": answer, "matched_feature": matched_id, "source": "deterministic"}

    product = _product(sig)
    event = _event(sig)
    strength = _g(sig, "strength") or "—"
    answer = (
        f"I could not pin that to one panel. Quick overview: **{product}** with **{event}** "
        f"is currently tiered **{strength}** on {_n(sig)} AE-flagged posts. "
        f"Try asking about a specific metric (PRR, MaxSPRT, Cox HR, Naranjo, triangulation, "
        f"4-gate, Remine, completeness, trust). "
        f"There are {len(tour)} explained features in the tour."
    )
    return {"answer": answer, "matched_feature": None, "source": "deterministic"}
