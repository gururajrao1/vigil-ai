"""VigilAI REST API."""
from __future__ import annotations

import json
import threading
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from datetime import datetime

from ..analytics.kpis import compute_kpis, recent_audit
from ..auth import require_role
from ..config import settings
from ..database import get_db, SessionLocal
from ..demo import prepare_demo, prewarm_signals
from ..evidence.e2b import generate_e2b_r2_xml, generate_e2b_xml
from ..evidence.cioms import generate_cioms_html, generate_cioms_text
from ..evidence.registry import registry_summary
from ..ingestion.fhir_parser import parse_fhir_bundle
from ..ingestion.fhir import sample_bundle
from ..ingestion.sources import (
    SOURCES,
    crawl_dailymed_rss,
    crawl_device_news,
    crawl_device_recalls,
    crawl_faers,
    crawl_fda_all,
    crawl_fda_medwatch,
    crawl_fda_recalls,
    crawl_fda_press,
    crawl_google_news,
    crawl_hackernews,
    crawl_life_science_news,
    crawl_maude_live,
    crawl_mhra_devices,
    crawl_cochrane_central,
    crawl_europe_pmc,
    crawl_pubmed_live,
    crawl_semantic_scholar,
    crawl_reddit_health,
    crawl_reddit_pullpush,
    crawl_reddit_rss,
    crawl_twitter,
    crawl_youtube,
    fda_rss_feeds,
    google_news_queries,
    life_science_feeds,
    query_eudamed,
    reddit_health_subs,
)
from ..ingestion.synthetic import generate_corpus, stream_batch
from ..llm import status as llm_status
from ..analytics.lifecycle import LIFECYCLE_TRANSITIONS, compute_priority, is_valid_transition, valid_next_states
from ..models import Alert, AuditLog, ProcessedPost, RawPost, Signal
from ..pipeline import (
    heal_orphan_project_ids,
    ingest_posts,
    knowledge_graph,
    recompute_signals,
    reprocess_posts,
)
from ..scheduler import scheduler
from .helpers import (
    alert_to_dict,
    dashboard_stats,
    overview_timeseries,
    post_to_dict,
    signal_list_dict,
    signal_to_dict,
    signal_trend_series,
)

router = APIRouter(prefix="/api")

_recompute_lock = threading.Lock()
_recompute_running = False


def _run_recompute_job() -> None:
    """Fresh-session signal rebuild (safe for background threads)."""
    global _recompute_running
    import logging

    log = logging.getLogger("vigilai.recompute")
    db = SessionLocal()
    try:
        heal_orphan_project_ids(db)
        recompute_signals(db, use_fda=False, with_narrative=False)
        db.commit()
        log.info("background recompute finished")
    except Exception:
        log.exception("background recompute failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
        with _recompute_lock:
            _recompute_running = False


def _maybe_recompute(db: Session, recompute: bool = False) -> dict:
    """Queue corpus recompute off-request when asked.

    Sync rebuild on Neon (~1948 posts) exceeds Vercel→Render proxy timeouts and
    surfaces as 502/500 (or empty gateway errors) for Google News / device crawls.
    Ingest returns immediately; signals refresh in the background.
    Only one rebuild runs at a time (extra requests are coalesced).
    """
    global _recompute_running
    if not recompute:
        return {"signals": 0, "alerts": 0, "recomputed": False}
    with _recompute_lock:
        if _recompute_running:
            return {
                "signals": 0,
                "alerts": 0,
                "recomputed": False,
                "recompute_queued": False,
                "recompute_skipped": "already_running",
            }
        _recompute_running = True
    threading.Thread(
        target=_run_recompute_job,
        daemon=True,
        name="vigilai-recompute",
    ).start()
    return {
        "signals": 0,
        "alerts": 0,
        "recomputed": False,
        "recompute_queued": True,
    }




# --------------------------- ingestion ------------------------------------- #
def _prewarm_background(limit: int = 12) -> None:
    """Warm external evidence on the top signals in a fresh session (non-blocking)."""
    db = SessionLocal()
    try:
        prewarm_signals(db, limit=limit)
    except Exception:
        pass
    finally:
        db.close()



@router.post("/recompute")
def recompute_only(db: Session = Depends(get_db)):
    """Queue one corpus signal recompute (DemoBar / Sources post-ingest)."""
    healed = heal_orphan_project_ids(db)
    db.commit()
    stats = _maybe_recompute(db, True)
    return {"status": "ok", "healed_projects": healed, **stats}


@router.post("/reprocess")
def reprocess_only(
    recompute: bool = False,
    db: Session = Depends(get_db),
    _user=Depends(require_role("analyst")),
):
    """Re-run NLP on all stored posts (applies current device/drug lexicons), then recompute."""
    healed = heal_orphan_project_ids(db)
    n = reprocess_posts(db, use_transformer=False)
    stats = _maybe_recompute(db, recompute) if recompute else {"recomputed": False}
    return {"status": "ok", "reprocessed": n, "healed_projects": healed, **stats}


@router.post("/heal-projects")
def heal_projects(
    db: Session = Depends(get_db),
    _user=Depends(require_role("analyst")),
):
    """Attach orphan NULL-scoped signals/alerts to the default project workspace."""
    return {"status": "ok", **heal_orphan_project_ids(db)}


@router.post("/ingest/seed")
def ingest_seed(days: int = 21, ml: bool = False, demo: bool = True,
                db: Session = Depends(get_db),
                _user=Depends(require_role("analyst"))):
    """Ingest a synthetic corpus into the active project workspace.

    Uses the header ``X-Project-Id`` (set by the UI project dropdown). When the
    active project is oncology/vaccine, seeds a focused therapeutic-area corpus;
    otherwise seeds the full worldwide general PV corpus.
    """
    from ..ingestion.synthetic import generate_area_corpus, generate_corpus
    from ..models import Project
    from ..projects.scope import current_project_id

    pid = current_project_id()
    area = "general"
    if pid is not None:
        proj = db.query(Project).filter(Project.id == pid).first()
        if proj and proj.therapeutic_area:
            area = proj.therapeutic_area

    posts = (
        generate_area_corpus(area, days=days)
        if area not in ("general", "general-pv", "")
        else generate_corpus(days=days)
    )
    new = ingest_posts(db, posts, use_transformer=ml, use_presidio=ml,
                       online_translation=ml, project_id=pid)
    stats = recompute_signals(db, project_id=pid)
    demo_info = None
    if demo and area in ("general", "general-pv", ""):
        demo_info = prepare_demo(db)
        threading.Thread(target=_prewarm_background, kwargs={"limit": 12},
                         daemon=True).start()
    return {
        "ingested": new,
        "ml_ner": ml,
        "demo": demo_info,
        "project_id": pid,
        "therapeutic_area": area,
        **stats,
    }


@router.post("/ingest/reddit")
def ingest_reddit(query: str = Query(..., min_length=2), limit: int = 25,
                  recompute: bool = False, db: Session = Depends(get_db)):
    posts = crawl_reddit_rss(query, limit)
    new = ingest_posts(db, posts)
    stats = _maybe_recompute(db, recompute)
    return {"source": "reddit", "fetched": len(posts), "ingested": new, **stats}


@router.post("/ingest/faers-live")
def ingest_faers_live(
    limit: int = 30, days_back: int = 90, recompute: bool = False, db: Session = Depends(get_db)
):
    """Ingest recent serious AE reports from openFDA FAERS as pipeline posts (no key).

    Converts each ICSR (drug + MedDRA reaction) into a post body so the NLP
    pipeline can extract signals from real regulatory reports.
    """
    batch = crawl_faers(limit=limit, days_back=days_back)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "faers_live",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/vaers")
def ingest_vaers(
    limit: int = 40,
    force_fixture: bool = False,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest VAERS vaccine AE reports (CDC when reachable, else offline fixtures)."""
    from ..ingestion.srs_bulk import crawl_vaers

    batch = crawl_vaers(limit=limit, force_fixture=force_fixture)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "vaers",
        "mode": batch.get("mode"),
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        "note": batch.get("note"),
        **stats,
    }


@router.post("/ingest/faers-bulk")
def ingest_faers_bulk(
    limit: int = 50,
    force_fixture: bool = False,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest FAERS quarterly bulk subset (openFDA slice or ASCII fixtures)."""
    from ..ingestion.srs_bulk import crawl_faers_bulk

    batch = crawl_faers_bulk(limit=limit, force_fixture=force_fixture)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "faers_bulk",
        "mode": batch.get("mode"),
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        "note": batch.get("note"),
        **stats,
    }


@router.post("/ingest/pv-demo")
def ingest_pv_demo(recompute: bool = True, db: Session = Depends(get_db)):
    """Load offline packs that make DDI, pregnancy, and masking remine demo-ready.

    Pulls FAERS-bulk fixtures (polypharmacy), VAERS fixtures, and pregnancy/teratogen
    demo ICSRs that pass 4-gate AE NLP so they land in Safety Signals Detect.
    Recomputes signals by default so lenses update immediately.
    """
    from ..analytics.pregnancy import pregnancy_demo_posts
    from ..ingestion.srs_bulk import crawl_faers_bulk, crawl_vaers

    posts = []
    posts.extend(crawl_faers_bulk(limit=50, force_fixture=True)["posts"])
    posts.extend(crawl_vaers(limit=40, force_fixture=True)["posts"])
    posts.extend(pregnancy_demo_posts())
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "pv_demo",
        "fetched": len(posts),
        "ingested": new,
        "packs": ["faers_bulk_fixture", "vaers_fixture", "pregnancy_demo"],
        "note": (
            "Demo pack for DDI co-mentions, pregnancy/teratogen cohort, and "
            "competition-bias remine. Pregnancy ICSRs use v2 ids and congenital "
            "lexicon terms so they become AE-flagged Detect rows. "
            "Prototype data — not for clinical use."
        ),
        **stats,
    }


@router.get("/ingest/fda-rss/feeds")
def list_fda_rss_feeds():
    """All FDA RSS feeds available for pharmacovigilance ingestion."""
    feeds = fda_rss_feeds()
    return {"count": len(feeds), "feeds": feeds}


@router.post("/ingest/fda-rss")
def ingest_fda_rss(
    feed: str | None = None,
    limit: int = 60,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest FDA RSS feeds (MedWatch, recalls, press releases) — no key.

    Pass ``feed=fda_medwatch|fda_recalls|fda_press`` to pull one feed only,
    or omit ``feed`` to run all three combined.
    """
    if feed == "fda_medwatch":
        batch = crawl_fda_medwatch(limit)
    elif feed == "fda_recalls":
        batch = crawl_fda_recalls(limit)
    elif feed == "fda_press":
        batch = crawl_fda_press(limit)
    else:
        batch = crawl_fda_all(limit)

    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": f"fda_rss/{feed or 'all'}",
        "feeds_run": batch.get("feeds_run", [feed or "all"]),
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/pubmed-live")
def ingest_pubmed_live(
    query: str | None = None,
    limit: int = 20,
    days_back: int = 730,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest PubMed abstracts via NCBI esearch + efetch (no key).

    Default queries use MeSH PV terms and respect the active project workspace
    (Oncology / Vaccine / device keywords). Literature posts are tagged
    ``content_type=literature`` so they stay distinct from spontaneous ICSRs.
    """
    batch = crawl_pubmed_live(query=query, limit=limit, days_back=days_back)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "pubmed_live",
        "content_type": "literature",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "query_count": batch.get("query_count"),
        "ingested": new,
        **stats,
    }


