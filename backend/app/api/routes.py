"""VigilAI REST API."""
from __future__ import annotations

import json
import threading
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
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
        term = f"%{q.strip()}%"
        qset = qset.filter(or_(
            Signal.drug.ilike(term),
            Signal.symptom.ilike(term),
            Signal.meddra_pt.ilike(term),
        ))

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


@router.get("/signals/{signal_id}")
def get_signal(signal_id: int, db: Session = Depends(get_db)):
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")

    # Lazy, cached multi-source evidence enrichment. Runs once per signal on
    # first view, then persisted. Device signals also get EUDAMED lookup.
    if sig.literature_json in (None, "", "{}"):
        try:
            from ..evidence.enrich import enrich_one
            ev = enrich_one(sig.product_type or "drug", sig.drug, sig.symptom)
            sig.label_evidence_json = json.dumps(ev.get("label_evidence") or {})
            sig.recall_json = json.dumps(ev.get("recall") or {})
            sig.literature_json = json.dumps(ev.get("literature") or {})
            sig.device_class_json = json.dumps(ev.get("device_classification") or {})
            # EUDAMED enrichment for device signals
            if (sig.product_type or "drug") == "device" and sig.drug:
                from ..ingestion.sources import query_eudamed
                eudamed = query_eudamed(sig.drug, timeout=6.0)
                if eudamed.get("available"):
                    existing = json.loads(sig.device_class_json or "{}")
                    existing["eudamed"] = eudamed
                    sig.device_class_json = json.dumps(existing)
            db.commit()
        except Exception:
            db.rollback()

    ids = json.loads(sig.supporting_post_ids or "[]")
    rows = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.id.in_(ids))
        .all()
    )
    supporting = [post_to_dict(p, r) for p, r in rows]
    from ..analytics.thread_score import score_thread
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
        })
    return {
        **signal_to_dict(sig),
        "trend_series": signal_trend_series(db, sig),
        "supporting_posts": supporting,
        "thread_score": score_thread(thread_posts, drug=sig.drug or "",
                                     symptom=sig.symptom or ""),
    }


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
    from ..analytics.corpus import build_ae_reports
    from ..analytics.masking import analyze_masking
    from ..projects.scope import current_project_id

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    corpus = build_ae_reports(db, project_id=sig.project_id or current_project_id())
    return analyze_masking(corpus["reports"], sig.drug, sig.symptom)


