"""End-to-end orchestration: ingest -> NLP -> analytics -> storage -> alerts.

Worldwide-first: each post is language-detected and translated to English before
NLP; drugs are normalized to generic + ATC; symptoms are standardized to MedDRA-style
PT/SOC; signals carry disproportionality, trend/spike, WHO-UMC causality, openFDA
evidence, regional spread, and an LLM (or deterministic) narrative.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from .analytics.causality import assess_causality, grade_severity
from .analytics.lifecycle import compute_priority
from .analytics.survival import compute_hazard_ratio
from .analytics.class_effect import (
    active_comparator_analysis,
    aggregate_class,
    atc_class_key,
    build_lookup as build_class_lookup,
    class_summary,
    read_across,
)
from .analytics.benefit_risk import assess as benefit_risk_assess
from .analytics.calibration import calibrate_signals, is_negative_control
from .analytics.completeness import dimensions_for_post, score_signal
from .analytics.disproportionality import compute_signals
from .analytics.knowledge_graph import build_graph
from .analytics.narrative import build_narrative
from .analytics.boxed_warnings import match as boxed_match
from .analytics.label_gap import assess_label_gap
from .analytics.mechanism import assess as mechanism_assess
from .analytics.pgx import match as pgx_match
from .analytics.smq import smqs_for_event
from .analytics.spatial import assess as spatial_assess
from .analytics.maxsprt import maxsprt_from_signal
from .analytics.trend import compute_trend
from .analytics.vaccine import assess as vaccine_assess, is_vaccine, summarize as vaccine_summary
from .evidence.fda import query_evidence
from .models import Alert, AuditLog, ProcessedPost, RawPost, Signal
from .nlp.ae_detector import detect_ae
from .nlp.devices import device_meta, is_known_device
from .nlp.drug_norm import canonical_product
from .nlp.text_normalize import canonical_event
from .nlp.entities import extract_entities
from .nlp.lexicons import atc_for
from .nlp.meddra import map_term
from .nlp.negation import detect_negation
from .nlp.pii import scrub
from .nlp.sentiment import analyze_sentiment
from .nlp.translation import translate_to_english

_COUNTRY_CODES = {
    "United States": "US", "Canada": "CA", "Germany": "DE", "United Kingdom": "GB",
    "France": "FR", "Italy": "IT", "India": "IN", "Japan": "JP", "Brazil": "BR",
    "Nigeria": "NG", "Australia": "AU",
}


# --------------------------------------------------------------------------- #
# Ingestion + NLP
# --------------------------------------------------------------------------- #
def ingest_posts(db: Session, posts: List[dict], use_transformer: bool | None = None,
                 use_presidio: bool | None = None, online_translation: bool | None = None,
                 project_id: int | None = None) -> int:
    from .projects.scope import current_project_id
    from .nlp.text_normalize import normalize_ingest_fields_sync
    from .nlp.content_dedupe import ContentDedupeGate
    from .privacy.hygiene import author_hash as hmac_author_hash, scrub_text as hygiene_scrub
    from .models import RawPost as _RawPost  # noqa: F401 — clarity for master bump

    if project_id is None:
        project_id = current_project_id()

    gate = ContentDedupeGate(project_id=project_id)
    try:
        gate.warm_from_db(db)
    except Exception:
        pass  # column may not exist until migrate_schema; still dedupe in-batch

    new_count = 0
    for p in posts:
        # Strict preprocessing: trim, synonym fold, region/product cleanup
        p = normalize_ingest_fields_sync(p)
        ext = str(p.get("external_id") or p.get("url") or p.get("body", "")[:40])
        pid = project_id if project_id is not None else p.get("project_id")
        dedupe_q = db.query(RawPost).filter(RawPost.external_id == ext)
        if pid is not None:
            dedupe_q = dedupe_q.filter(RawPost.project_id == pid)
        if dedupe_q.first():
            continue

        # Content-hash gate — before PII/NLP so syndicated copies never inflate DMA
        decision = gate.check(p)
        if decision["action"] == "skip_empty":
            continue
        if decision["action"] == "suppress_duplicate":
            master_id = decision.get("master_id")
            if master_id:
                master = db.get(RawPost, master_id)
                if master is not None:
                    master.duplicate_count = int(master.duplicate_count or 0) + 1
            continue

        original = p.get("body", "") or ""
        title_raw = p.get("title", "") or ""
        # Phase-1 privacy hygiene: standardized redaction tokens + HMAC author
        scrubbed_src, pii_types, _tokens = hygiene_scrub(original, use_presidio=use_presidio)
        scrubbed_title, pii_title, _ = hygiene_scrub(title_raw, use_presidio=use_presidio)
        pii_all = sorted(set(pii_types) | set(pii_title))
        # 2) worldwide: detect language + translate to English for NLP
        tr = translate_to_english(scrubbed_src, src=p.get("lang"), online=online_translation)
        from .nlp.stage1_sanitize import repair_scraped_text
        english = repair_scraped_text(tr["text"])
        # 3) only re-scrub when translation actually changed the text (names may
        #    surface differently in English); avoids a redundant NER pass otherwise.
        if tr["translated"] and english != scrubbed_src:
            english, pii2, _ = hygiene_scrub(english, use_presidio=use_presidio)
            pii_all = sorted(set(pii_all) | set(pii2))

        # Never persist raw handles — HMAC-SHA256(SYSTEM_SALT)
        ahash = hmac_author_hash(str(p.get("author") or p.get("username") or ""))

        raw = RawPost(
            project_id=pid,
            external_id=ext,
            platform=(f"{p.get('platform', 'google_news')}/{(p.get('news_source') or '')[:40]}"
                        if p.get("news_source")
                        else f"reddit/{p.get('subreddit')}" if p.get("subreddit")
                        else p.get("platform", "unknown")),
            product_type=p.get("product_type", "drug"),
            url=p.get("url", ""),
            author_hash=ahash,
            title=(scrubbed_title or "")[:500],
            body=english,
            body_original=scrubbed_src if tr["translated"] else None,
            lang=tr["lang"],
            lang_name=tr["lang_name"],
            translated=tr["translated"],
            region=p.get("region", "Global"),
            country=p.get("country"),
            pii_found=json.dumps(pii_all),
            posted_at=p.get("posted_at") or datetime.utcnow(),
            processed=False,
            content_hash=decision["content_hash"],
            duplicate_count=0,
        )
        db.add(raw)
        db.flush()
        gate.register_master(decision["content_hash"], raw.id)
        _process_raw(db, raw, use_transformer=use_transformer)
        new_count += 1
        if new_count % 40 == 0:
            db.commit()  # incremental commits keep the write lock short

    db.commit()
    gate.finish()
    return new_count


def reprocess_posts(db: Session, use_transformer: bool | None = None) -> int:
    """Re-run NLP over every stored raw post (applies current NER/stop-list rules).

    Deletes existing ProcessedPost rows and rebuilds them, so historical junk
    entities are purged without a full reseed. Caller should recompute_signals after.
    """
    db.query(ProcessedPost).delete()
    db.commit()
    count = 0
    for raw in db.query(RawPost).all():
        raw.processed = False
        _process_raw(db, raw, use_transformer=use_transformer)
        count += 1
        if count % 50 == 0:
            db.commit()
    db.commit()
    return count


def _process_raw(db: Session, raw: RawPost, use_transformer: bool | None = None) -> ProcessedPost:
    """NLP + pre-DB 4-gate ingest gateway — junk never reaches entities_json."""
    from .nlp.ingest_gateway import apply_ingest_gateway
    from .nlp.stage1_sanitize import repair_scraped_text

    # Align stored narrative with highlight offsets (scrape spacing / broken compounds)
    if raw.title:
        raw.title = repair_scraped_text(raw.title)[:500]
    if raw.body:
        raw.body = repair_scraped_text(raw.body)

    text = f"{raw.title or ''} {raw.body or ''}".strip()
    raw_entities = extract_entities(text, use_transformer=use_transformer)
    gated = apply_ingest_gateway(text, raw_entities)
    entities = gated["entities"]
    negation = gated["negation"]
    sentiment = analyze_sentiment(text)
    ae = detect_ae(entities, sentiment, negation)

    # Heal mis-tagged posts: if NLP found a known device product, mark as device.
    if any(
        d.get("is_device") or d.get("product_type") == "device" or is_known_device(
            d.get("normalized") or d.get("generic") or ""
        )
        for d in (entities.get("drugs") or [])
    ):
        raw.product_type = "device"

    # ae["gate_trace"] is a list of per-gate dicts — nest it, do not **spread
    gate_payload = {
        "ae_gates": ae.get("gate_trace") or [],
        "explainability": ae.get("explainability") or {},
        "unique_drug_count": ae.get("unique_drug_count"),
        "unique_symptom_count": ae.get("unique_symptom_count"),
        "ingest_gateway": gated.get("gateway_trace") or {},
    }

    processed = ProcessedPost(
        raw_id=raw.id,
        entities_json=json.dumps(entities),
        sentiment_label=sentiment["label"],
        sentiment_score=sentiment["score"],
        negation_json=json.dumps(negation),
        ae_flag=ae["ae_flag"],
        ae_confidence=ae["confidence"],
        ae_reason=ae["reason"],
        gate_trace_json=json.dumps(gate_payload),
    )
    db.add(processed)
    raw.processed = True
    db.flush()
    return processed


# --------------------------------------------------------------------------- #
# Signal recomputation
# --------------------------------------------------------------------------- #
def recompute_signals(db: Session, use_fda: bool = True, with_narrative: bool = True,
                      project_id: int | None = None) -> dict:
    from .projects.scope import current_project_id

    if project_id is None:
        project_id = current_project_id()

    # Heal legacy NULL-scoped signals so project-filtered UI can see them.
    heal_orphan_project_ids(db, default_project_id=project_id or 1)

    ae_q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
    )
    if project_id is not None:
        ae_q = ae_q.filter(RawPost.project_id == project_id)
    ae_rows = ae_q.all()

    sig_q = db.query(Signal)
    if project_id is not None:
        sig_q = sig_q.filter(Signal.project_id == project_id)
    prior = {
        (s.drug, s.symptom): {
            "detected_at": s.detected_at,
            "review_state": s.review_state,
            "reviewed_by": s.reviewed_by,
            "reviewed_at": s.reviewed_at,
            "lifecycle_status": s.lifecycle_status,
            "lifecycle_owner": s.lifecycle_owner,
            "lifecycle_notes": s.lifecycle_notes,
            "lifecycle_updated_at": s.lifecycle_updated_at,
        }
        for s in sig_q.all()
    }

    # Corpus baseline geographic distribution (counts of ALL AE reports by country
    # and region). This defines each area's EXPECTED share of reports, against which
    # the spatial scan statistic compares a signal's observed geographic spread.
    geo_baseline = {
        "country": dict(Counter(raw.country for _p, raw in ae_rows if raw.country)),
        "region": dict(Counter((raw.region or "Global") for _p, raw in ae_rows)),
    }

    reports: List[Tuple[str, str]] = []
    pair_meta: Dict[Tuple[str, str], dict] = {}
    # normalized symptom -> (pt, soc, soc_code); generic -> atc
    sym_meddra: Dict[str, dict] = {}
    drug_atc_map: Dict[str, str] = {}
    pair_product: Dict[Tuple[str, str], str] = {}
    pair_device: Dict[Tuple[str, str], dict] = {}
    # vigiGrade-style completeness dimensions per supporting post (processed.id -> dims).
    post_dims: Dict[int, dict] = {}

    # Map processed_post id -> posted_at for all AE posts (comparator pool for Cox PH)
    all_ae_post_times: Dict[int, datetime] = {}

    for processed, raw in ae_rows:
        if raw.posted_at:
            all_ae_post_times[processed.id] = raw.posted_at
        entities = json.loads(processed.entities_json or "{}")
        negation = json.loads(processed.negation_json or "{}")
        ptype_raw = getattr(raw, "product_type", None) or "drug"
        post_dims[processed.id] = dimensions_for_post(
            text=f"{raw.title or ''} {raw.body or ''}",
            entities=entities,
            negation=negation,
            sentiment={"label": processed.sentiment_label,
                       "score": processed.sentiment_score},
            country=raw.country,
        )
        # Product → entity flags (device entities override a mislabeled raw.product_type)
        drug_flags: Dict[str, dict] = {}
        for d in entities.get("drugs", []):
            canon = canonical_product(d.get("normalized") or d.get("text") or "")
            if not canon:
                continue
            is_dev = (
                bool(d.get("is_device"))
                or d.get("product_type") == "device"
                or is_known_device(canon)
            )
            # Raw rows tagged device only imply device for known-device products —
            # never promote co-mentioned drugs (e.g. Accutane on a device thread).
            if ptype_raw == "device" and is_known_device(canon):
                is_dev = True
            prev = drug_flags.get(canon)
            if prev is None or (is_dev and not prev.get("is_device")):
                drug_flags[canon] = {
                    "is_device": is_dev,
                    "atc": None if is_dev else d.get("atc"),
                    "gmdn": d.get("gmdn"),
                }
            elif d.get("atc") and not drug_flags[canon].get("is_device"):
                drug_flags[canon]["atc"] = d["atc"]
        for canon, flags in drug_flags.items():
            if flags.get("atc") and not flags.get("is_device"):
                drug_atc_map[canon] = flags["atc"]
        symptoms = []
        for s in entities.get("symptoms", []):
            if negation.get(s["normalized"], False):
                continue
            ev = canonical_event(s.get("pt") or s.get("normalized") or s.get("text") or "")
            if not ev:
                continue
            symptoms.append(ev)
            if ev not in sym_meddra:
                sym_meddra[ev] = {
                    "pt": ev,
                    "soc": s.get("soc"),
                    "soc_code": s.get("soc_code"),
                }
        for drug, flags in drug_flags.items():
            for symptom in symptoms:
                key = (drug, symptom)
                reports.append(key)
                # Once a pair is seen as device, keep it device (don't flip back to drug).
                if flags.get("is_device") or pair_product.get(key) == "device":
                    pair_product[key] = "device"
                    pair_device[key] = device_meta(drug, symptom)
                else:
                    pair_product.setdefault(key, "drug")
                # Heal mislabeled raw rows so future passes stay consistent.
                if flags.get("is_device") and ptype_raw != "device":
                    raw.product_type = "device"
                meta = pair_meta.setdefault(
                    key, {"timestamps": [], "post_ids": [], "texts": [], "regions": [],
                          "countries": [], "authors": []})
                meta["timestamps"].append(raw.posted_at or datetime.utcnow())
                meta["post_ids"].append(processed.id)
                meta["texts"].append((processed.ae_confidence, raw.body or ""))
                meta["regions"].append(raw.region or "Global")
                meta["authors"].append(raw.author_hash or "")
                if raw.country:
                    meta["countries"].append(raw.country)

    signals = compute_signals(reports)

    # Empirical calibration: fit the null from negative controls present in this corpus
    # and compute calibrated p-values/CIs + E-values for every signal (once).
    _cal_null, calib_map = calibrate_signals(signals)

    # Class effect (ATC roll-up) + read-across: build the class-level aggregation and
    # the set of (drug, event) pairs once, so each signal can be annotated with its
    # pharmacological-class disproportionality and any structural analogs reporting the
    # same event. Drugs only (devices have no ATC class).
    class_inputs: List[dict] = []
    event_pairs: set[Tuple[str, str]] = set()
    for sig in signals:
        if pair_product.get((sig["drug"], sig["symptom"]), "drug") == "device":
            continue
        md0 = sym_meddra.get(sig["symptom"]) or map_term(sig["symptom"])
        pt0 = md0.get("pt") or sig["symptom"]
        atc0 = drug_atc_map.get(sig["drug"]) or atc_for(sig["drug"])
        class_inputs.append({"drug": sig["drug"], "atc": atc0, "pt": pt0,
                             "soc": md0.get("soc"), "post_count": sig["post_count"]})
        event_pairs.add((sig["drug"], pt0))
    class_groups = aggregate_class(class_inputs)
    class_lookup = build_class_lookup(class_groups)
    # Active-comparator (same-class) disproportionality: reuse the class cohort to
    # contrast each drug against the OTHER drugs in its ATC class (shared indication),
    # reducing confounding-by-indication vs the standard "all other drugs" comparator.
    ac_lookup = active_comparator_analysis(class_inputs)

    # Prefetch openFDA/MAUDE evidence concurrently (each call is network-bound); this
    # turns dozens of sequential ~1-2s lookups into a couple of seconds total. Results
    # are cached in fda.py, so repeat recomputes (stream/tick) are near-instant.
    fda_map: Dict[Tuple[str, str], dict] = {}
    if use_fda and signals:
        from concurrent.futures import ThreadPoolExecutor

        uniq = {(s["drug"], s["symptom"]) for s in signals}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {
                ex.submit(query_evidence, pair_product.get((d, sym), "drug"), d, sym): (d, sym)
                for d, sym in uniq
            }
            for fut, pair in futs.items():
                try:
                    fda_map[pair] = fut.result()
                except Exception:
                    fda_map[pair] = {"available": False}

    # NOTE: DailyMed / PubMed / recall / device-classification enrichment is done
    # LAZILY per signal on first detail view (cached + persisted), NOT as a bulk burst
    # here. A mass concurrent fan-out (hundreds of calls) tripped NCBI rate limits and
    # destabilized the worker, so enrichment is deferred to keep recompute fast + stable.
    # Wipe prior signal rows for this scope. Alerts FK → signals.id has no ON DELETE
    # CASCADE (legacy SQLite→Postgres), and orphan alerts may have NULL/mismatched
    # project_id — so delete by signal_id first, then by project, then signals.
    if project_id is not None:
        sig_ids = [
            row[0]
            for row in db.query(Signal.id).filter(Signal.project_id == project_id).all()
        ]
        if sig_ids:
            db.query(Alert).filter(Alert.signal_id.in_(sig_ids)).delete(
                synchronize_session=False
            )
        db.query(Alert).filter(Alert.project_id == project_id).delete(
            synchronize_session=False
        )
        db.query(Signal).filter(Signal.project_id == project_id).delete(
            synchronize_session=False
        )
    else:
        db.query(Alert).delete(synchronize_session=False)
        db.query(Signal).delete(synchronize_session=False)
    db.flush()

    stored = []
    for sig in signals:
        key = (sig["drug"], sig["symptom"])
        meta = pair_meta.get(key, {"timestamps": [], "post_ids": [], "texts": [],
                                   "regions": [], "countries": []})
        trend = compute_trend(meta["timestamps"])

        fda = fda_map.get(key, {"available": False}) if use_fda else {"available": False}
        ptype = pair_product.get(key, "drug")

        causality = {"category": "Unassessable", "score": 0.0, "factors": [],
                     "uncertainty": "high"}
        for _conf, text in meta["texts"]:
            cand = assess_causality(text, sig["drug"], sig["symptom"],
                                    fda_known=fda.get("available", False),
                                    product_type=ptype)
            if cand["score"] > causality["score"]:
                causality = cand
        if not meta["texts"]:
            causality = assess_causality("", sig["drug"], sig["symptom"],
                                         fda_known=fda.get("available", False),
                                         product_type=ptype)
        # persist uncertainty alongside the causality factors
        causality["factors"] = list(causality["factors"]) + [
            f"uncertainty:{causality.get('uncertainty', 'high')}"]
        severity = grade_severity(sig["symptom"], causality["category"])

        md = sym_meddra.get(sig["symptom"]) or map_term(sig["symptom"])
        atc = drug_atc_map.get(sig["drug"]) or atc_for(sig["drug"])
        regions = dict(Counter(meta["regions"]))
        # Spatial (geographic) cluster detection: is this signal concentrated in a
        # country/region beyond its expected share of the corpus geography? (bad batch,
        # counterfeit/substandard product, or regional practice issue — Kulldorff scan)
        spatial_info = spatial_assess(
            {"country": dict(Counter(meta["countries"])), "region": regions},
            geo_baseline,
        )
        ptype = pair_product.get(key, "drug")
        dev = device_meta(sig["drug"], sig["symptom"]) if ptype == "device" else {}
        # Pharmacogenomic overlay: flag genomically-explainable signals (drugs only).
        pgx = pgx_match(sig["drug"], sig["symptom"], pt=md.get("pt"),
                        soc=md.get("soc_code")) if ptype != "device" else None
        # SMQ syndrome membership (narrow/broad) for this event.
        smqs = smqs_for_event(md.get("pt"), md.get("soc"), sig["symptom"])
        # FDA boxed (black-box) warning overlay (drugs only): is the drug boxed, and
        # does the boxed harm cover THIS event? (drives the novelty hint)
        boxed = boxed_match(sig["drug"], sig["symptom"], pt=md.get("pt"),
                            soc=md.get("soc_code")) if ptype != "device" else None
        # Labeling-gap detection: classify event against the drug's FDA label text
        # (DailyMed adverse_reactions section). Runs after boxed so the boxed tier
        # takes precedence when the boxed warning covers this event.
        label_gap = None
        if ptype == "device":
            label_gap = {
                "novelty_tier": "not_applicable",
                "label_match": None,
                "label_section": None,
                "confidence": "high",
                "note": "Device signals are not classified against drug labels.",
            }
        else:
            try:
                label_gap = assess_label_gap(
                    sig["drug"], sig["symptom"],
                    pt=md.get("pt"), soc=md.get("soc_code"),
                    boxed_info=boxed,
                )
            except Exception:
                label_gap = {
                    "novelty_tier": "unknown", "label_match": None,
                    "label_section": None, "confidence": "low",
                    "note": "Label-gap assessment unavailable.",
                }
        # Mechanistic plausibility (Bradford Hill): does the drug's MoA explain the event?
        mechanism = mechanism_assess(sig["drug"], sig["symptom"], pt=md.get("pt"),
                                     soc=md.get("soc_code")) if ptype != "device" else None
        if mechanism and mechanism.get("plausible"):
            # surface as a causality factor without altering the deterministic score
            causality["factors"] = list(causality["factors"]) + ["biological_plausibility"]
        # Class effect (ATC roll-up) + chemical read-across (drugs only).
        class_info = None
        analogs: list = []
        active_comparator = None
        if ptype != "device":
            pt_key = md.get("pt") or sig["symptom"]
            ck = atc_class_key(atc)
            class_info = class_summary(class_lookup.get((ck, pt_key))) if ck else None
            analogs = read_across(sig["drug"], pt_key, event_pairs)
            # Active-comparator (same-class) disproportionality for this drug/event.
            active_comparator = ac_lookup.get((sig["drug"], pt_key))
        # Vaccine pharmacovigilance overlay (vaccines only): attach the AESI match,
        # a Brighton case-definition-level surrogate, and a self-controlled risk
        # interval (SCRI) surrogate computed over the supporting-post onset times.
        vaccine_info = None
        if is_vaccine(sig["drug"]):
            vaccine_info = vaccine_summary(
                vaccine_assess(sig["drug"], sig["symptom"], pt=md.get("pt"),
                               soc=md.get("soc_code"), timestamps=meta["timestamps"]))
        # Quantitative benefit–risk (BRAT/MCDA + NNT vs NNH): contextualise this
        # signal against the drug's therapeutic benefit (illustrative surrogate).
        # Applies to drugs + vaccines (indication/NNV framing); devices are skipped.
        benefit_risk = None
        if ptype != "device":
            benefit_risk = benefit_risk_assess(
                sig["drug"], atc, sig["symptom"], md.get("pt"),
                severity, causality["category"], sig["post_count"])
        # Empirical calibration + E-values for this signal.
        calib = calib_map.get(key, {})
        # UMC vigiGrade-style report completeness (documentation-quality surrogate):
        # aggregate the per-post assessable-dimension coverage across the supporting
        # posts into a mean multiplicative-penalty score + a well-documented flag.
        post_ids = meta["post_ids"]
        sig_dims = [post_dims[pid] for pid in post_ids if pid in post_dims]
        completeness = score_signal(sig_dims)
        # Map best/worst back to the originating processed-post id for traceability.
        for _which in ("best", "worst"):
            summ = completeness.get(_which)
            if summ and 0 <= summ.get("index", -1) < len(post_ids):
                summ["post_id"] = post_ids[summ["index"]]
        timestamps = meta["timestamps"] or [datetime.utcnow()]
        earliest = min(timestamps)
        carried = prior.get(key)

        # Sybil-defense trust score — evaluates cohort for coordinated inauthentic posts.
        from .analytics.trust import compute_trust as _compute_trust
        _trust = _compute_trust(
            author_hashes=meta.get("authors", []),
            timestamps=timestamps,
            texts=[t for _, t in meta.get("texts", []) if t],
        )

        # MaxSPRT sequential surveillance: compute over the trend series for this signal.
        # Expected per look = signal.expected / n_trend_looks (distributes the expected count
        # uniformly across the surveillance window — a conservative Poisson assumption).
        _maxsprt = maxsprt_from_signal(
            trend_series=trend.get("series", []),
            expected_total=max(0.01, sig.get("expected", 0.01)),
            alpha=0.05,
        )

        # Cox PH time-to-event surrogate (social-listening hazard ratio).
        # Exposed  = this signal's own supporting posts.
        # Unexposed = AE posts NOT in this signal's supporting-post set.
        _signal_pid_set = set(meta["post_ids"])
        _comparator_ts = [
            ts for pid, ts in all_ae_post_times.items()
            if pid not in _signal_pid_set
        ]
        _hr_result = compute_hazard_ratio(
            signal_timestamps=meta["timestamps"],
            comparator_timestamps=_comparator_ts,
            anchor=earliest,
        )

        row = Signal(
            project_id=project_id or _infer_project_id(db, meta.get("post_ids", [])),
            drug=canonical_product(sig["drug"]) or sig["drug"],
            symptom=canonical_event(sig["symptom"]) or sig["symptom"],
            product_type=ptype,
            device_gmdn=dev.get("gmdn"),
            imdrf_code=dev.get("imdrf"),
            imdrf_term=dev.get("imdrf_term"),
            drug_atc=atc if ptype != "device" else None,
            meddra_pt=canonical_event(md.get("pt") or "") or md.get("pt"),
            meddra_soc=md.get("soc"),
            meddra_soc_code=md.get("soc_code"),
            regions_json=json.dumps(regions),
            post_count=sig["post_count"],
            expected=sig.get("expected", 0.0),
            prr=sig["prr"],
            prr_ci_low=sig.get("prr_ci_low"),
            prr_ci_high=sig.get("prr_ci_high"),
            ror=sig["ror"],
            ror_ci_low=sig.get("ror_ci_low"),
            ror_ci_high=sig.get("ror_ci_high"),
            chi_square=sig["chi_square"],
            ic=sig.get("ic"),
            ic025=sig.get("ic025"),
            ebgm=sig.get("ebgm"),
            eb05=sig.get("eb05"),
            strength=sig["strength"],
            sdr_flag=sig.get("sdr_flag", False),
            trend_score=trend["trend_score"],
            spike_flag=trend["spike_flag"],
            spike_z=trend["spike_z"],
            who_umc=causality["category"],
            who_umc_score=causality["score"],
            who_umc_factors_json=json.dumps(causality["factors"]),
            severity=severity,
            fda_evidence_json=json.dumps(fda),
            pgx_actionable=bool(pgx),
            pgx_json=json.dumps(pgx or {}),
            smq_json=json.dumps(smqs),
            boxed_warning=bool(boxed),
            boxed_json=json.dumps(boxed or {}),
            label_novelty=(label_gap.get("novelty_tier") if label_gap else None),
            label_gap_json=json.dumps(label_gap or {}),
            mechanism_plausible=bool(mechanism and mechanism.get("plausible")),
            mechanism_json=json.dumps(mechanism or {}),
            class_effect=bool(class_info and class_info.get("class_effect")),
            class_json=json.dumps(class_info or {}),
            read_across_json=json.dumps(analogs or []),
            stands_out_in_class=bool(active_comparator
                                     and active_comparator.get("stands_out_in_class")),
            active_comparator_json=json.dumps(active_comparator or {}),
            is_vaccine=bool(vaccine_info),
            aesi=(vaccine_info.get("aesi_name") if vaccine_info else None),
            vaccine_json=json.dumps(vaccine_info or {}),
            spatial_cluster=bool(spatial_info and spatial_info.get("cluster")),
            spatial_json=json.dumps(spatial_info or {}),
            calibrated_p=calib.get("calibrated_p"),
            calibrated_signal=bool(calib.get("calibrated_p") is not None
                                   and calib.get("calibrated_p") < 0.05),
            e_value=calib.get("e_value"),
            e_value_ci=calib.get("e_value_ci"),
            calibration_json=json.dumps({
                "calibrated": calib.get("calibrated", False),
                "calibrated_ci": calib.get("calibrated_ci"),
                "null_mu": calib.get("null_mu"),
                "null_sigma": calib.get("null_sigma"),
                "n_controls": calib.get("n_controls"),
                "is_negative_control": is_negative_control(sig["drug"], sig["symptom"]),
            }),
            br_verdict=(benefit_risk.get("verdict") if benefit_risk else None),
            benefit_risk_json=json.dumps(benefit_risk or {}),
            completeness=completeness["mean_completeness"],
            well_documented=completeness["well_documented"],
            completeness_json=json.dumps(completeness),
            hr=_hr_result.get("hr"),
            hr_ci_json=json.dumps(_hr_result.get("hr_ci")),
            hr_p=_hr_result.get("hr_p"),
            hr_elevated=bool(_hr_result.get("hr_elevated", False)),
            hr_json=json.dumps(_hr_result.get("hr_json") or {}),
            maxsprt_llr=_maxsprt.get("llr_max"),
            maxsprt_crossed=bool(_maxsprt.get("crossed", False)),
            maxsprt_json=json.dumps(_maxsprt),
            federated_json=None,
            supporting_post_ids=json.dumps(meta["post_ids"]),
            earliest_post_at=earliest,
            detected_at=(carried["detected_at"] if carried else datetime.utcnow()),
            trust_score=_trust.get("trust_score", 1.0),
            trust_label=_trust.get("trust_label", "high"),
            review_state=(carried["review_state"] if carried else "unreviewed"),
            reviewed_by=(carried["reviewed_by"] if carried else None),
            reviewed_at=(carried["reviewed_at"] if carried else None),
            # GVP Module IX lifecycle — carry over governed state; compute priority fresh.
            lifecycle_status=(carried["lifecycle_status"] if carried else "new"),
            lifecycle_owner=(carried["lifecycle_owner"] if carried else None),
            lifecycle_notes=(carried["lifecycle_notes"] if carried else None),
            lifecycle_updated_at=(carried["lifecycle_updated_at"] if carried else None),
        )
        db.add(row)
        db.flush()
        # Priority score depends on analytics fields computed above; set after flush.
        row.priority_score = compute_priority({
            "strength": row.strength,
            "severity": row.severity,
            "label_novelty": row.label_novelty,
            "spike_flag": row.spike_flag,
            "trend_score": row.trend_score,
            "maxsprt_crossed": row.maxsprt_crossed,
        })
        stored.append(row)
        if carried is None:
            db.add(AuditLog(actor="system", action="signal_detected",
                            entity_type="signal", entity_id=row.id,
                            detail=f"{row.drug} -> {row.meddra_pt or row.symptom} "
                                   f"[{row.strength}{' SDR' if row.sdr_flag else ''}]"))
        _maybe_alert(db, row)

    db.commit()

    # Longitudinal casefile: persist weekly DMA snapshots for trajectory UI
    try:
        from .analytics.casefile import snapshot_signals
        snapshot_signals(db, stored, project_id=project_id)
    except Exception:
        pass

    # Narratives: generate for the most important signals (keeps LLM usage bounded).
    if with_narrative and stored:
        _attach_narratives(db, stored)

    return {
        "signals": len(stored),
        "alerts": db.query(Alert).count(),
        "reports": len(reports),
    }


def _attach_narratives(db: Session, signals: List[Signal]) -> None:
    """Attach an instant deterministic narrative to every signal.

    LLM narratives are generated on demand (POST /signals/{id}/narrative) so bulk
    ingest stays fast; every signal still carries a grounded explanation immediately.
    """
    from .api.helpers import signal_to_dict

    for s in signals:
        try:
            nar = build_narrative(signal_to_dict(s), allow_llm=False)
            s.narrative = nar["text"]
            s.narrative_source = nar["source"]
        except Exception:
            continue
    db.commit()


def _infer_project_id(db: Session, post_ids: List[int]) -> int | None:
    """Resolve workspace from supporting *processed* post ids → raw.project_id."""
    if not post_ids:
        return None
    row = (
        db.query(RawPost.project_id)
        .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.id.in_(post_ids[:16]))
        .filter(RawPost.project_id.isnot(None))
        .first()
    )
    return int(row[0]) if row and row[0] is not None else None


def heal_orphan_project_ids(db: Session, default_project_id: int | None = None) -> dict:
    """Attach NULL/0 project_id signal+alert rows to the default (or given) workspace.

    Legacy recomputes stored signals with project_id=NULL because ``_infer_project_id``
    incorrectly queried RawPost.id with ProcessedPost ids. The UI always sends
    X-Project-Id, so those orphans never appear in /api/signals.
    """
    from sqlalchemy import or_

    from .models import Project

    try:
        pid = default_project_id
        if pid is None:
            pid = db.query(Project.id).order_by(Project.id.asc()).limit(1).scalar()
        if pid is None:
            return {"signals": 0, "alerts": 0, "project_id": None}

        orphan = or_(Signal.project_id.is_(None), Signal.project_id == 0)
        n_sig = 0
        for sig in db.query(Signal).filter(orphan).all():
            sig.project_id = int(pid)
            n_sig += 1
        n_alert = 0
        alert_orphan = or_(Alert.project_id.is_(None), Alert.project_id == 0)
        for alert in db.query(Alert).filter(alert_orphan).all():
            alert.project_id = int(pid)
            n_alert += 1
        if n_sig or n_alert:
            db.commit()
        return {"signals": n_sig, "alerts": n_alert, "project_id": int(pid)}
    except Exception as exc:
        db.rollback()
        return {"signals": 0, "alerts": 0, "project_id": default_project_id, "error": str(exc)}


def _maybe_alert(db: Session, sig: Signal) -> None:
    reasons = []
    if sig.severity in {"Critical", "High"}:
        reasons.append(f"{sig.severity.lower()} severity")
    if sig.spike_flag:
        reasons.append(f"spike detected (z={sig.spike_z})")
    if sig.sdr_flag:
        reasons.append(f"disproportionate reporting (EB05={sig.eb05}, IC025={sig.ic025})")
    elif sig.strength == "STRONG":
        reasons.append(f"strong disproportionality (PRR={sig.prr})")

    if reasons:
        db.add(Alert(
            project_id=sig.project_id,
            signal_id=sig.id,
            drug=sig.drug,
            symptom=sig.symptom,
            severity=sig.severity,
            message=f"{sig.drug} \u2192 {sig.meddra_pt or sig.symptom}: " + ", ".join(reasons),
        ))


# --------------------------------------------------------------------------- #
# Knowledge graph projection
# --------------------------------------------------------------------------- #
def knowledge_graph(db: Session, project_id: int | None = None) -> dict:
    sig_q = db.query(Signal)
    if project_id is not None:
        sig_q = sig_q.filter(Signal.project_id == project_id)
    sigs = sig_q.all()
    signal_dicts = [
        {
            "drug": s.drug, "symptom": s.meddra_pt or s.symptom, "prr": s.prr,
            "strength": s.strength, "post_count": s.post_count, "severity": s.severity,
            "soc": s.meddra_soc,
        }
        for s in sigs
    ]

    cond_counter: Dict[Tuple[str, str], int] = {}
    proc_q = db.query(ProcessedPost, RawPost).join(RawPost, ProcessedPost.raw_id == RawPost.id)
    if project_id is not None:
        proc_q = proc_q.filter(RawPost.project_id == project_id)
    for processed, _raw in proc_q.all():
        entities = json.loads(processed.entities_json or "{}")
        drugs = {
            canon
            for d in entities.get("drugs", [])
            for canon in [canonical_product(d.get("normalized") or d.get("text") or "")]
            if canon
        }
        conds = {c["normalized"] for c in entities.get("conditions", []) if c.get("normalized")}
        for d in drugs:
            for c in conds:
                cond_counter[(d, c)] = cond_counter.get((d, c), 0) + 1
    condition_links = [
        {"drug": d, "condition": c, "count": n}
        for (d, c), n in cond_counter.items() if n >= 2
    ]

    return build_graph(signal_dicts, condition_links)