@router.post("/ingest/europe-pmc")
def ingest_europe_pmc(
    query: str | None = None,
    limit: int = 20,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest Europe PMC abstracts (EMBL-EBI REST, no key; offline fixtures if blocked)."""
    batch = crawl_europe_pmc(query=query, limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "europe_pmc",
        "content_type": "literature",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/semantic-scholar")
def ingest_semantic_scholar(
    query: str | None = None,
    limit: int = 20,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest Semantic Scholar paper abstracts (optional SEMANTIC_SCHOLAR_API_KEY)."""
    batch = crawl_semantic_scholar(query=query, limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "semantic_scholar",
        "content_type": "literature",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/cochrane-central")
def ingest_cochrane_central(
    query: str | None = None,
    limit: int = 20,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest Cochrane CENTRAL abstracts via Europe PMC SRC:cctr (+ offline fixtures)."""
    batch = crawl_cochrane_central(query=query, limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "cochrane_central",
        "content_type": "literature",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/hackernews")
def ingest_hackernews(
    query: str | None = None, limit: int = 30, recompute: bool = False, db: Session = Depends(get_db)
):
    """Ingest HackerNews drug safety discussions via Algolia API (no key)."""
    batch = crawl_hackernews(query=query, limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "hackernews",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "query_count": batch["query_count"],
        "ingested": new,
        **stats,
    }


@router.get("/ingest/life-science/feeds")
def list_life_science_feeds():
    """Curated life-science / pharma RSS outlets (no key)."""
    feeds = life_science_feeds()
    return {"feeds": feeds, "count": len(feeds)}


@router.post("/ingest/life-science")
def ingest_life_science(
    feed_id: str | None = None, limit: int = 50, recompute: bool = False, db: Session = Depends(get_db)
):
    """Ingest curated life-science news RSS pack (ScienceDaily, STAT, Nature Medicine…)."""
    batch = crawl_life_science_news(feed_id=feed_id, limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "life_science",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "feed_count": batch["feed_count"],
        "feeds_run": batch.get("feeds_run", []),
        "ingested": new,
        "note": batch.get("note"),
        **stats,
    }


@router.post("/ingest/youtube")
def ingest_youtube(
    query: str | None = None, limit: int = 30, recompute: bool = False, db: Session = Depends(get_db)
):
    """Ingest YouTube video titles/descriptions + comment threads (needs YOUTUBE_API_KEY)."""
    batch = crawl_youtube(query=query, limit=limit)
    posts = batch["posts"]
    new = 0
    stats: dict = {}
    if posts:
        new = ingest_posts(db, posts, use_transformer=False,
                           use_presidio=False, online_translation=False)
        stats = _maybe_recompute(db, recompute)
    return {
        "source": "youtube",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "video_posts": batch.get("video_posts", 0),
        "comment_posts": batch.get("comment_posts", 0),
        "ingested": new,
        "note": batch.get("note"),
        "errors": batch.get("errors") or [],
        **stats,
    }


@router.get("/signals/{signal_id}/audit")
def get_signal_audit(signal_id: int, db: Session = Depends(get_db)):
    """Return the cryptographic audit envelope for a signal and verify its integrity."""
    from ..analytics.audit import create_envelope, verify_envelope
    from ..api.helpers import signal_to_dict

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")

    sig_dict = signal_to_dict(sig)

    # Retrieve previous chain hash from audit_logs for this signal
    prev_log = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "signal", AuditLog.entity_id == signal_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    prev_hash = None
    if prev_log and prev_log.detail:
        try:
            prev_hash = json.loads(prev_log.detail).get("chain_hash")
        except Exception:
            pass

    envelope = create_envelope(sig_dict, prev_hash=prev_hash)
    verification = verify_envelope(envelope, sig_dict)

    # Persist envelope in audit_logs
    try:
        log = AuditLog(
            actor="system",
            action="audit_envelope",
            entity_type="signal",
            entity_id=signal_id,
            detail=json.dumps(envelope),
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()

    return {
        "envelope": envelope,
        "verification": verification,
        "signal_id": signal_id,
    }


@router.get("/audit/chain")
def get_audit_chain(limit: int = 50, db: Session = Depends(get_db)):
    """Walk the audit envelope chain and verify integrity."""
    from ..analytics.audit import chain_status

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "audit_envelope")
        .order_by(AuditLog.id.asc())
        .limit(limit)
        .all()
    )
    envelopes = []
    for log in logs:
        try:
            envelopes.append(json.loads(log.detail or "{}"))
        except Exception:
            pass

    status = chain_status(envelopes)
    return {**status, "sample_envelopes": envelopes[-3:]}


@router.get("/signals/{signal_id}/trust")
def get_signal_trust(signal_id: int, db: Session = Depends(get_db)):
    """Return detailed trust score breakdown for a signal's supporting cohort."""
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    return {
        "signal_id": signal_id,
        "drug": sig.drug,
        "symptom": sig.symptom,
        "trust_score": sig.trust_score if sig.trust_score is not None else 1.0,
        "trust_label": sig.trust_label or "high",
        "post_count": sig.post_count,
    }


@router.post("/ingest/mhra-devices")
def ingest_mhra_devices(limit: int = 40, recompute: bool = False, db: Session = Depends(get_db)):
    """Ingest UK MHRA device alerts and Field Safety Notices (no key).

    Pulls from gov.uk Atom feeds — device FSNs tagged product_type=device,
    drug safety updates tagged product_type=drug.
    """
    batch = crawl_mhra_devices(limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "mhra_devices",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "feeds_run": batch["feeds_run"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/maude-live")
def ingest_maude_live(
    limit: int = 30, days_back: int = 60, recompute: bool = False, db: Session = Depends(get_db)
):
    """Ingest live device MDR reports from FDA MAUDE (no key).

    Converts each MDR (device + event narrative) to a product_type=device post
    that flows through the full signal detection pipeline.
    """
    batch = crawl_maude_live(limit=limit, days_back=days_back)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "maude_live",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/device-news")
def ingest_device_news(limit: int = 40, recompute: bool = False, db: Session = Depends(get_db)):
    """Ingest medical-device safety news (Google News RSS, no key)."""
    batch = crawl_device_news(limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "device_news",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "queries_run": batch.get("queries_run"),
        "ingested": new,
        **stats,
    }


@router.post("/ingest/device-recalls")
def ingest_device_recalls(limit: int = 30, recompute: bool = False, db: Session = Depends(get_db)):
    """Ingest FDA device recalls (openFDA device/enforcement, no key)."""
    batch = crawl_device_recalls(limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "device_recalls",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.get("/device/eudamed")
def lookup_eudamed(device: str, db: Session = Depends(get_db)):
    """Look up a device in the EUDAMED EU registry (no key).

    Returns EU registration data: UDI, manufacturer, CE risk class, GMDN.
    """
    result = query_eudamed(device)
    return result


@router.post("/ingest/dailymed-rss")
def ingest_dailymed_rss(limit: int = 40, recompute: bool = False, db: Session = Depends(get_db)):
    """Ingest new/revised drug labels from DailyMed RSS (no key).

    Label text is run through the NLP pipeline; the drug name in the title
    seeds drug entity extraction for any reaction-adjacent language.
    """
    batch = crawl_dailymed_rss(limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "dailymed_rss",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "ingested": new,
        **stats,
    }


@router.get("/ingest/google-news/queries")
def list_google_news_queries():
    """Curated Google News RSS query panel for pharmacovigilance monitoring."""
    qs = google_news_queries()
    return {"count": len(qs), "queries": qs}


@router.post("/ingest/google-news")
def ingest_google_news(
    query: str | None = None,
    limit: int = 40,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest live health-safety articles from Google News RSS (no API key).

    Omit ``query`` to run all curated PV queries (drug AEs, vaccine safety,
    recalls, FDA warnings, pharmacovigilance news).
    """
    batch = crawl_google_news(query, limit=limit)
    posts = batch["posts"]
    # News headlines/snippets are English; lexicon NLP keeps bulk ingest fast.
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "google_news",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "query_count": batch["query_count"],
        "queries_run": batch["queries_run"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/reddit-pullpush")
def ingest_reddit_pullpush(
    query: str = Query(default="side effect adverse reaction", min_length=2),
    limit: int = 50,
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Ingest Reddit posts via Pullpush.io archive API — works when reddit.com is blocked.

    Same 29 curated health subreddits as the standard reddit_health crawler,
    but routes through the Pullpush mirror instead of reddit.com directly.
    """
    batch = crawl_reddit_pullpush(query=query, limit=limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "reddit_pullpush",
        "method": "pullpush.io",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "subreddit_count": batch["subreddit_count"],
        "ingested": new,
        **stats,
    }


@router.get("/ingest/reddit-health/subs")
def list_reddit_health_subs():
    """Curated health subreddit panel used by reddit_health crawls."""
    subs = reddit_health_subs()
    return {"count": len(subs), "subreddits": subs}


@router.post("/ingest/reddit-health")
def ingest_reddit_health(query: str = Query(..., min_length=2), limit: int = 60,
                         recompute: bool = False, db: Session = Depends(get_db)):
    batch = crawl_reddit_health(query, limit)
    posts = batch["posts"]
    new = ingest_posts(db, posts)
    stats = _maybe_recompute(db, recompute)
    return {
        "source": "reddit_health",
        "fetched": len(posts),
        "unique_fetched": batch["unique_fetched"],
        "subreddit_count": batch["subreddit_count"],
        "subs_queried": batch["subs_queried"],
        "ingested": new,
        **stats,
    }


@router.post("/ingest/twitter")
def ingest_twitter(query: str = Query(..., min_length=2), limit: int = 25,
                   recompute: bool = False, db: Session = Depends(get_db)):
    posts = crawl_twitter(query, limit)
    new = ingest_posts(db, posts)
    stats = _maybe_recompute(db, recompute)
    return {"source": "twitter", "fetched": len(posts), "ingested": new,
            "note": "configure TWITTERAPI_IO_KEY for live data" if not posts else None,
            **stats}


@router.post("/ingest/fhir")
def ingest_fhir(payload: dict, recompute: bool = False, db: Session = Depends(get_db)):
    """Ingest a FHIR R4 Bundle or single AdverseEvent / MedicationStatement resource.

    Parses the submitted JSON into VigilAI post format (platform='fhir'),
    runs the same NLP → signal-recompute pipeline as all other ingest sources,
    and returns ingested post count plus updated signal statistics.

    Uses lexicon-tier NLP (use_transformer=False) — FHIR data is structured/clinical
    so the enriched symptom lexicon (rhabdomyolysis, angioedema, etc.) is sufficient
    and avoids the heavy transformer model load on first call.
    """
    posts = parse_fhir_bundle(payload)
    if not posts:
        return {"ingested": 0, "signals": 0, "alerts": 0, "reports": 0,
                "detail": "No parseable AdverseEvent or MedicationStatement resources found."}
    new = ingest_posts(db, posts, use_transformer=False, use_presidio=False)
    stats = _maybe_recompute(db, recompute)
    return {"source": "fhir", "parsed": len(posts), "ingested": new, **stats}


@router.get("/fhir/sample")
def fhir_sample():
    """A small valid FHIR R4 Bundle (EHR adverse events) for demo/paste-and-ingest."""
    return sample_bundle()


@router.post("/stream/tick")
def stream_tick(n: int = 3, recompute: bool = False, db: Session = Depends(get_db)):
    """Simulate a real-time streaming batch arriving.

    Uses fast lexicon NLP path. Signal recompute is skipped by default
    (fast demo tick). Pass recompute=true to trigger full stats recalculation.
    """
    from .helpers import dashboard_stats
    from ..projects.scope import current_project_id
    posts = stream_batch(n)
    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    if recompute:
        stats = _maybe_recompute(db, recompute)
    else:
        stats = dashboard_stats(db, project_id=current_project_id())
    return {"streamed": new, **stats}


@router.post("/reset")
def reset(db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    db.query(Alert).delete()
    db.query(Signal).delete()
    db.query(ProcessedPost).delete()
    db.query(RawPost).delete()
    db.query(AuditLog).delete()
    db.commit()
    return {"status": "cleared"}


@router.post("/prewarm")
def prewarm(limit: int = 12, db: Session = Depends(get_db)):
    """Eagerly cache external evidence (DailyMed/PubMed/recalls/device-class) on the
    top signals so they open instantly during a live demo. Safe + rate-limit aware."""
    return prewarm_signals(db, limit=limit)


@router.post("/demo/prepare")
def demo_prepare(db: Session = Depends(get_db)):
    """Back-date detection/alert timestamps + pre-review a few signals so the KPIs
    and SPC control chart tell a realistic story (clearly synthetic demo data)."""
    info = prepare_demo(db)
    threading.Thread(target=_prewarm_background, kwargs={"limit": 12}, daemon=True).start()
    return info


@router.post("/ingest/dedupe-content")
def ingest_dedupe_content(
    recompute: bool = Query(False, description="Also recompute signals (slow; openFDA lookups)"),
    db: Session = Depends(get_db),
):
    """Backfill content hashes and purge syndicated narrative duplicates.

    Keeps the earliest RawPost per SHA-256 fingerprint; bumps ``duplicate_count``
    on the master; deletes clone rows + ProcessedPost.
    """
    from ..nlp.content_dedupe import backfill_and_purge_duplicates
    from ..projects.scope import current_project_id

    pid = current_project_id()
    result = backfill_and_purge_duplicates(db, project_id=pid)
    out = {**result, "recomputed": False}
    if recompute:
        stats = recompute_signals(db, project_id=pid)
        out["recomputed"] = True
        out.update(stats)
    return out


@router.post("/normalize/labels")
def normalize_labels(db: Session = Depends(get_db)):
    """Collapse casing/fragment AE labels (Air/air/aller) without full reprocess."""
    from ..nlp.normalize_cleanup import scrub_signal_labels
    from ..projects.rdf_graph import _FILTER_OPTS_CACHE, _GRAPH_CACHE, _GRAPH_SIG
    from ..projects.scope import current_project_id

    scrub = scrub_signal_labels(db, project_id=current_project_id())
    _GRAPH_CACHE.clear()
    _GRAPH_SIG.clear()
    _FILTER_OPTS_CACHE.clear()
    return scrub


# --------------------------- product ontology ------------------------------ #
@router.get("/ontology/resolve")
def ontology_resolve(term: str, online: bool = False):
    """Resolve any product surface to its concept (brand / generic / chemical)."""
    from ..nlp.ontology import ontology_stack, resolve_product

    concept = resolve_product(term, online=online)
    return {
        "term": term,
        "concept": concept.to_dict(),
        "ontology_stack": ontology_stack(),
    }


@router.get("/ontology/expand")
def ontology_expand(term: str, online: bool = False):
    """Full alias closure for a product term, grouped by naming tier."""
    from ..nlp.ontology import expand_product, known_dual_groups, ontology_stack

    return {
        "term": term,
        **expand_product(term, online=online),
        "inn_dual_groups": known_dual_groups(),
        "ontology_stack": ontology_stack(),
    }


@router.get("/ontology/compare")
def ontology_compare(product: str, online: bool = False, db: Session = Depends(get_db)):
    """Per-alias vs pooled AE counts — shows naming fragmentation for a product."""
    from ..analytics.ontology_compare import compare_product_aliases
    from ..projects.scope import current_project_id

    return compare_product_aliases(
        db, product, project_id=current_project_id(), online=online
    )


# --------------------- enterprise ontology mapping engine ------------------- #
@router.get("/ontology/engine/map")
def ontology_engine_map(
    verbatim: str,
    entity_type: str = "auto",
    failure_mode: str = "",
    online: bool = False,
):
    """Full ontology identity for one verbatim (event, drug, or device)."""
    from ..nlp.ontology_engine import map_verbatim_to_full_ontology

    mapped = map_verbatim_to_full_ontology(
        verbatim, entity_type, online=online, failure_mode=failure_mode
    )
    return mapped.model_dump()


@router.get("/ontology/engine/meddra-chain")
def ontology_engine_meddra_chain(term: str, online: bool = False):
    """LLT → PT → HLT → HLGT → SOC chain for an event verbatim."""
    from ..nlp.ontology_engine import meddra_mapper

    chain = meddra_mapper.map_event(term, online=online)
    return {**chain.model_dump(), "tiers": chain.tiers()}


@router.get("/ontology/engine/hierarchy")
def ontology_engine_hierarchy(soc_code: str = ""):
    """Nested SOC → HLGT → HLT → PT tree for the hierarchy playground."""
    from ..nlp.ontology_engine import meddra_mapper
    from ..nlp.ontology_engine.models import ONTOLOGY_VERSION, SURROGATE_DISCLAIMER

    return {
        "tree": meddra_mapper.hierarchy_snapshot(soc_code or None),
        "ontology_version": ONTOLOGY_VERSION,
        "disclaimer": SURROGATE_DISCLAIMER,
    }


@router.get("/ontology/engine/drug-chemical")
def ontology_engine_drug_chemical(term: str, online: bool = False):
    """Ingredient → ATC L1–L5 → ChEBI ID + SMILES (+ structural neighbours)."""
    from ..nlp.ontology_engine import drug_chemical_mapper

    return drug_chemical_mapper.map_drug(term, online=online).model_dump()


@router.get("/ontology/engine/device")
def ontology_engine_device(term: str, failure_mode: str = ""):
    """GMDN + EMDN + FDA/MDR risk class + SaMD flag + IMDRF failure mode."""
    from ..nlp.ontology_engine import device_mapper

    return device_mapper.map_device(term, failure_mode).model_dump()


@router.get("/ontology/engine/disproportionality")
def ontology_engine_disproportionality(
    product: str = "",
    min_count: int = 1,
    top_n: int = 100,
    db: Session = Depends(get_db),
):
    """PT-level and SOC-level disproportionality plus organ-class alerts."""
    from ..analytics.ontological_disproportionality import (
        compute_ontological_disproportionality,
    )
    from ..projects.scope import current_project_id

    return compute_ontological_disproportionality(
        db,
        project_id=current_project_id(),
        product=product or None,
        min_count=min_count,
        top_n=top_n,
    )


@router.get("/ontology/engine/knowledge-graph")
def ontology_engine_knowledge_graph(
    product: str = "",
    limit: int = 300,
    db: Session = Depends(get_db),
):
    """Heterogeneous ontology graph (typed nodes + relations) over signals."""
    from ..graph.knowledge_graph import build_ontology_graph
    from ..projects.scope import current_project_id

    return build_ontology_graph(
        db, project_id=current_project_id(), product=product or None, limit=limit
    )


@router.get("/ontology/engine/status")
def ontology_engine_status():
    """Which surrogate dictionaries loaded, their versions, and coverage counts."""
    from ..nlp.ontology_engine import engine_status

    return engine_status()


# --------------------- Omni-Search / brand-to-chemical gateway -------------- #
@router.get("/search/omni")
def search_omni(
    q: str,
    online: bool = False,
    subset: str = "",
    include_analytics: bool = True,
    db: Session = Depends(get_db),
):
    """Unified search: extract → BEL → RxE/RxNorm → ATC → Universe vs Subset."""
    from ..projects.scope import current_project_id
    from ..search_engine import omni_search

    brands = [b.strip() for b in subset.split(",") if b.strip()] or None
    return omni_search(
        q,
        db=db,
        online=online,
        subset_brands=brands,
        project_id=current_project_id(),
        include_analytics=include_analytics,
    ).model_dump()


@router.get("/search/resolve-brand")
def search_resolve_brand(term: str, online: bool = False):
    """Brand / noisy drug → UMLS CUI, ingredient RxCUIs, ATC classes."""
    from ..search_engine import resolve_brand_to_chemical

    return resolve_brand_to_chemical(term, online=online).model_dump()


@router.get("/search/autocomplete")
def search_autocomplete(q: str, kind: str = "drug", limit: int = 8):
    """Fuzzy MicroMeSH-style autocomplete for the Omni-Search dropdown."""
    from ..search_engine import autocomplete

    return {"query": q, "suggestions": autocomplete(q, kind=kind, limit=limit)}


@router.get("/search/universe-subset")
def search_universe_subset(
    term: str,
    subset: str = "",
    online: bool = False,
    top_n: int = 40,
    db: Session = Depends(get_db),
):
    """Universe (generic ingredient) vs Subset (brand) disproportionality."""
    from ..projects.scope import current_project_id
    from ..search_engine import omop_analytics, resolve_brand_to_chemical

    resolution = resolve_brand_to_chemical(term, online=online)
    brands = [b.strip() for b in subset.split(",") if b.strip()] or None
    return omop_analytics.compute_universe_vs_subset(
        db,
        resolution,
        subset_brands=brands,
        project_id=current_project_id(),
        top_n=top_n,
    ).model_dump()


@router.get("/search/status")
def search_engine_status():
    from ..search_engine import engine_status

    return engine_status()


# --------------------- Deep Medical Concept Normalization (MCN) ------------- #
@router.get("/normalization/status")
def normalization_status():
    """SapBERT / FAISS / gazetteer readiness for Module 2 MCN."""
    from ..normalization import engine_status

    return engine_status()


@router.get("/normalization/link")
def normalization_link(term: str, top_k: int = 5):
    """Embed a clinical span and link to UMLS CUI + MedDRA PT + SNOMED-CT."""
    from ..normalization import normalize_clinical_term

    return normalize_clinical_term(term, top_k=top_k).model_dump()


@router.get("/normalization/trace")
def normalization_trace(term: str):
    """Full ConceptMappingTrace payload (embed → cosine → MedDRA PT)."""
    from ..normalization import mapping_trace

    return mapping_trace(term).model_dump()


@router.get("/normalization/geo")
def normalization_geo(location: str):
    """Resolve municipal aliases (e.g. Madras → Chennai) with coordinates."""
    from ..normalization import normalize_location

    return normalize_location(location).model_dump()


@router.post("/normalization/aggregate")
def normalization_aggregate(payload: dict):
    """Collapse synonymous mentions and sum patient counts into cohort N."""
    from ..normalization import aggregate_clinical_cohorts

    mentions = payload.get("mentions") or []
    return aggregate_clinical_cohorts(mentions).model_dump()


@router.get("/normalization/normalize")
def normalization_normalize(clinical: str = "", location: str = ""):
    """Joint clinical + geographic normalization (MCP mirror)."""
    from ..normalization import normalize_clinical_and_geo_entities

    return normalize_clinical_and_geo_entities(clinical, location).model_dump()


@router.get("/normalization/expand")
def normalization_expand(q: str, online: bool = False):
    """Expand a free-text query: geo aliases + clinical synonyms + brand peers."""
    from ..normalization import expand_query

    return expand_query(q, online=online)


@router.get("/normalization/corpus")
def normalization_corpus(
    q: str,
    online: bool = False,
    db: Session = Depends(get_db),
):
    """Search posts/signals using MCN + geo + brand expansions (the useful path)."""
    from ..normalization import search_corpus_with_expansion
    from ..projects.scope import current_project_id

    return search_corpus_with_expansion(
        db, q, project_id=current_project_id(), online=online
    )


@router.get("/normalization/eval")
def normalization_eval():
    """Mantra GSC / CADEC-inspired F1 gate (must be > 0.85 for downstream ML)."""
    from ..normalization import evaluate_clinical_f1, evaluate_geo_f1

    clinical = evaluate_clinical_f1()
    geo = evaluate_geo_f1()
    return {
        "clinical": clinical.model_dump(),
        "geography": geo.model_dump(),
        "pass_gate": clinical.f1 > 0.85 and geo.f1 > 0.85,
        "threshold": 0.85,
    }


@router.post("/normalize/label-novelty")
def normalize_label_novelty(db: Session = Depends(get_db)):
    """Recompute FDA-label novelty tiers (in_label / novel / boxed) for existing signals."""
    from ..analytics.label_gap import refresh_label_novelty
    from ..projects.scope import current_project_id

    return refresh_label_novelty(db, project_id=current_project_id())


# --------------------------- dashboard ------------------------------------- #
@router.get("/dashboard/stats")
def get_stats(db: Session = Depends(get_db)):
    from ..projects.scope import current_project_id

    return dashboard_stats(db, project_id=current_project_id())


@router.get("/trends/overview")
def get_overview(db: Session = Depends(get_db)):
    from ..projects.scope import current_project_id

    return overview_timeseries(db, project_id=current_project_id())


# -------------------- bi-directional product ↔ AE analytics ---------------- #
@router.get("/analytics/drug-to-events/{drug_name:path}")
def analytics_drug_to_events(drug_name: str, db: Session = Depends(get_db)):
    """Forward path: medication/device → adverse events by severity tier."""
    from ..analytics.bidirectional import drug_to_events
    from ..projects.scope import current_project_id

    return drug_to_events(db, drug_name, project_id=current_project_id())


@router.get("/analytics/event-to-drugs/{event_name:path}")
def analytics_event_to_drugs(event_name: str, db: Session = Depends(get_db)):
    """Inverse path: adverse event → products ordered by PRR/ROR."""
    from ..analytics.bidirectional import event_to_drugs
    from ..projects.scope import current_project_id

    return event_to_drugs(db, event_name, project_id=current_project_id())


@router.get("/analytics/signal-audit/{signal_id}")
def analytics_signal_audit(signal_id: int, db: Session = Depends(get_db)):
    """Severity / DMA parameter audit for the clinical transparency popover.

    Exposes PRR, ROR, IC025, EBGM against corporate thresholds plus an explicit
    data-limitations block (patient-voice sentiment; unverified comorbidities).
    """
    from ..analytics.signal_audit import build_signal_audit

    payload = build_signal_audit(db, signal_id)
    if not payload:
        raise HTTPException(404, "signal not found")
    return payload


@router.get("/nlp/term-map")
def nlp_term_map(q: str):
    """Explain what a layman / raw phrase maps to (MedDRA-style PT + SOC)."""
    from ..nlp.term_glossary import explain_term

    if not (q or "").strip():
        raise HTTPException(400, "query parameter q is required")
    return explain_term(q.strip())


@router.get("/nlp/term-glossary")
def nlp_term_glossary():
    """Full patient-phrase → Preferred Term glossary for the Evidence UI."""
    from ..nlp.term_glossary import build_glossary

    return build_glossary()


@router.get("/nlp/resolver-status")
def nlp_resolver_status():
    """Diagnostics for the 3-pass hybrid resolver (RapidFuzz / SapBERT+Faiss / spaCy)."""
    from ..nlp.hybrid_resolver import resolver_status

    return resolver_status()


# --------------------------- signals --------------------------------------- #
@router.get("/signals")
def list_signals(
    strength: str | None = None,
    severity: str | None = None,
    min_prr: float | None = None,
    spiking: bool | None = None,
    pgx: bool | None = None,
    boxed: bool | None = None,
    mechanism: bool | None = None,
    class_effect: bool | None = None,
    active_comparator: bool | None = None,
    calibrated: bool | None = None,
    vaccine: bool | None = None,
    aesi: bool | None = None,
    spatial: bool | None = None,
    well_documented: bool | None = None,
    br: str | None = None,
    benefit_risk: bool | None = None,
    smq: str | None = None,
    region: str | None = None,
    soc: str | None = None,
    hr_elevated: bool | None = None,
    maxsprt: bool | None = None,
    label_novelty: str | None = None,
    lifecycle_status: str | None = None,
    drug: str | None = None,
    symptom: str | None = None,
    q: str | None = None,
    full: bool = False,
    db: Session = Depends(get_db),
):
    """List signals for the active project.

    Default payload is a compact list row (flags + badge tooltips). Pass
    ``full=true`` only when a caller needs nested evidence blobs; detail views
    should use ``GET /signals/{id}`` instead.
    """
    from sqlalchemy import or_

    from ..projects.scope import current_project_id
    from ..nlp.text_normalize import fold_key
    from ..api.helpers import _project_scope

    qset = db.query(Signal)
    pid = current_project_id()
    if pid is not None:
        # Include legacy NULL/0 project_id rows (same rule as dashboard_stats).
        qset = qset.filter(_project_scope(Signal.project_id, pid))
    if strength:
        qset = qset.filter(Signal.strength == strength.upper())
    if severity:
        qset = qset.filter(Signal.severity == severity)
    if min_prr is not None:
        qset = qset.filter(Signal.prr >= min_prr)
    if spiking:
        qset = qset.filter(Signal.spike_flag.is_(True))
    if pgx:
        qset = qset.filter(Signal.pgx_actionable.is_(True))
    if boxed:
        qset = qset.filter(Signal.boxed_warning.is_(True))
    if mechanism:
        qset = qset.filter(Signal.mechanism_plausible.is_(True))
    if class_effect:
        qset = qset.filter(Signal.class_effect.is_(True))
    if active_comparator:
        qset = qset.filter(Signal.stands_out_in_class.is_(True))
    if calibrated:
        qset = qset.filter(Signal.calibrated_signal.is_(True))
    if vaccine:
        qset = qset.filter(Signal.is_vaccine.is_(True))
    if aesi:
        qset = qset.filter(Signal.is_vaccine.is_(True), Signal.aesi.isnot(None))
    if spatial:
        qset = qset.filter(Signal.spatial_cluster.is_(True))
    if well_documented:
        qset = qset.filter(Signal.well_documented.is_(True))
    if benefit_risk:
        qset = qset.filter(Signal.br_verdict.isnot(None))
    if br:
        qset = qset.filter(Signal.br_verdict == br)
    if soc:
        qset = qset.filter(Signal.meddra_soc == soc)
    if hr_elevated:
        qset = qset.filter(Signal.hr_elevated.is_(True))
    if maxsprt:
        qset = qset.filter(Signal.maxsprt_crossed.is_(True))
    if label_novelty:
        qset = qset.filter(Signal.label_novelty == label_novelty.lower())
    if lifecycle_status:
        qset = qset.filter(Signal.lifecycle_status == lifecycle_status.lower())
    # Push text filters into SQL so Neon does not ship the full corpus then filter.
    if drug and drug.strip():
        qset = qset.filter(Signal.drug.ilike(f"%{drug.strip()}%"))
    if symptom and symptom.strip():
        term = f"%{symptom.strip()}%"
        qset = qset.filter(or_(Signal.symptom.ilike(term), Signal.meddra_pt.ilike(term)))
    if q and q.strip():
        # Expand clinical / geo / brand synonyms so Detect search does not miss
        # Madras when the user typed Chennai, or diabetic when PT is Diabetes mellitus.
        from sqlalchemy import or_

        terms = {q.strip()}
        try:
            from ..normalization import expand_query

            expansion = expand_query(q.strip())
            for t in (expansion.get("search_terms") or [])[:25]:
                if t and len(t) >= 2:
                    terms.add(t)
            for pt in ((expansion.get("clinical") or {}).get("preferred_pts") or []):
                terms.add(pt)
        except Exception:
            pass
        clauses = []
        for t in terms:
            like = f"%{t}%"
            clauses.extend([
                Signal.drug.ilike(like),
                Signal.symptom.ilike(like),
                Signal.meddra_pt.ilike(like),
            ])
        qset = qset.filter(or_(*clauses))

    signals = qset.order_by(Signal.prr.desc(), Signal.post_count.desc()).all()
    to_dict = signal_to_dict if full else signal_list_dict
    out = [to_dict(s) for s in signals]
    if region and region.lower() != "global":
        out = [s for s in out if region in (s.get("regions") or {})]
    if smq:
        out = [s for s in out if any(m.get("smq") == smq for m in (s.get("smq") or []))]
    # Keep fold_key refinement for fuzzy drug/symptom matches after ILIKE prefilter.
    if drug:
        dk = fold_key(drug)
        out = [s for s in out if dk and (dk in fold_key(s.get("drug") or "") or fold_key(s.get("drug") or "") in dk)]
    if symptom:
        sk = fold_key(symptom)
        out = [
            s for s in out
            if sk and (
                sk in fold_key(s.get("symptom") or "")
                or sk in fold_key((s.get("meddra") or {}).get("pt") or "")
                or fold_key(s.get("symptom") or "") in sk
            )
        ]
    return {"signals": out, "compact": not full}


# --------------------------- labeling-gap summary -------------------------- #
@router.get("/label-gap")
def get_label_gap(db: Session = Depends(get_db)):
    """Labeling-gap summary: tier counts + novel signal list.

    Returns counts by novelty tier (novel / in_label / boxed / unknown) and the
    list of signals classified as 'novel' — events not found in the drug's
    current FDA label adverse-reactions section.
    """
    signals = db.query(Signal).filter(Signal.product_type != "device").all()
    tier_counts = {"novel": 0, "in_label": 0, "boxed": 0, "unknown": 0}
    novel_signals = []
    for s in signals:
        tier = s.label_novelty or "unknown"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if tier == "novel":
            novel_signals.append({
                "id": s.id,
                "drug": s.drug,
                "event": s.meddra_pt or s.symptom,
                "meddra_pt": s.meddra_pt,
                "strength": s.strength,
                "prr": s.prr,
                "post_count": s.post_count,
                "label_gap": json.loads(s.label_gap_json or "null"),
            })
    novel_signals.sort(key=lambda x: (x.get("prr") or 0), reverse=True)
    return {
        "tier_counts": tier_counts,
        "total_signals": len(signals),
        "novel_count": tier_counts["novel"],
        "novel_signals": novel_signals,
        "note": (
            "novelty_tier is 'novel' when the event is not found in the drug's adverse_reactions "
            "section text from DailyMed (or our offline surrogate). 'boxed' when the boxed "
            "warning covers this event. 'in_label' when the event is already listed."
        ),
    }


@router.get("/label-filter")
def api_label_filter(
    product: str,
    event: str,
    online: bool = False,
    db: Session = Depends(get_db),
):
    """Module 1 — in-label vs novel tag + Weber alert-gate adjustment."""
    from ..analytics.label_filter import filter_product_event

    return filter_product_event(
        product, event, db=db, offline_only=not online,
    )


@router.post("/nlp/causality")
def api_nlp_causality(payload: dict):
    """Module 2 — WHO-UMC + Naranjo + de/rechallenge extraction."""
    from ..nlp.causality_engine import evaluate_narrative_causality

    text = payload.get("text") or ""
    if not str(text).strip():
        raise HTTPException(422, "text is required")
    return evaluate_narrative_causality(
        text,
        product=payload.get("product") or payload.get("drug") or "",
        event=payload.get("event") or payload.get("symptom") or "",
        fda_known=bool(payload.get("fda_known")),
        product_type=payload.get("product_type") or "drug",
        use_optional_bionlp=bool(payload.get("use_optional_bionlp", False)),
    )


@router.get("/signals/{signal_id}/triangulation")
def api_signal_triangulation(signal_id: int, db: Session = Depends(get_db)):
    """Module 3 — Social + FAERS/MAUDE + RWD triangulation."""
    from ..analytics.triangulation import triangulate_signal_row

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    return triangulate_signal_row(db, sig)


@router.get("/signals/{signal_id}")
def get_signal(
    signal_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Return signal + supporting posts immediately.

    Multi-source evidence (PubMed / DailyMed / recalls / device class / EUDAMED)
    is scheduled in the background on first view so free-tier network latency
    never blocks the Signal Detail page (was hanging on coronary stent, etc.).
    """
    from ..evidence.enrich import (
        enrich_signal_background,
        mark_enrich_pending,
        needs_network_enrichment,
    )

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")

    evidence_pending = False
    if needs_network_enrichment(sig.literature_json):
        # Claim the slot so concurrent clicks don't all hit external APIs
        sig.literature_json = mark_enrich_pending()
        db.commit()
        background_tasks.add_task(enrich_signal_background, signal_id)
        evidence_pending = True

    ids = json.loads(sig.supporting_post_ids or "[]")
    # Cap payload size — huge supporting sets were slowing serialization on devices
    ids = ids[:80]
    rows = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.id.in_(ids))
        .all()
    ) if ids else []
    supporting = [post_to_dict(p, r) for p, r in rows]
    from ..analytics.evidence_hierarchy import annotate_posts, evidence_mix
    from ..analytics.thread_score import score_thread
    supporting = annotate_posts(supporting)
    thread_posts = []
    for p, r in rows:
        ents = json.loads(p.entities_json or "{}")
        neg = json.loads(p.negation_json or "{}")
        thread_posts.append({
            "ae_flag": p.ae_flag,
            "sentiment": p.sentiment_label,
            "negation": bool(neg.get("negated") or neg.get("is_negated")),
            "drugs": ents.get("drugs") or [],
            "symptoms": ents.get("symptoms") or [],
            "body": r.body or "",
            "title": r.title or "",
            "platform": r.platform,
        })
    base = {
        **signal_to_dict(sig),
        "supporting_posts": supporting,
    }
    enriched = _enrich_gvp_modules(db, sig, base)
    thread_score = score_thread(thread_posts, drug=sig.drug or "",
                                symptom=sig.symptom or "")
    from ..analytics.copilot_tour import attach_feature_tour, build_feature_tour

    tour_payload = {**enriched, "thread_score": thread_score}
    # Always expose plain-English tour on detail (even before Draft Assessment)
    feature_tour = build_feature_tour(tour_payload)
    from ..analytics.copilot_verdicts import apply_verdicts
    feature_tour, bottom_line = apply_verdicts(feature_tour, tour_payload)
    copilot = enriched.get("copilot")
    if isinstance(copilot, dict):
        copilot = attach_feature_tour(copilot, tour_payload)
    else:
        # Lightweight shell so the UI can show the tour immediately
        copilot = attach_feature_tour(
            {
                "signal_summary": None,
                "recommendation": None,
                "disclaimer": (
                    "Prototype; synthetic data; openFDA = US FAERS/MAUDE only; "
                    "not for clinical use."
                ),
                "tour_only": True,
                "source": "feature_tour",
            },
            tour_payload,
        )

    return {
        **enriched,
        "copilot": copilot,
        "feature_tour": feature_tour,
        "bottom_line": bottom_line,
        "trend_series": signal_trend_series(db, sig),
        "supporting_posts": supporting,
        "evidence_mix": evidence_mix(supporting),
        "thread_score": thread_score,
        "evidence_pending": evidence_pending,
        "briefing": _attach_briefing(sig),
    }


def _enrich_gvp_modules(db: Session, sig: Signal, payload: dict) -> dict:
    """Attach label_filter + triangulation (+ light causality) on signal detail."""
    try:
        from ..analytics.label_filter import filter_product_event
        from ..analytics.triangulation import triangulate_signal
        from ..analytics.lifecycle import gvp_alias_for
        from ..nlp.causality_engine import evaluate_narrative_causality

        payload["label_filter"] = filter_product_event(
            sig.drug or "",
            sig.meddra_pt or sig.symptom or "",
            pt=sig.meddra_pt,
            soc=sig.meddra_soc,
            db=db,
            offline_only=True,
        )
        payload["triangulation"] = triangulate_signal(payload, db=db)
        payload["gvp_lifecycle_alias"] = gvp_alias_for(sig.lifecycle_status)
        # Causality on narrative / first supporting excerpt
        blob = sig.narrative or ""
        if not blob:
            for p in (payload.get("supporting_posts") or [])[:3]:
                blob += " " + (p.get("text") or "")
        fda = payload.get("fda_evidence") or {}
        payload["causality_assessment"] = evaluate_narrative_causality(
            blob,
            product=sig.drug or "",
            event=sig.meddra_pt or sig.symptom or "",
            fda_known=bool(fda.get("known")),
            product_type=sig.product_type or "drug",
        )
    except Exception:
        payload.setdefault("label_filter", None)
        payload.setdefault("triangulation", None)
        payload.setdefault("causality_assessment", None)
    return payload


def _attach_briefing(sig: Signal) -> dict:
    from ..analytics.signal_briefing import build_signal_briefing

    return build_signal_briefing(signal_to_dict(sig))



@router.get("/signals/{signal_id}/e2b")
def export_e2b(signal_id: int, db: Session = Depends(get_db)):
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    xml = generate_e2b_xml(signal_to_dict(sig))
    return Response(content=xml, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=e2b_r3_{signal_id}.xml"})


@router.get("/signals/{signal_id}/e2b-r2")
def export_e2b_r2(signal_id: int, db: Session = Depends(get_db)):
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    xml = generate_e2b_r2_xml(signal_to_dict(sig))
    return Response(content=xml, media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename=e2b_r2_{signal_id}.xml"})


@router.get("/signals/{signal_id}/cioms")
def export_cioms(signal_id: int, db: Session = Depends(get_db)):
    """Return a printable CIOMS Form I HTML for the signal."""
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    sd = signal_to_dict(sig)
    drug_slug = (sd.get("drug") or "drug").replace(" ", "_").lower()[:20]
    event_slug = (sd.get("symptom") or "event").replace(" ", "_").lower()[:20]
    html = generate_cioms_html(sd)
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename=cioms_{drug_slug}_{event_slug}.html"},
    )


@router.get("/signals/{signal_id}/cioms-text")
def export_cioms_text(signal_id: int, db: Session = Depends(get_db)):
    """Return a plain-text CIOMS Form I for the signal."""
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    sd = signal_to_dict(sig)
    drug_slug = (sd.get("drug") or "drug").replace(" ", "_").lower()[:20]
    event_slug = (sd.get("symptom") or "event").replace(" ", "_").lower()[:20]
    text = generate_cioms_text(sd)
    return Response(
        content=text,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename=cioms_{drug_slug}_{event_slug}.txt"},
    )


# -------------------- Phase A/B PV overlays (masking, DDI, SAR, casefile) --- #
@router.get("/signals/{signal_id}/masking")
def signal_masking_report(signal_id: int, db: Session = Depends(get_db)):
    """Competition-bias masking report + top masker drugs for this signal."""
    from collections import Counter, defaultdict

    from ..analytics.corpus import build_ae_reports
    from ..analytics.masking import analyze_masking
    from ..projects.scope import current_project_id

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    # Prefer MedDRA PT when present so soft-matching aligns with corpus events
    event = sig.meddra_pt or sig.symptom
    pid = sig.project_id or current_project_id()
    corpus = build_ae_reports(db, project_id=pid)
    out = analyze_masking(corpus["reports"], sig.drug, event)

    # When this pair monopolizes the event, point the analyst to remineable examples
    # (events in the corpus that have ≥2 products) so remine is one click away.
    examples = []
    if not out.get("can_remine"):
        by_event: dict[str, Counter] = defaultdict(Counter)
        for d, e in corpus["reports"]:
            by_event[e][(d or "").lower()] += 1
        # Prefer events where a secondary product would strengthen if the dominant is removed
        candidates = []
        for ev, counts in by_event.items():
            if len(counts) < 2:
                continue
            ranked = counts.most_common()
            dominant, dom_n = ranked[0]
            for other, n in ranked[1:4]:
                if n < 1:
                    continue
                candidates.append((n, dom_n, other, dominant, ev))
        candidates.sort(reverse=True)
        seen = set()
        for _n, _dom_n, other, dominant, ev in candidates:
            key = (other, ev.lower())
            if key in seen:
                continue
            seen.add(key)
            row = (
                db.query(Signal)
                .filter(Signal.drug.ilike(other))
                .filter(
                    (Signal.symptom.ilike(ev)) | (Signal.meddra_pt.ilike(ev))
                )
            )
            if pid is not None:
                row = row.filter(Signal.project_id == pid)
            row = row.first()
            if not row:
                # Fallback: match drug only, then check event soft-equality in Python
                q2 = db.query(Signal).filter(Signal.drug.ilike(other))
                if pid is not None:
                    q2 = q2.filter(Signal.project_id == pid)
                for cand in q2.limit(20).all():
                    ev_l = (ev or "").lower()
                    if (cand.symptom or "").lower() == ev_l or (cand.meddra_pt or "").lower() == ev_l:
                        row = cand
                        break
            if not row:
                continue
            examples.append({
                "signal_id": row.id,
                "drug": row.drug,
                "event": row.meddra_pt or row.symptom,
                "masker_hint": dominant,
                "why": f"Shares “{ev}” with {dominant} — remine can exclude the competitor.",
            })
            if len(examples) >= 4:
                break
    out["remineable_examples"] = examples
    out["try_next"] = (
        None if out.get("can_remine")
        else (
            "This product owns the whole event — remine has nothing to remove. "
            "Open one of the example signals below, or load the PV demo pack."
        )
    )
    return out


@router.get("/signals/{signal_id}/unmask")
@router.post("/signals/{signal_id}/unmask")
def signal_unmask_remine(
    signal_id: int,
    db: Session = Depends(get_db),
    exclude_drugs: list[str] | None = Query(None),
):
    """Remine DMA after excluding selected masker drugs (read-only sensitivity analysis).

    GET or POST — does not mutate the database (safe for viewers). Pass
    ``exclude_drugs`` as repeated query params, or omit to auto-pick suggested maskers.
    """
    from ..analytics.corpus import build_ae_reports
    from ..analytics.masking import analyze_masking, remine_unmasked
    from ..projects.scope import current_project_id

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    event = sig.meddra_pt or sig.symptom
    corpus = build_ae_reports(db, project_id=sig.project_id or current_project_id())
    exclude = list(exclude_drugs or [])
    if not exclude:
        report = analyze_masking(corpus["reports"], sig.drug, event)
        exclude = list(report.get("suggested_exclude") or [])
        if not exclude and report.get("maskers"):
            exclude = [report["maskers"][0]["drug"]]
    return remine_unmasked(
        corpus["posts"], sig.drug, event, exclude, full_reports=corpus["reports"]
    )


@router.get("/signals/{signal_id}/sar.md")
def export_sar_markdown(signal_id: int, db: Session = Depends(get_db)):
    """GVP Module IX Signal Assessment Report as Markdown."""
    from ..analytics.sar import build_sar_payload, render_sar_markdown

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    md = render_sar_markdown(build_sar_payload(db, sig))
    fname = f"sar_{sig.drug}_{sig.symptom}.md".replace(" ", "_")[:80]
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/signals/{signal_id}/sar.pdf")
def export_sar_pdf(signal_id: int, db: Session = Depends(get_db)):
    """GVP Module IX Signal Assessment Report as PDF."""
    from ..analytics.sar import build_sar_payload, render_sar_pdf

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    try:
        pdf = render_sar_pdf(build_sar_payload(db, sig))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    fname = f"sar_{sig.drug}_{sig.symptom}.pdf".replace(" ", "_")[:80]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/signals/{signal_id}/sar")
def signal_sar_json(signal_id: int, db: Session = Depends(get_db)):
    """Structured SAR payload (JSON) for UI preview."""
    from ..analytics.sar import build_sar_payload

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    return build_sar_payload(db, sig)


@router.get("/signals/{signal_id}/casefile")
def signal_casefile(signal_id: int, db: Session = Depends(get_db)):
    """Longitudinal DMA snapshots + trajectory for this signal."""
    from ..analytics.casefile import get_casefile, snapshot_signals

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    # Ensure at least the current week is persisted when the analyst opens the casefile
    try:
        snapshot_signals(db, [sig], project_id=sig.project_id)
    except Exception:
        pass
    return get_casefile(db, sig)


@router.get("/remine/lab")
def remine_lab(
    limit: int = 24,
    offset: int = 0,
    q: str | None = None,
    only: str = "all",
    sort: str = "impact",
    db: Session = Depends(get_db),
):
    """Corpus-wide competition-bias remine cards (before/after PRR + IC025).

    Screens every remine-eligible (product, event) pair — a pair qualifies when
    two or more distinct products report the same event. Supports search (``q``),
    filtering (``only``: all|actionable|unmasked|co_reported|vanished|attenuated|
    amplified|stable|evaluable|devices|high|moderate), sorting (``sort``:
    impact|coreporting|masking|delta|prr|count|risk) and paging.
    """
    from ..analytics.remine_lab import build_remine_lab
    from ..projects.scope import current_project_id

    return build_remine_lab(
        db,
        project_id=current_project_id(),
        limit=limit,
        offset=offset,
        q=q,
        only=only,
        sort=sort,
    )


@router.get("/remine/run")
@router.post("/remine/run")
def remine_run_pair(
    drug: str,
    event: str,
    db: Session = Depends(get_db),
    exclude_drugs: list[str] | None = Query(None),
):
    """Remine any (product, event) pair directly — no persisted Signal row needed.

    Read-only sensitivity analysis, so Remine lab cards stay actionable even when
    a pair has not been materialised into the signals table yet.
    """
    from ..analytics.corpus import build_ae_reports
    from ..analytics.masking import analyze_masking, remine_unmasked
    from ..analytics.remine_lab import effective_project_id
    from ..projects.scope import current_project_id

    # Same scope the lab screened in, so both surfaces agree on the same pair
    pid = effective_project_id(db, current_project_id())
    corpus = build_ae_reports(db, project_id=pid)
    exclude = list(exclude_drugs or [])
    if not exclude:
        report = analyze_masking(corpus["reports"], drug, event)
        exclude = list(report.get("suggested_exclude") or [])
        if not exclude and report.get("maskers"):
            exclude = [report["maskers"][0]["drug"]]
    return remine_unmasked(
        corpus["posts"], drug, event, exclude, full_reports=corpus["reports"]
    )


@router.get("/ddi")
def ddi_signals(
    drug: str | None = None,
    min_count: int = 1,
    plausible_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Drug–drug interaction co-mention disproportionality + plausibility gate."""
    from ..analytics.corpus import build_ae_reports
    from ..analytics.ddi import mine_ddi
    from ..projects.scope import current_project_id

    corpus = build_ae_reports(db, project_id=current_project_id())
    out = mine_ddi(
        corpus["posts"],
        min_count=min_count,
        require_plausible=plausible_only,
        focus_drug=drug,
        limit=limit,
    )
    pairs = out.get("pairs") or []
    # Actionable findings first: plausible / known pattern / STRONG
    def _rank(p):
        pl = p.get("plausibility") or {}
        return (
            1 if pl.get("plausible") else 0,
            1 if pl.get("known_pattern") else 0,
            1 if p.get("sdr_flag") else 0,
            {"STRONG": 3, "MODERATE": 2, "WEAK": 1}.get(p.get("strength"), 0),
            p.get("omega025") or -99,
            p.get("count") or 0,
        )
    pairs_sorted = sorted(pairs, key=_rank, reverse=True)
    from ..models import Signal

    pid = current_project_id()

    def _resolve(drug: str, event: str):
        if not drug:
            return None
        q = db.query(Signal).filter(Signal.drug.ilike(drug))
        if pid is not None:
            q = q.filter(Signal.project_id == pid)
        ev = (event or "").lower().strip()
        soft = []
        for cand in q.limit(60).all():
            for f in ((cand.symptom or "").lower(), (cand.meddra_pt or "").lower()):
                if f and (f == ev or (ev and (ev in f or f in ev))):
                    return cand
            soft.append(cand)
        return soft[0] if soft else None

    findings = []
    for p in pairs_sorted[:12]:
        pl = p.get("plausibility") or {}
        pattern = (pl.get("known_pattern") or {}).get("note")
        why = pattern or (
            "Mechanistic plausibility for at least one drug."
            if pl.get("plausible")
            else "Co-mentioned on AE posts — review clinically; not yet mechanism-gated."
        )
        sig_a = _resolve(p.get("drug_a"), p.get("event"))
        sig_b = _resolve(p.get("drug_b"), p.get("event"))
        findings.append({
            **p,
            "signal_id": (sig_a.id if sig_a else None) or (sig_b.id if sig_b else None),
            "signal_id_a": sig_a.id if sig_a else None,
            "signal_id_b": sig_b.id if sig_b else None,
            "headline": f"{p['drug_a'].title()} + {p['drug_b'].title()} → {p['event']}",
            "why_it_matters": why,
            "what_to_do": (
                "Open either product’s Safety Signal for triage / SAR."
                if (sig_a or sig_b)
                else "Prioritise for clinical review after confirming the pair appears in Detect."
            ),
        })
    out["pairs"] = pairs_sorted
    out["findings"] = findings
    out["needs_demo_seed"] = len([f for f in findings if (f.get("plausibility") or {}).get("plausible")]) < 2
    out["headline"] = (
        f"{len(findings)} interaction finding(s) to review — "
        f"{sum(1 for f in findings if (f.get('plausibility') or {}).get('plausible'))} plausibility-gated."
        if findings
        else "No co-mention pairs yet — load the PV demo pack for polypharmacy fixtures."
    )
    out["verdict"] = out["headline"]
    return out


@router.get("/signals/{signal_id}/ddi")
def signal_ddi(signal_id: int, db: Session = Depends(get_db)):
    """DDI pairs involving this signal's product."""
    from ..analytics.corpus import build_ae_reports
    from ..analytics.ddi import mine_ddi

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    corpus = build_ae_reports(db, project_id=sig.project_id)
    out = mine_ddi(corpus["posts"], focus_drug=sig.drug, min_count=1, limit=30)
    out["needs_demo_seed"] = len(out.get("pairs") or []) == 0
    out["verdict"] = (
        f"No co-mentioned partners for {sig.drug} yet — load the PV demo pack or FAERS bulk."
        if out["needs_demo_seed"]
        else f"{len(out['pairs'])} co-mention pair(s) involving {sig.drug}."
    )
    return out


@router.get("/pregnancy")
def pregnancy_cohort(db: Session = Depends(get_db)):
    """Pregnancy / teratogen cohort mode with stratified DMA + actionable findings.

    Findings are built only from AE-flagged corpus posts (same pool as Safety Signals).
    Phantom fixture DMA is not shown — load PV demo pack to persist real rows.
    """
    from ..analytics.corpus import build_ae_reports
    from ..analytics.pregnancy import stratified_pregnancy_dma
    from ..models import Signal
    from ..projects.scope import current_project_id

    pid = current_project_id()
    corpus = build_ae_reports(db, project_id=pid)
    out = stratified_pregnancy_dma(corpus["posts"])

    def _resolve_signal(drug: str, event: str):
        if not drug:
            return None
        q = db.query(Signal).filter(Signal.drug.ilike(drug))
        if pid is not None:
            q = q.filter(Signal.project_id == pid)
        ev = (event or "").lower().strip()
        soft = []
        for cand in q.limit(80).all():
            fields = [
                (cand.symptom or "").lower(),
                (cand.meddra_pt or "").lower(),
            ]
            for f in fields:
                if not f:
                    continue
                if f == ev or (ev and (ev in f or f in ev)):
                    return cand
            soft.append(cand)
        # Drug-only fallback when event labels diverge after MedDRA mapping
        return soft[0] if soft and not ev else None

    findings = []
    for s in (out.get("congenital_signals") or [])[:15]:
        sig = _resolve_signal(s.get("drug"), s.get("symptom"))
        findings.append({
            **s,
            "fixture": False,
            "signal_id": sig.id if sig else None,
            "headline": f"{s['drug'].title()} → {s['symptom']} (pregnancy / congenital stratum)",
            "why_it_matters": (
                "Classic teratogen / congenital-anomaly surveillance case — "
                "stratify pregnancy exposures separately from general adult DMA."
            ),
            "what_to_do": (
                "Open the signal for SAR / lifecycle triage, or corroborate with label boxed warnings."
                if sig
                else (
                    "Pair not yet in Detect — load PV demo pack (or recompute) so this "
                    "pregnancy ICSR becomes an AE-flagged signal row."
                )
            ),
        })

    other = []
    for s in (out.get("other_pregnancy_signals") or [])[:12]:
        sig = _resolve_signal(s.get("drug"), s.get("symptom"))
        other.append({**s, "signal_id": sig.id if sig else None})

    out["congenital_signals"] = out.get("congenital_signals") or []
    out["other_pregnancy_signals"] = other
    out["findings"] = findings
    out["fixture_blended"] = False
    out["needs_demo_seed"] = len(findings) < 2
    out["headline"] = (
        f"{len(findings)} congenital / teratogen finding(s) in the pregnancy cohort "
        f"({out.get('n_pregnancy_posts', 0)} pregnancy-context AE posts)."
        if findings
        else "No congenital findings in AE corpus yet — load the pregnancy demo pack to seed ICSRs."
    )
    out["verdict"] = out["headline"]
    out["how_to_use"] = (
        "Review congenital findings first → open the linked Safety Signal → export SAR / "
        "advance lifecycle. Findings map into the same Detect table as core DMA."
    )
    return out


@router.get("/risk-strata")
def risk_strata(
    product_id: str | None = None,
    target_ae_pt: str | None = None,
    min_confidence: float = 0.55,
    limit: int = 8,
    db: Session = Depends(get_db),
):
    """Proactive risk stratification — high-risk demographic/comorbidity segments.

    When product_id / target_ae_pt omitted, returns candidate pairs from the corpus
    plus a default stratification on the densest pair (demo-friendly).
    """
    from ..analytics.risk_strata import list_candidate_pairs, predict_high_risk_populations
    from ..projects.scope import current_project_id

    pid = current_project_id()
    candidates = list_candidate_pairs(db, project_id=pid, limit=40)
    pairs = candidates.get("pairs") or []

    if not product_id or not target_ae_pt:
        if not pairs:
            return {
                "product_id": product_id or "",
                "target_ae_pt": target_ae_pt or "",
                "model": "none",
                "segments": [],
                "findings": [],
                "candidate_pairs": [],
                "needs_demo_seed": True,
                "headline": "No AE corpus density for stratification — load PV demo pack or Fetch sources.",
                "verdict": "No AE corpus density for stratification — load PV demo pack or Fetch sources.",
                "how_to_use": (
                    "Pass product_id + target_ae_pt, or load corpus then reopen this lens."
                ),
                "disclaimer": candidates.get("disclaimer"),
                "ontology_stack": [],
                "evidence_sources": [],
            }
        product_id = product_id or pairs[0]["product_id"]
        target_ae_pt = target_ae_pt or pairs[0]["target_ae_pt"]

    out = predict_high_risk_populations(
        db,
        product_id=product_id,
        target_ae_pt=target_ae_pt,
        min_confidence=min_confidence,
        project_id=pid,
        limit=limit,
    )
    out["candidate_pairs"] = pairs
    return out


@router.post("/risk-strata/predict")
def risk_strata_predict(
    product_id: str = Query(..., min_length=1),
    target_ae_pt: str = Query(..., min_length=1),
    min_confidence: float = 0.55,
    db: Session = Depends(get_db),
):
    """Explicit predict endpoint (mirrors FastMCP ``predict_high_risk_populations``)."""
    from ..analytics.risk_strata import predict_high_risk_populations
    from ..projects.scope import current_project_id

    return predict_high_risk_populations(
        db,
        product_id=product_id,
        target_ae_pt=target_ae_pt,
        min_confidence=min_confidence,
        project_id=current_project_id(),
    )


@router.get("/risk-strata/rank")
@router.post("/risk-strata/rank")
def risk_strata_rank(
    product_id: str = Query(..., min_length=1),
    target_ae_pt: str = Query(..., min_length=1),
    top_n: int = 5,
    include_exploratory: bool = False,
    db: Session = Depends(get_db),
):
    """Rank subpopulations by Risk Elevation Multiplier (REM).

    REM = P(AE|Drug∩Subpop) / P(AE|Drug∩General). Keeps strata with REM≥1.5 and
    Yates χ²≥4 by default. Mirrors FastMCP ``rank_high_risk_populations``.
    """
    from ..analytics.risk_ranking import rank_high_risk_populations
    from ..analytics.risk_strata import list_candidate_pairs
    from ..projects.scope import current_project_id

    pid = current_project_id()
    out = rank_high_risk_populations(
        db,
        product_id=product_id,
        target_ae_pt=target_ae_pt,
        top_n=top_n,
        project_id=pid,
        include_exploratory=include_exploratory,
    )
    out["candidate_pairs"] = (list_candidate_pairs(db, project_id=pid, limit=40).get("pairs") or [])
    return out


# -------------- Phase 1–2: privacy / OMOP / 4-gate / feature store --------- #
@router.post("/privacy/hygiene")
def privacy_hygiene(payload: dict, db: Session = Depends(get_db)):
    """Run PII scrub + HMAC author hash + 30-day content-hash dedupe on one record."""
    from ..privacy.hygiene import hygiene_pipeline
    from ..projects.scope import current_project_id

    result = hygiene_pipeline(
        {
            "title": payload.get("title") or "",
            "body": payload.get("body") or payload.get("text") or "",
            "author": payload.get("author") or payload.get("username") or "",
        },
        db=db,
        project_id=payload.get("project_id") or current_project_id(),
        bump_duplicate=bool(payload.get("bump_duplicate", False)),
    )
    return result.to_dict()


@router.post("/omop/sync")
def omop_sync(
    limit: int = 500,
    ae_only: bool = True,
    db: Session = Depends(get_db),
):
    """Backfill OMOP CDM v5.4 staging tables from the VigilAI AE corpus."""
    from ..db.schemas.omop_mapper import sync_omop_from_corpus
    from ..projects.scope import current_project_id

    return sync_omop_from_corpus(
        db, project_id=current_project_id(), limit=limit, ae_only=ae_only
    )


@router.get("/omop/stats")
def omop_stats(db: Session = Depends(get_db)):
    from ..db.schemas.omop_cdm import (
        OmopConditionOccurrence,
        OmopDeviceExposure,
        OmopDrugExposure,
        OmopPerson,
    )

    return {
        "persons": db.query(OmopPerson).count(),
        "drug_exposures": db.query(OmopDrugExposure).count(),
        "device_exposures": db.query(OmopDeviceExposure).count(),
        "condition_occurrences": db.query(OmopConditionOccurrence).count(),
        "cdm": "OMOP CDM v5.4 staging (open surrogates)",
    }


@router.post("/nlp/four-gate")
def nlp_four_gate(payload: dict):
    """Run the Phase-2 4-gate deterministic NLP engine on raw text."""
    from ..nlp.four_gate_engine import run_four_gates

    text = payload.get("text") or ""
    if not text.strip():
        raise HTTPException(422, "text is required")
    return run_four_gates(
        text,
        use_transformer=bool(payload.get("use_transformer", False)),
        use_optional_bionlp=bool(payload.get("use_optional_bionlp", False)),
        discard_near_neutral=bool(payload.get("discard_near_neutral", True)),
    )


@router.get("/nlp/bioie-benchmark")
def nlp_bioie_benchmark(corpus: str = "bc5cdr", path: str | None = None):
    """Precision/recall/F1 adapter for BC5CDR / NCBI Disease–style corpora."""
    from ..nlp.bioie_benchmark import evaluate_corpus

    return evaluate_corpus(corpus=corpus, path=path)


@router.get("/nlp/optional-backends")
def nlp_optional_backends():
    """Report optional RoBERTa / scispaCy availability without forcing a model load."""
    from ..nlp.bionlp_optional import optional_backends_status

    return optional_backends_status()


@router.get("/feature-store/matrix")
@router.post("/feature-store/matrix")
def feature_store_matrix(
    product_id: str | None = None,
    target_ae_pt: str | None = None,
    include_explainability: bool = False,
    min_n: int = 1,
    db: Session = Depends(get_db),
):
    """Product–Event–Cohort feature matrix X (FastMCP ``get_normalized_feature_matrix``).

    ``include_explainability`` defaults False for speed — sample 4-gate traces
    are opt-in (they re-run NLP on corpus snippets).
    """
    from ..analytics.feature_store import get_normalized_feature_matrix
    from ..projects.scope import current_project_id

    return get_normalized_feature_matrix(
        db,
        product_id=product_id,
        target_ae_pt=target_ae_pt,
        project_id=current_project_id(),
        include_explainability=include_explainability,
    )


@router.post("/ingest/adapters/{adapter_name}")
def run_ingest_adapter(
    adapter_name: str,
    limit: int = 20,
    query: str | None = None,
    apply_hygiene: bool = True,
    source: str = "pubmed",
    mode: str = "health",
    db: Session = Depends(get_db),
):
    """Run a Phase-1 modular ingestion adapter (faers/maude/literature/reddit/clinical_notes)."""
    from ..ingestion.adapters import (
        ClinicalNotesAdapter,
        FaersAdapter,
        LiteratureAdapter,
        MaudeAdapter,
        RedditAdapter,
    )
    from ..projects.scope import current_project_id

    adapters = {
        "faers": FaersAdapter,
        "maude": MaudeAdapter,
        "literature": LiteratureAdapter,
        "reddit": RedditAdapter,
        "clinical_notes": ClinicalNotesAdapter,
    }
    cls = adapters.get(adapter_name.lower())
    if not cls:
        raise HTTPException(404, f"Unknown adapter. Choose from: {sorted(adapters)}")
    result = cls().run(
        db=db,
        project_id=current_project_id(),
        apply_hygiene=apply_hygiene,
        limit=limit,
        query=query,
        source=source,
        mode=mode,
    )
    return result.to_dict()


@router.post("/signals/{signal_id}/narrative")
def regenerate_narrative(signal_id: int, db: Session = Depends(get_db)):
    from ..analytics.narrative import build_narrative

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    nar = build_narrative(signal_to_dict(sig))
    sig.narrative = nar["text"]
    sig.narrative_source = nar["source"]
    db.commit()
    return {"narrative": nar["text"], "source": nar["source"]}


@router.post("/signals/{signal_id}/copilot")
def draft_copilot_assessment(signal_id: int, db: Session = Depends(get_db)):
    """Generate (or regenerate) a RAG-based structured signal-assessment memo.

    Retrieves all computed analytics for the signal, assembles a grounded evidence
    brief, and calls the local Ollama LLM for a structured pharmacovigilance memo.
    Falls back to a deterministic template when Ollama is unavailable.
    """
    from ..analytics.copilot import generate_assessment

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")

    # Ensure evidence is enriched before drafting (non-blocking claim + sync enrich with short timeout)
    if sig.literature_json in (None, "", "{}"):
        try:
            from ..evidence.enrich import enrich_one
            ev = enrich_one(sig.product_type or "drug", sig.drug, sig.symptom, timeout=2.0)
            sig.label_evidence_json = json.dumps(ev.get("label_evidence") or {})
            sig.recall_json = json.dumps(ev.get("recall") or {})
            sig.literature_json = json.dumps(ev.get("literature") or {"available": False, "source": "pubmed_offline"})
            sig.device_class_json = json.dumps(ev.get("device_classification") or {})
            db.commit()
        except Exception:
            db.rollback()
            try:
                sig.literature_json = json.dumps({"available": False, "source": "pubmed_offline"})
                db.commit()
            except Exception:
                db.rollback()

    # Prefer GVP-enriched payload so tour covers triangulation / label / causality
    base = signal_to_dict(sig)
    try:
        base = _enrich_gvp_modules(db, sig, base)
    except Exception:
        pass
    assessment = generate_assessment(base)
    sig.copilot_json = json.dumps(assessment)
    sig.copilot_source = assessment.get("source", "deterministic")
    db.commit()
    return assessment


class CopilotAskBody(BaseModel):
    question: str = Field("", description="Plain-language question about Signal Detail metrics")


@router.post("/signals/{signal_id}/copilot/ask")
def ask_copilot(signal_id: int, body: CopilotAskBody, db: Session = Depends(get_db)):
    """Plain-language Q&A over Signal Detail analytics (offline-first)."""
    from ..analytics.copilot_tour import answer_question, build_feature_tour
    from ..analytics.copilot_verdicts import apply_verdicts

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    question = (body.question or "").strip()
    base = signal_to_dict(sig)
    try:
        base = _enrich_gvp_modules(db, sig, base)
    except Exception:
        pass
    tour, bottom = apply_verdicts(build_feature_tour(base), base)
    result = answer_question(base, question, tour=tour)
    result["feature_tour"] = tour
    result["bottom_line"] = bottom
    return result


# --------------------------- sources / llm --------------------------------- #
@router.get("/sources")
def list_sources():
    return {"sources": SOURCES}


@router.get("/sources/stats")
def source_stats(db: Session = Depends(get_db)):
    """Per-source post count, AE yield, and NER yield (entity extraction rate).

    Used for the per-source sparkline / health panel on the Sources page.
    """
    from collections import defaultdict
    from sqlalchemy import func

    rows = (
        db.query(RawPost.platform, func.count(RawPost.id).label("total"))
        .group_by(RawPost.platform)
        .all()
    )
    ae_rows = (
        db.query(RawPost.platform, func.count(RawPost.id).label("ae"))
        .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
        .group_by(RawPost.platform)
        .all()
    )
    ae_map = {r.platform: r.ae for r in ae_rows}

    result = {}
    for r in rows:
        plat = r.platform or "unknown"
        # Normalize sub-platform (e.g. "reddit/AskDocs" → "reddit_health", "google_news/BBC" → "google_news")
        base = plat.split("/")[0] if "/" in plat else plat
        entry = result.setdefault(base, {"total": 0, "ae": 0, "platforms": []})
        entry["total"] += r.total
        entry["ae"] += ae_map.get(plat, 0)
        entry["platforms"].append(plat)

    out = []
    for src_id, data in result.items():
        total = data["total"]
        ae = data["ae"]
        out.append({
            "source_id": src_id,
            "total_posts": total,
            "ae_posts": ae,
            "ae_rate": round(ae / total, 3) if total else 0.0,
            "sub_platforms": data["platforms"][:5],
        })
    out.sort(key=lambda x: -x["total_posts"])
    return {"stats": out, "total_posts": sum(x["total_posts"] for x in out)}


@router.get("/llm/status")
def get_llm_status():
    return llm_status()


# --------------------------- story stepper (Step 5) ------------------------ #
@router.get("/story")
def get_story(
    event: str = Query(..., description="Adverse event / MedDRA PT"),
    drugs: str = Query(..., description="Comma-separated drug pair, e.g. DrugA,DrugB"),
    db: Session = Depends(get_db),
):
    """Guided 4-step drug–event comparison carousel (workspace-scoped via X-Project-Id)."""
    from ..projects.scope import current_project_id
    from ..projects.story import build_story

    drug_list = [d.strip() for d in drugs.split(",") if d.strip()]
    try:
        return build_story(db, event=event, drugs=drug_list, project_id=current_project_id())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story/candidates")
def get_story_candidates(db: Session = Depends(get_db)):
    from ..projects.scope import current_project_id
    from ..projects.story import list_story_candidates

    return list_story_candidates(db, current_project_id())


@router.get("/story/pdf")
def get_story_pdf(
    event: str = Query(...),
    drugs: str = Query(...),
    db: Session = Depends(get_db),
):
    from ..projects.scope import current_project_id
    from ..projects.story import build_story, story_pdf_bytes

    drug_list = [d.strip() for d in drugs.split(",") if d.strip()]
    try:
        payload = build_story(db, event=event, drugs=drug_list, project_id=current_project_id())
        pdf = story_pdf_bytes(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    fname = f"vigilai_story_{event[:40].replace(' ', '_')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/ingest/registries")
def ingest_multi_registries(
    query: str = Query("adverse event"),
    limit_per: int = Query(10, ge=1, le=50),
    recompute: bool = False,
    db: Session = Depends(get_db),
):
    """Cross-sectional mining: KAERS + Cochrane CENTRAL + MEDLINE/PubMed → privacy gateway → NLP."""
    from ..ingestion.registry_adapters import fetch_multi_registry
    from ..pipeline import ingest_posts, recompute_signals

    bundles = fetch_multi_registry(query, limit_per)
    posts = []
    for rows in bundles.values():
        posts.extend(rows)
    count = ingest_posts(db, posts) if posts else 0
    stats = _maybe_recompute(db, recompute and bool(count))
    return {
        "ingested": count,
        "by_source": {k: len(v) for k, v in bundles.items()},
        "signals": stats.get("signals", 0),
        "alerts": stats.get("alerts", 0),
        "recompute_queued": stats.get("recompute_queued", False),
    }


# --------------------------- posts / feed ---------------------------------- #
@router.get("/posts")
def list_posts(
    ae_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    from ..projects.scope import current_project_id

    q = db.query(ProcessedPost, RawPost).join(RawPost, ProcessedPost.raw_id == RawPost.id)
    pid = current_project_id()
    if pid is not None:
        q = q.filter(RawPost.project_id == pid)
    if ae_only:
        q = q.filter(ProcessedPost.ae_flag.is_(True))
    rows = q.order_by(RawPost.posted_at.desc()).limit(limit).all()
    return {"posts": [post_to_dict(p, r) for p, r in rows]}


@router.get("/posts/{post_id}")
def get_post(post_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.id == post_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "post not found")
    return post_to_dict(row[0], row[1])


# --------------------------- alerts ---------------------------------------- #
@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db)):
    from ..api.helpers import _project_scope
    from ..projects.scope import current_project_id

    q = db.query(Alert)
    pid = current_project_id()
    if pid is not None:
        q = q.filter(_project_scope(Alert.project_id, pid))
    alerts = q.order_by(Alert.created_at.desc()).all()
    return {"alerts": [alert_to_dict(a) for a in alerts]}


@router.get("/alerts/outbound")
def list_outbound_deliveries(limit: int = 20):
    from ..analytics.outbound import recent_deliveries
    return {"deliveries": recent_deliveries(limit),
            "webhook_configured": bool(settings.alert_webhook_url)}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(
    alert_id: int,
    action: str = Query("seen", pattern="^(seen|investigate|false_alarm)$"),
    by: str = Query("analyst"),
    notes: str = Query(""),
    db: Session = Depends(get_db),
):
    """Acknowledge an alert — optionally start investigation or mark false alarm.

    - seen: clear from inbox only
    - investigate: clear + move linked signal into Lifecycle "Looking into it"
      and Confirm it for Ops KPIs
    - false_alarm: clear + Reject lifecycle + Dismiss for Ops KPIs
    """
    from ..analytics.alert_actions import resolve_alert

    try:
        return resolve_alert(db, alert_id, action=action, by=by, notes=notes)
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 422, str(exc))


@router.post("/alerts/{alert_id}/notify")
def notify_alert(
    alert_id: int,
    dry_run: bool = False,
    and_investigate: bool = Query(
        True,
        description="After notify, also Investigate (ack + Workflow + Ops confirm). "
                    "Set false only for ping-without-ownership demos.",
    ),
    by: str = Query("analyst"),
    db: Session = Depends(get_db),
):
    """Push alert to Slack/Teams (or simulate), then by default start investigation.

    Notify alone used to be a dead-end webhook. Default ``and_investigate=true``
    means escalate = ping team AND open Workflow ("Looking into it") + Ops confirm.
    """
    from ..analytics.alert_actions import resolve_alert
    from ..analytics.outbound import dispatch_alert

    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "alert not found")
    result = dispatch_alert(alert_to_dict(a), dry_run=dry_run)
    try:
        db.add(AuditLog(
            actor=by or "system",
            action="alert_notify",
            entity_type="alert",
            entity_id=alert_id,
            detail=json.dumps({
                "mode": result.get("mode"),
                "ok": result.get("ok"),
                "and_investigate": and_investigate,
            }),
        ))
        db.commit()
    except Exception:
        db.rollback()

    effects = None
    if and_investigate and result.get("ok") and not a.acknowledged:
        try:
            effects = resolve_alert(
                db, alert_id,
                action="investigate",
                by=by,
                notes="Escalated via Notify — team pinged and investigation opened.",
            )
        except ValueError as exc:
            raise HTTPException(404 if "not found" in str(exc) else 422, str(exc))

    result["alert_id"] = alert_id
    result["signal_id"] = a.signal_id
    result["and_investigate"] = and_investigate
    result["effects"] = effects
    if effects:
        result["next_step"] = (
            "Team notified · investigation opened on Workflow · confirmed in Ops KPIs."
        )
    elif and_investigate and a.acknowledged:
        result["next_step"] = "Team notified. Alert was already handled — Workflow unchanged."
    else:
        result["next_step"] = (
            "Team notified only (ping). Still open — Investigate or False alarm to decide."
        )
    return result


# --------------------------- signal review (HCP feedback) ------------------ #
@router.post("/signals/{signal_id}/review")
def review_signal(signal_id: int, state: str = Query(..., pattern="^(confirmed|dismissed|unreviewed)$"),
                  by: str = "analyst", db: Session = Depends(get_db)):
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    sig.review_state = state
    sig.reviewed_by = by
    sig.reviewed_at = datetime.utcnow()
    db.add(AuditLog(actor=by, action="signal_reviewed", entity_type="signal",
                    entity_id=signal_id,
                    detail=f"{sig.drug} -> {sig.meddra_pt or sig.symptom} marked {state}"))
    db.commit()
    return {"status": "ok", "id": signal_id, "review_state": state}


# --------------------------- GVP Module IX lifecycle ----------------------- #
@router.patch("/signals/{signal_id}/lifecycle")
def update_lifecycle(
    signal_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Advance or reject a signal through the GVP Module IX lifecycle workflow.

    Body JSON: ``{status, owner?, notes?}``.
    Validates the state transition, updates the signal, and appends an audit log entry.
    """
    from ..analytics.lifecycle import (
        LIFECYCLE_TRANSITIONS,
        compute_priority,
        gvp_alias_for,
        is_valid_transition,
        normalize_lifecycle_status,
        valid_next_states,
    )

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")

    new_status = normalize_lifecycle_status(payload.get("status") or "")
    if new_status not in LIFECYCLE_TRANSITIONS:
        raise HTTPException(422, f"Invalid lifecycle_status '{payload.get('status')}'. "
                                 f"Valid states: {list(LIFECYCLE_TRANSITIONS)}")
    current = sig.lifecycle_status or "new"
    if not is_valid_transition(current, new_status):
        allowed = valid_next_states(current)
        raise HTTPException(422, f"Transition '{current}' → '{new_status}' is not permitted. "
                                 f"Allowed next states: {allowed}")

    owner = payload.get("owner") or sig.lifecycle_owner
    notes = payload.get("notes") if payload.get("notes") is not None else sig.lifecycle_notes

    from ..reports.inspection_audit import (
        append_sj_to_notes,
        build_sj_entry,
        require_justification,
    )

    just_err = require_justification(new_status, notes)
    if just_err:
        # Don't hard-break Register / Kanban one-click advances — provision a
        # provisional rationale that still flags JUSTIFICATION_INCOMPLETE.
        notes = (
            "[PROVISIONAL_JUSTIFICATION] Terminal lifecycle action recorded without a full "
            "medical narrative. QPPV must replace this with a structured rationale before "
            "inspection close-out."
        )

    sj = build_sj_entry(
        signal_id=signal_id,
        actor=owner or "system",
        action="lifecycle_transition",
        from_status=current,
        to_status=new_status,
        rationale=notes or "",
        prev_hash="GENESIS",
    )
    notes = append_sj_to_notes(notes, sj)

    sig.lifecycle_status = new_status
    sig.lifecycle_owner = owner
    sig.lifecycle_notes = notes
    sig.lifecycle_updated_at = datetime.utcnow()

    db.add(AuditLog(
        actor=owner or "system",
        action="lifecycle_transition",
        entity_type="signal",
        entity_id=signal_id,
        detail=(f"{sig.drug} → {sig.meddra_pt or sig.symptom}: "
                f"{current} → {new_status}"
                + (f" (owner: {owner})" if owner else "")
                + (f" | {notes[:200]}" if notes else "")
                + f" | sjl:{sj['action_hash'][:16]}"),
    ))
    db.commit()
    db.refresh(sig)
    out = signal_to_dict(sig)
    out["gvp_lifecycle_alias"] = gvp_alias_for(sig.lifecycle_status)
    out["sjl_action_hash"] = sj["action_hash"]
    return out


@router.get("/gvp/register")
def gvp_register(
    db: Session = Depends(get_db),
    limit: int = 25,
    offset: int = 0,
):
    """GVP Module IX Signal Tracking Register (paginated table)."""
    from sqlalchemy import desc, nullslast

    from ..analytics.label_filter import filter_product_event
    from ..analytics.lifecycle import gvp_alias_for, valid_next_states
    from ..analytics.triangulation import triangulate_signal
    from ..projects.scope import current_project_id

    pid = current_project_id()
    q = db.query(Signal)
    if pid is not None:
        from sqlalchemy import or_
        q = q.filter(or_(Signal.project_id == pid, Signal.project_id.is_(None), Signal.project_id == 0))
    total = q.count()
    page_size = max(1, min(int(limit or 25), 100))
    page_offset = max(0, int(offset or 0))
    # SQL-side pagination — never load the full signal table into memory
    try:
        page_rows = (
            q.order_by(nullslast(desc(Signal.priority_score)), desc(Signal.id))
            .offset(page_offset)
            .limit(page_size)
            .all()
        )
    except Exception:
        # SQLite / dialects without NULLS LAST
        page_rows = (
            q.order_by(desc(Signal.priority_score), desc(Signal.id))
            .offset(page_offset)
            .limit(page_size)
            .all()
        )
    rows = []
    for s in page_rows:
        base = signal_to_dict(s, fda=False)
        try:
            lf = filter_product_event(
                s.drug or "", s.meddra_pt or s.symptom or "",
                pt=s.meddra_pt, soc=s.meddra_soc, db=db, offline_only=True,
            )
        except Exception:
            lf = {"tag": "UNKNOWN"}
        try:
            tri = triangulate_signal(base, db=db)
        except Exception:
            tri = {"urgency_tier": "INSUFFICIENT", "triangulated_risk_score": 0}
        status = s.lifecycle_status or "new"
        rows.append({
            "id": s.id,
            "product": s.drug,
            "event": s.meddra_pt or s.symptom,
            "strength": s.strength,
            "prr": s.prr,
            "chi_square": s.chi_square,
            "who_umc": s.who_umc,
            "severity": s.severity,
            "label_tag": (lf or {}).get("tag"),
            "is_in_label": (lf or {}).get("is_in_label"),
            "weber_adjusted": ((lf or {}).get("weber") or {}).get("weber_adjusted"),
            "triangulation_tier": (tri or {}).get("urgency_tier"),
            "triangulated_risk_score": (tri or {}).get("triangulated_risk_score"),
            "lifecycle_status": status,
            "gvp_alias": gvp_alias_for(status),
            "next_states": valid_next_states(status),
            "priority_score": s.priority_score or 0,
            "owner": s.lifecycle_owner,
            "updated_at": s.lifecycle_updated_at.isoformat() if s.lifecycle_updated_at else None,
        })
    return {
        "rows": rows,
        "n": len(rows),
        "total": total,
        "limit": page_size,
        "offset": page_offset,
        "page": (page_offset // page_size) + 1 if page_size else 1,
        "pages": max(1, (total + page_size - 1) // page_size) if page_size else 1,
        "disclaimer": (
            "GVP Module IX–shaped signal tracking register over VigilAI corpus. "
            "Prototype; not a validated QMS record."
        ),
    }


@router.get("/gvp/pbrer")
@router.get("/gvp/pbrer.md")
def gvp_pbrer_md(db: Session = Depends(get_db), signal_id: int | None = None):
    """Aggregate PBRER/PSUR draft (markdown)."""
    from fastapi.responses import PlainTextResponse
    from ..reports.pbrer import build_pbrer_payload, render_pbrer_markdown
    from ..projects.scope import current_project_id

    payload = build_pbrer_payload(db, signal_id=signal_id, project_id=current_project_id())
    return PlainTextResponse(render_pbrer_markdown(payload), media_type="text/markdown")


@router.get("/gvp/pbrer.pdf")
def gvp_pbrer_pdf(db: Session = Depends(get_db), signal_id: int | None = None):
    from fastapi.responses import Response
    from ..reports.pbrer import build_pbrer_payload, render_pbrer_pdf
    from ..projects.scope import current_project_id

    payload = build_pbrer_payload(db, signal_id=signal_id, project_id=current_project_id())
    data = render_pbrer_pdf(payload)
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": 'attachment; filename="vigilai_pbrer_draft.pdf"',
    })


@router.get("/gvp/pbrer.docx")
def gvp_pbrer_docx(db: Session = Depends(get_db), signal_id: int | None = None):
    from fastapi.responses import Response
    from ..reports.docx_pdf_generator import render_docx_or_markdown
    from ..reports.pbrer import build_pbrer_payload, render_pbrer_markdown
    from ..projects.scope import current_project_id

    payload = build_pbrer_payload(db, signal_id=signal_id, project_id=current_project_id())
    md = render_pbrer_markdown(payload)
    raw, media, ext = render_docx_or_markdown("PBRER / PSUR Draft", md, prefer_docx=True)
    return Response(raw, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="vigilai_pbrer_draft.{ext}"',
    })


@router.get("/signals/{signal_id}/pbrer.md")
def signal_pbrer_md(signal_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import PlainTextResponse
    from ..reports.pbrer import build_pbrer_payload, render_pbrer_markdown

    if not db.get(Signal, signal_id):
        raise HTTPException(404, "signal not found")
    payload = build_pbrer_payload(db, signal_id=signal_id)
    return PlainTextResponse(render_pbrer_markdown(payload), media_type="text/markdown")


@router.get("/signals/{signal_id}/pbrer.pdf")
def signal_pbrer_pdf(signal_id: int, db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from ..reports.pbrer import build_pbrer_payload, render_pbrer_pdf

    if not db.get(Signal, signal_id):
        raise HTTPException(404, "signal not found")
    payload = build_pbrer_payload(db, signal_id=signal_id)
    return Response(render_pbrer_pdf(payload), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="signal_{signal_id}_pbrer.pdf"',
    })


@router.get("/lifecycle/summary")
def lifecycle_summary(db: Session = Depends(get_db)):
    """GVP Module IX lifecycle dashboard.

    Returns signal counts by lifecycle status and the top 10 signals ranked by
    priority_score (descending) with key fields for triage.
    """
    from ..analytics.lifecycle import gvp_alias_for

    signals = db.query(Signal).all()
    counts: dict[str, int] = {s: 0 for s in LIFECYCLE_TRANSITIONS}
    for sig in signals:
        st = sig.lifecycle_status or "new"
        counts[st] = counts.get(st, 0) + 1

    top10 = sorted(signals, key=lambda s: s.priority_score or 0.0, reverse=True)[:10]
    return {
        "status_counts": counts,
        "total": len(signals),
        "top_by_priority": [
            {
                "id": s.id,
                "drug": s.drug,
                "event": s.meddra_pt or s.symptom,
                "priority_score": s.priority_score or 0.0,
                "lifecycle_status": s.lifecycle_status or "new",
                "gvp_alias": gvp_alias_for(s.lifecycle_status),
                "strength": s.strength,
                "severity": s.severity,
                "label_novelty": s.label_novelty or "unknown",
                "spike_flag": bool(s.spike_flag),
                "maxsprt_crossed": bool(s.maxsprt_crossed),
                "lifecycle_owner": s.lifecycle_owner,
            }
            for s in top10
        ],
        "workflow": LIFECYCLE_TRANSITIONS,
    }


# --------------------------- KPIs / quality / audit ------------------------ #
@router.get("/kpis")
def get_kpis(db: Session = Depends(get_db)):
    from ..projects.scope import current_project_id

    return compute_kpis(db, project_id=current_project_id())


@router.get("/audit")
def get_audit(limit: int = 100, db: Session = Depends(get_db)):
    return {"entries": recent_audit(db, limit)}


# --------------------------- surveillance source registry ------------------ #
@router.get("/surveillance/sources")
def get_surveillance_sources():
    return registry_summary()


# --------------------------- boxed (black-box) warnings -------------------- #
@router.get("/boxed-warnings")
def get_boxed_reference():
    """FDA boxed (black-box) warning registry backing the boxed-warning overlay."""
    from ..analytics.boxed_warnings import reference_table

    return reference_table()


# --------------------------- pharmacogenomics (PGx) ------------------------ #
@router.get("/pgx")
def get_pgx_reference():
    """CPIC/PharmGKB reference table backing the PGx risk overlay (offline surrogate)."""
    from ..analytics.pgx import reference_table

    return reference_table()


# --------------------------- mechanistic plausibility ---------------------- #
@router.get("/mechanism")
def get_mechanism_reference():
    """Drug MoA -> adverse-event knowledge base backing the mechanistic-plausibility
    (Bradford Hill biological plausibility) scoring (offline surrogate)."""
    from ..analytics.mechanism import reference_table

    return reference_table()


# --------------------------- SMQ syndromes --------------------------------- #
@router.get("/smq")
def get_smq(db: Session = Depends(get_db)):
    """Syndrome-level (Standardised MedDRA Query) disproportionality aggregation.

    Pools member Preferred-Term reports per drug so a product that is weak on any
    single PT can surface as a signal at the syndrome level (e.g. DILI, SCAR).
    """
    from ..analytics.smq import aggregate_smq, reference

    sigs = db.query(Signal).filter(Signal.product_type != "device").all()
    signal_dicts = [
        {"drug": s.drug, "symptom": s.symptom, "meddra_pt": s.meddra_pt,
         "post_count": s.post_count}
        for s in sigs
    ]
    groups = aggregate_smq(signal_dicts)
    defs = reference()["smqs"]
    return {"groups": groups, "definitions": defs,
            "active_count": len(groups), "definition_count": len(defs)}


# --------------------------- empirical calibration ------------------------- #
@router.get("/calibration")
def get_calibration(db: Session = Depends(get_db)):
    """Empirical-null calibration summary (Schuemie/OHDSI): the fitted null estimated
    from negative-control signals present in the corpus, plus the control panel. Each
    signal's calibrated p-value / E-value live on the signal itself."""
    from ..analytics.calibration import calibration_summary_from_rows

    return calibration_summary_from_rows(db.query(Signal).all())


# --------------------------- class effect + read-across -------------------- #
@router.get("/class-effect")
def get_class_effect(db: Session = Depends(get_db)):
    """Class-level (ATC pharmacological subgroup) disproportionality aggregation.

    Pools member-drug reports per (ATC class, event) so a class-wide effect surfaces
    even when each individual drug looks modest (e.g. statins -> myalgia across
    several statins). ``class_effect`` groups have 2+ contributing member drugs.
    """
    from ..analytics.class_effect import aggregate_class, atc_class_key, reference

    sigs = db.query(Signal).filter(Signal.product_type != "device").all()
    inputs = [
        {"drug": s.drug, "atc": s.drug_atc, "pt": s.meddra_pt or s.symptom,
         "soc": s.meddra_soc, "post_count": s.post_count}
        for s in sigs if s.drug_atc
    ]
    groups = aggregate_class(inputs)
    return {
        "groups": groups,
        "class_effects": [g for g in groups if g["class_effect"]],
        "count": len(groups),
        "reference": reference(),
    }


# --------------------------- quantitative benefit–risk --------------------- #
@router.get("/benefit-risk")
def get_benefit_risk(db: Session = Depends(get_db)):
    """Quantitative benefit–risk overlay (BRAT/MCDA framing + NNT vs NNH).

    Builds per-signal benefit–risk rows from the stored non-device signals that
    carry a computed assessment, then rolls them up to a drug-centric table and a
    verdict distribution. This is an illustrative surrogate framing (illustrative
    NNT/NNV literature ranges + a report-derived NNH proxy), NOT a regulatory
    benefit–risk assessment.
    """
    from ..analytics import benefit_risk

    sigs = (
        db.query(Signal)
        .filter(Signal.product_type != "device", Signal.benefit_risk_json.isnot(None))
        .all()
    )
    rows = []
    for s in sigs:
        br = json.loads(s.benefit_risk_json or "null")
        if not br:
            continue
        rows.append({
            **br,
            "drug": s.drug,
            "symptom": s.symptom,
            "meddra_pt": s.meddra_pt,
            "signal_id": s.id,
            "severity": s.severity,
            "who_umc": s.who_umc,
        })
    return {
        "drugs": benefit_risk.drug_table(rows),
        "verdict_distribution": benefit_risk.verdict_distribution(rows),
        "reference": benefit_risk.reference(),
        "count": len(rows),
    }


# --------------------------- spatial (geographic) clusters ----------------- #
@router.get("/spatial")
def get_spatial(db: Session = Depends(get_db)):
    """Geographic cluster detection (Kulldorff-style spatial scan statistic).

    Flags signals whose reports concentrate in a country/region beyond the expected
    share implied by the corpus-wide geographic distribution of all AE reports — an
    early indicator of a bad manufacturing batch, a counterfeit/substandard product in
    a market, or a regional practice/reporting issue. Each cluster carries its hotspot,
    observed vs expected counts, relative risk (RR) and the Poisson log-likelihood
    ratio (LLR) scan score.
    """
    from ..analytics.spatial import reference, spatial_clusters

    # Corpus baseline geographic distribution from all AE reports.
    ae_rows = (
        db.query(RawPost)
        .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
        .all()
    )
    baseline = {
        "country": dict(Counter(r.country for r in ae_rows if r.country)),
        "region": dict(Counter((r.region or "Global") for r in ae_rows)),
    }

    # Per-supporting-post geography, then per-signal observed area counts.
    post_geo = {
        p.id: (raw.country, raw.region or "Global")
        for p, raw in db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .all()
    }
    signals_with_geo = []
    for s in db.query(Signal).all():
        ids = json.loads(s.supporting_post_ids or "[]")
        cc: Counter = Counter()
        rc: Counter = Counter()
        for pid in ids:
            geo = post_geo.get(pid)
            if not geo:
                continue
            country, region = geo
            if country:
                cc[country] += 1
            rc[region] += 1
        signals_with_geo.append({
            "drug": s.drug,
            "event": s.meddra_pt or s.symptom,
            "product_type": s.product_type or "drug",
            "post_count": s.post_count,
            "area_counts": {"country": dict(cc), "region": dict(rc)},
        })

    clusters = spatial_clusters(signals_with_geo, baseline)
    return {
        "clusters": clusters,
        "count": len(clusters),
        "baseline": baseline,
        "reference": reference(),
    }


# --------------------------- report completeness (vigiGrade-style) --------- #
@router.get("/completeness")
def get_completeness(db: Session = Depends(get_db)):
    """UMC vigiGrade-style report-completeness summary (documentation-quality surrogate).

    Returns the corpus-wide distribution of per-signal completeness scores, the
    average completeness, the well-documented count, and the mean coverage of each
    assessable dimension across all signals — plus the dimension/penalty reference.
    A documentation-quality surrogate adapted to social-listening fields (the true
    vigiGrade needs structured ICSR data not present in patient posts).
    """
    from ..analytics.completeness import DIMENSIONS, WELL_DOCUMENTED_THRESHOLD, reference

    signals = db.query(Signal).all()
    n = len(signals)
    scores = [s.completeness or 0.0 for s in signals]
    mean = round(sum(scores) / n, 3) if n else 0.0
    well = sum(1 for s in signals if s.well_documented)

    # Score histogram in 0.1-wide bands (0.0-1.0).
    bands = [f"{i/10:.1f}-{(i+1)/10:.1f}" for i in range(10)]
    hist = {b: 0 for b in bands}
    for sc in scores:
        idx = min(9, int(sc * 10))
        hist[bands[idx]] += 1

    # Mean per-dimension coverage across all signals (from stored completeness JSON).
    cov_totals: dict[str, float] = {key: 0.0 for key, *_ in DIMENSIONS}
    cov_n = 0
    for s in signals:
        detail = json.loads(s.completeness_json or "null")
        if not detail:
            continue
        cov = detail.get("dimension_coverage") or {}
        for key, *_ in DIMENSIONS:
            cov_totals[key] += float(cov.get(key, 0.0))
        cov_n += 1
    dimension_coverage = {
        key: round(cov_totals[key] / cov_n, 3) if cov_n else 0.0
        for key, *_ in DIMENSIONS
    }

    # Best / worst documented signals (small leaderboard for the UI).
    ranked = sorted(signals, key=lambda s: s.completeness or 0.0, reverse=True)
    def _brief(s: Signal) -> dict:
        return {"id": s.id, "drug": s.drug, "event": s.meddra_pt or s.symptom,
                "completeness": s.completeness, "well_documented": bool(s.well_documented),
                "post_count": s.post_count}

    return {
        "signal_count": n,
        "mean_completeness": mean,
        "well_documented_count": well,
        "well_documented_rate": round(well / n, 3) if n else 0.0,
        "threshold": WELL_DOCUMENTED_THRESHOLD,
        "histogram": [{"band": b, "count": hist[b]} for b in bands],
        "dimension_coverage": dimension_coverage,
        "best_documented": [_brief(s) for s in ranked[:5]],
        "worst_documented": [_brief(s) for s in ranked[-5:][::-1]] if n else [],
        "reference": reference(),
    }


# --------------------------- vaccine pharmacovigilance --------------------- #
@router.get("/vaccine")
def get_vaccine(db: Session = Depends(get_db)):
    """Vaccine safety surveillance: the AESI reference (vaccine registry + Adverse
    Events of Special Interest) plus an AESI-level summary of the vaccine signals
    currently detected, each with a Brighton case-definition-level surrogate and a
    self-controlled risk interval (SCRI) relative-incidence surrogate.

    Vaccine PV is a distinct discipline — biologicals given to healthy people are
    reviewed around a curated AESI list, graded against Brighton diagnostic levels,
    and quantified with self-controlled designs. Brighton levels and SCRI here are
    clearly-labelled social-listening surrogates (no true per-patient vaccination
    dates are available).
    """
    from ..analytics.vaccine import reference, vaccine_aesi_summary

    sigs = db.query(Signal).filter(Signal.is_vaccine.is_(True)).all()
    summary = vaccine_aesi_summary([signal_to_dict(s, fda=False) for s in sigs])
    return {"reference": reference(), **summary}


# --------------------------- background scheduler / stream worker ----------- #
@router.post("/scheduler/start")
def scheduler_start(interval: int = 30, mode: str = "stream",
                    query: str = "drug side effects"):
    return scheduler.start(interval=interval, mode=mode, query=query)


@router.post("/scheduler/stop")
def scheduler_stop():
    return scheduler.stop()


@router.get("/scheduler/status")
def scheduler_status_route():
    return scheduler.status()


# /api/stream/* — semantically-named streaming control aliases (same underlying worker).
# These expose the enhanced stream-session metadata (session_id, total_posts_ingested,
# batches_processed, started_at, latest_batch_at).
@router.post("/stream/start")
def stream_start(interval: int = 15, mode: str = "stream",
                 query: str = "drug side effects"):
    """Start the real streaming ingestion worker.

    Pulls from the simulated stream (mode='stream') or live Reddit RSS (mode='reddit')
    on a configurable interval, calling ingest_posts + a lightweight streaming recompute
    (use_fda=False to skip the openFDA pre-warm for speed). Tracks session metadata.
    """
    return scheduler.start(interval=interval, mode=mode, query=query)


@router.post("/stream/stop")
def stream_stop():
    """Stop the streaming ingestion worker."""
    return scheduler.stop()


@router.get("/stream/status")
def stream_status():
    """Return stream-session metadata: session_id, total_posts_ingested, batches_processed,
    started_at, latest_batch_at, plus the standard scheduler running/interval/mode fields."""
    return scheduler.status()


# --------------------------- knowledge graph ------------------------------- #
@router.get("/knowledge-graph")
def get_kg(db: Session = Depends(get_db)):
    from ..projects.rdf_graph import kg_filter_options

    graph = knowledge_graph(db)
    graph["filter_options"] = kg_filter_options(db, project_id=None)
    return graph


@router.get("/knowledge-graph/filters")
def get_kg_filters(db: Session = Depends(get_db)):
    """Dropdown options from all ingested posts and signals."""
    from ..projects.rdf_graph import kg_filter_options
    return kg_filter_options(db, project_id=None)

# =================== Next-gen frontiers (inspection / COU / PGx / ATMP / lot / BR) == #
@router.get("/inspection/portfolio")
def inspection_portfolio_api(db: Session = Depends(get_db), limit: int = 200):
    """GVP Module IX inspection-readiness portfolio (SLA lead-time + overdue)."""
    from ..reports.inspection_audit import inspection_portfolio
    return inspection_portfolio(db, limit=limit)


@router.get("/inspection/signals/{signal_id}")
def inspection_signal_api(signal_id: int, db: Session = Depends(get_db)):
    from ..reports.inspection_audit import inspection_risk_for_signal
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    return inspection_risk_for_signal(sig)


@router.get("/inspection/signals/{signal_id}/sjl")
def inspection_sjl_api(signal_id: int, db: Session = Depends(get_db), fmt: str = "json"):
    """Signal Justification Log (tamper-evident SHA-256 chain)."""
    from ..reports.inspection_audit import build_signal_justification_log, render_sjl_markdown
    payload = build_signal_justification_log(db, signal_id)
    if payload.get("error"):
        raise HTTPException(404, payload["error"])
    if (fmt or "json").lower() in ("md", "markdown", "txt"):
        return Response(
            content=render_sjl_markdown(payload),
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=sjl_{signal_id}.md"},
        )
    return payload


@router.get("/governance/cou")
def governance_cou_api():
    from ..governance.cou_manager import get_cou_boundaries
    return get_cou_boundaries()


@router.get("/governance/credibility")
def governance_credibility_api():
    from ..governance.cou_manager import run_credibility_scorecard
    return run_credibility_scorecard(allow_network=False)


@router.post("/governance/cou/assert")
def governance_cou_assert(payload: dict):
    from ..governance.cou_manager import assert_within_cou
    return assert_within_cou((payload or {}).get("action") or "")


@router.get("/pgx/associations")
def pgx_associations_api(drug: str = Query(..., min_length=1), event: str = "", offline: bool = True):
    from ..analytics.pgx_engine import get_pgx_gene_associations
    return get_pgx_gene_associations(drug, event=event, offline_only=offline)


@router.get("/signals/{signal_id}/pgx-profile")
def signal_pgx_profile(signal_id: int, db: Session = Depends(get_db)):
    from ..analytics.pgx_engine import profile_signal
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    return profile_signal(sig.drug or "", sig.meddra_pt or sig.symptom or "", soc=sig.meddra_soc)


@router.get("/signals/{signal_id}/longitudinal-biologics")
def signal_longitudinal_biologics(signal_id: int, db: Session = Depends(get_db)):
    from ..analytics.longitudinal_biologics import assess_signal_longitudinal
    from ..models import ProcessedPost, RawPost
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    ids = json.loads(sig.supporting_post_ids or "[]")[:60]
    texts, dated = [], []
    if ids:
        rows = (
            db.query(ProcessedPost, RawPost)
            .join(RawPost, ProcessedPost.raw_id == RawPost.id)
            .filter(ProcessedPost.id.in_(ids))
            .all()
        )
        for p, r in rows:
            texts.append((r.body or "")[:2000])
            if r.posted_at:
                dated.append((r.posted_at, 1 if p.ae_flag else 0))
    return assess_signal_longitudinal(sig, supporting_texts=texts, dated_counts=dated)


@router.get("/signals/{signal_id}/lot-clustering")
def signal_lot_clustering(signal_id: int, db: Session = Depends(get_db)):
    from ..analytics.lot_clustering import assess_lot_clustering, enrich_with_enforcement
    from ..models import ProcessedPost, RawPost
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    ids = json.loads(sig.supporting_post_ids or "[]")[:80]
    texts = []
    if ids:
        rows = (
            db.query(ProcessedPost, RawPost)
            .join(RawPost, ProcessedPost.raw_id == RawPost.id)
            .filter(ProcessedPost.id.in_(ids))
            .all()
        )
        texts = [(r.body or "")[:2500] for _, r in rows]
    out = assess_lot_clustering(texts, product=sig.drug or "", spike=bool(sig.spike_flag))
    out["enforcement"] = enrich_with_enforcement(sig.drug or "")
    return out


@router.get("/benefit-risk/proact")
def benefit_risk_proact(
    drug: str = Query(..., min_length=1),
    event: str = Query(..., min_length=1),
    strength: str = "WEAK",
    post_count: int = 0,
    offline: bool = True,
):
    from ..analytics.benefit_risk import evaluate_benefit_risk_ratio
    return evaluate_benefit_risk_ratio(
        drug, event, post_count=post_count, strength=strength, offline_only=offline,
    )


@router.get("/signals/{signal_id}/benefit-risk-proact")
def signal_benefit_risk_proact(signal_id: int, db: Session = Depends(get_db), offline: bool = True):
    from ..analytics.benefit_risk import evaluate_benefit_risk_ratio
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    return evaluate_benefit_risk_ratio(
        sig.drug or "",
        sig.meddra_pt or sig.symptom or "",
        post_count=int(sig.post_count or 0),
        strength=sig.strength or "WEAK",
        offline_only=offline,
    )


@router.get("/frontiers/summary")
def frontiers_summary(db: Session = Depends(get_db)):
    """One-shot portfolio for the Governance / Inspection hub."""
    from ..governance.cou_manager import run_credibility_scorecard
    from ..reports.inspection_audit import inspection_portfolio

    inspection = inspection_portfolio(db, limit=150)
    credibility = run_credibility_scorecard(allow_network=False)
    return {
        "inspection": inspection,
        "credibility": credibility,
        "modules": [
            {
                "id": "inspection_audit",
                "label": "Inspection readiness",
                "where": "Dashboard · Inspection & COU",
                "summary": (
                    f"{inspection.get('n_overdue', 0)} of {inspection.get('n_open', 0)} "
                    "open signals past SLA"
                ),
            },
            {
                "id": "cou_manager",
                "label": "Context of Use",
                "where": "Dashboard · Inspection & COU",
                "summary": (
                    f"Credibility index {credibility.get('model_credibility_index')} "
                    f"({credibility.get('credibility_band')})"
                ),
            },
            {
                "id": "pgx_engine",
                "label": "Pharmacogenomics",
                "where": "Signal Detail",
                "summary": "CPIC / PharmGKB gene–drug screen per signal",
            },
            {
                "id": "longitudinal_biologics",
                "label": "Delayed-toxicity watch",
                "where": "Signal Detail",
                "summary": "Multi-year windows for biologics and advanced therapies",
            },
            {
                "id": "lot_clustering",
                "label": "Lot clustering",
                "where": "Signal Detail",
                "summary": "Separates one bad batch from a product-wide effect",
            },
            {
                "id": "benefit_risk_proact",
                "label": "PrOACT-URL benefit–risk",
                "where": "Signal Detail + below",
                "summary": "Weighs the signal against the product's therapeutic benefit",
            },
        ],
    }