@router.post("/signals/{signal_id}/unmask")
def signal_unmask_remine(
    signal_id: int,
    db: Session = Depends(get_db),
    exclude_drugs: list[str] | None = Query(None),
):
    """Remine DMA after excluding selected masker drugs (sensitivity analysis).

    Pass ``exclude_drugs`` as repeated query params, or omit to auto-pick likely maskers.
    """
    from ..analytics.corpus import build_ae_reports
    from ..analytics.masking import analyze_masking, remine_unmasked
    from ..projects.scope import current_project_id

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    corpus = build_ae_reports(db, project_id=sig.project_id or current_project_id())
    exclude = list(exclude_drugs or [])
    if not exclude:
        report = analyze_masking(corpus["reports"], sig.drug, sig.symptom)
        exclude = [m["drug"] for m in report.get("maskers") or [] if m.get("likely_masker")]
        if not exclude and report.get("maskers"):
            exclude = [report["maskers"][0]["drug"]]
    return remine_unmasked(
        corpus["posts"], sig.drug, sig.symptom, exclude, full_reports=corpus["reports"]
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


@router.get("/ddi")
def ddi_signals(
    drug: str | None = None,
    min_count: int = 2,
    plausible_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Drug–drug interaction co-mention disproportionality + plausibility gate."""
    from ..analytics.corpus import build_ae_reports
    from ..analytics.ddi import mine_ddi
    from ..projects.scope import current_project_id

    corpus = build_ae_reports(db, project_id=current_project_id())
    return mine_ddi(
        corpus["posts"],
        min_count=min_count,
        require_plausible=plausible_only,
        focus_drug=drug,
        limit=limit,
    )


@router.get("/signals/{signal_id}/ddi")
def signal_ddi(signal_id: int, db: Session = Depends(get_db)):
    """DDI pairs involving this signal's product."""
    from ..analytics.corpus import build_ae_reports
    from ..analytics.ddi import mine_ddi

    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")
    corpus = build_ae_reports(db, project_id=sig.project_id)
    return mine_ddi(corpus["posts"], focus_drug=sig.drug, min_count=2, limit=30)


@router.get("/pregnancy")
def pregnancy_cohort(db: Session = Depends(get_db)):
    """Pregnancy / teratogen cohort mode with stratified DMA."""
    from ..analytics.corpus import build_ae_reports
    from ..analytics.pregnancy import stratified_pregnancy_dma
    from ..projects.scope import current_project_id

    corpus = build_ae_reports(db, project_id=current_project_id())
    return stratified_pregnancy_dma(corpus["posts"])


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

    # Ensure evidence is enriched before drafting (mirrors GET /signals/{id} logic)
    if sig.literature_json in (None, "", "{}"):
        try:
            from ..evidence.enrich import enrich_one
            ev = enrich_one(sig.product_type or "drug", sig.drug, sig.symptom)
            sig.label_evidence_json = json.dumps(ev.get("label_evidence") or {})
            sig.recall_json = json.dumps(ev.get("recall") or {})
            sig.literature_json = json.dumps(ev.get("literature") or {})
            sig.device_class_json = json.dumps(ev.get("device_classification") or {})
            db.commit()
        except Exception:
            db.rollback()

    assessment = generate_assessment(signal_to_dict(sig))
    sig.copilot_json = json.dumps(assessment)
    sig.copilot_source = assessment.get("source", "deterministic")
    db.commit()
    return assessment


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
    sig = db.get(Signal, signal_id)
    if not sig:
        raise HTTPException(404, "signal not found")

    new_status = (payload.get("status") or "").lower()
    if new_status not in LIFECYCLE_TRANSITIONS:
        raise HTTPException(422, f"Invalid lifecycle_status '{new_status}'. "
                                 f"Valid states: {list(LIFECYCLE_TRANSITIONS)}")
    current = sig.lifecycle_status or "new"
    if not is_valid_transition(current, new_status):
        allowed = valid_next_states(current)
        raise HTTPException(422, f"Transition '{current}' → '{new_status}' is not permitted. "
                                 f"Allowed next states: {allowed}")

    owner = payload.get("owner") or sig.lifecycle_owner
    notes = payload.get("notes") or sig.lifecycle_notes

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
                + (f" | {notes[:200]}" if notes else "")),
    ))
    db.commit()
    db.refresh(sig)
    return signal_to_dict(sig)


@router.get("/lifecycle/summary")
def lifecycle_summary(db: Session = Depends(get_db)):
    """GVP Module IX lifecycle dashboard.

    Returns signal counts by lifecycle status and the top 10 signals ranked by
    priority_score (descending) with key fields for triage.
    """
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


# --------------------------- quantitative benefit-risk --------------------- #
@router.get("/benefit-risk")
def get_benefit_risk(db: Session = Depends(get_db)):
    """Quantitative benefit-risk (BRAT/MCDA + NNT vs NNH) drug-level view.

    Collapses per-signal benefit-risk assessments to one row per (drug, indication),
    keeping the most concerning verdict. Illustrative surrogate, not a regulatory
    benefit-risk assessment.
    """
    from ..analytics.benefit_risk import drug_table, reference, verdict_distribution

    rows = []
    for s in db.query(Signal).all():
        br = json.loads(s.benefit_risk_json or "null")
        if br:
            rows.append({**br, "drug": s.drug, "signal_id": s.id,
                         "severity": s.severity, "who_umc": s.who_umc})
    return {
        "drugs": drug_table(rows),
        "verdict_distribution": verdict_distribution(rows),
        "n_assessed": len(rows),
        "reference": reference(),
    }


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