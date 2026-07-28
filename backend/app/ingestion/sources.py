"""Live data source adapters. Reddit public RSS needs no API key.

Twitter/forum adapters are stubbed to synthetic data unless keys are configured,
so the app always runs offline.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from typing import List
from urllib.parse import quote

import feedparser

from ..config import settings

# Worldwide source registry surfaced in the UI. "key_required" sources degrade
# to synthetic/empty when no key is present, so the app always runs.
SOURCES = [
    {"id": "reddit", "name": "Reddit (global)", "type": "social",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Public RSS search, no key"},
    {"id": "reddit_health", "name": "Reddit health subreddits", "type": "social",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": f"{len([])} curated health communities — see /api/ingest/reddit-health/subs"},
    {"id": "reddit_pullpush", "name": "Reddit via Pullpush (corporate-network safe)", "type": "social",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Reddit archive mirror — works when reddit.com is blocked by corporate firewall"},
    {"id": "google_news", "name": "Google News (health safety RSS)", "type": "news",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Public RSS search — drug safety, recalls, vaccine AEs (no key)"},
    {"id": "faers_live", "name": "FDA FAERS (live AE reports)", "type": "regulatory",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Pulls recent serious ICSR reports directly from openFDA FAERS (no key)"},
    {"id": "dailymed_rss", "name": "DailyMed label RSS", "type": "regulatory",
     "scope": "United States", "key_required": False, "status": "live",
     "note": "New & revised drug labels from NLM DailyMed (no key)"},
    {"id": "pubmed_live", "name": "PubMed literature (NCBI)", "type": "literature",
     "scope": "Global", "key_required": False, "status": "live",
     "note": "Recent PV / drug safety / vaccine AE articles via NCBI E-utilities (no key)"},
    {"id": "fda_medwatch", "name": "FDA MedWatch / EMA / WHO alerts", "type": "regulatory",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "MedWatch, EMA, WHO, MHRA safety alerts via Google News (6 regulatory queries)"},
    {"id": "fda_recalls", "name": "FDA recalls + enforcement (direct API)", "type": "regulatory",
     "scope": "United States", "key_required": False, "status": "live",
     "note": "Live openFDA enforcement API + Google News — drug/device/biologic recalls"},
    {"id": "fda_press", "name": "FDA drug approvals & press releases", "type": "regulatory",
     "scope": "United States", "key_required": False, "status": "live",
     "note": "New approvals, safety communications via Google News"},
    {"id": "twitter", "name": "X / Twitter", "type": "social",
     "scope": "Worldwide", "key_required": True,
     "status": "live" if settings.twitter_api_key else "optional",
     "note": "Live — TWITTERAPI_IO_KEY set" if settings.twitter_api_key else "Needs TWITTERAPI_IO_KEY"},
    {"id": "forum", "name": "Patient forums (agentic onboarding)", "type": "forum",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Auto-onboard any forum URL"},
    {"id": "openfda", "name": "openFDA FAERS", "type": "regulatory",
     "scope": "United States", "key_required": False, "status": "live",
     "note": "Evidence corroboration"},
    {"id": "fhir", "name": "FHIR/HL7 (EHR)", "type": "clinical",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Ingest FHIR R4 AdverseEvent/MedicationStatement bundles"},
    {"id": "hackernews", "name": "HackerNews (Algolia API)", "type": "social",
     "scope": "Global", "key_required": False, "status": "live",
     "note": "Drug safety / pharmacovigilance discussions via Algolia search API (no key)"},
    {"id": "life_science", "name": "Life-science news pack (RSS)", "type": "news",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "ScienceDaily, STAT, Nature Medicine, WHO, FiercePharma, Endpoints, GEN, NPR Health, Medical Xpress (no key)"},
    {"id": "youtube", "name": "YouTube videos + comments", "type": "social",
     "scope": "Global", "key_required": True,
     "status": "live" if os.getenv("YOUTUBE_API_KEY", "").strip() else "optional",
     "note": "Video titles/descriptions + AE comment threads via YouTube Data API v3 (needs YOUTUBE_API_KEY)"},
    # ── Device-specific live sources ──────────────────────────────────────────
    {"id": "mhra_devices", "name": "MHRA device alerts & FSNs (UK)", "type": "regulatory",
     "scope": "United Kingdom", "key_required": False, "status": "live",
     "note": "UK Field Safety Notices, Device Safety Information — gov.uk Atom feed, no key"},
    {"id": "maude_live", "name": "FDA MAUDE live (device AE reports)", "type": "regulatory",
     "scope": "United States", "key_required": False, "status": "live",
     "note": "Recent MDRs from MAUDE — device malfunctions, injuries, deaths — ingested as device signals"},
    {"id": "device_recalls", "name": "FDA device recalls & enforcement", "type": "regulatory",
     "scope": "United States", "key_required": False, "status": "live",
     "note": "openFDA device/enforcement + device-recall news — Class I/II device recalls as device posts"},
    {"id": "device_news", "name": "Medical device safety news", "type": "news",
     "scope": "Worldwide", "key_required": False, "status": "live",
     "note": "Google News RSS on CGM/pump/implant/CPAP/stent safety & recalls (no key)"},
    {"id": "eudamed", "name": "EUDAMED (EU device registry)", "type": "regulatory",
     "scope": "European Union", "key_required": False, "status": "live",
     "note": "EU device registration lookup — UDI, CE certificate, manufacturer, classification, no key"},
]

# Curated health subreddits for PV social listening (public RSS, no API key).
# Grouped for maintainability; all are searched on every reddit_health crawl.
_HEALTH_SUBS: List[dict] = [
    # General clinical Q&A
    {"sub": "AskDocs", "focus": "Patient questions to clinicians"},
    {"sub": "medical", "focus": "Medicine discussion"},
    {"sub": "medicine", "focus": "Physician / trainee community"},
    {"sub": "nursing", "focus": "Nursing practice"},
    {"sub": "pharmacy", "focus": "Pharmacist community"},
    {"sub": "Health", "focus": "General health"},
    {"sub": "AdverseEffects", "focus": "Drug adverse effects (dedicated)"},
    # Mental health / neuro (high AE-report volume)
    {"sub": "mentalhealth", "focus": "Mental health support"},
    {"sub": "depression", "focus": "Depression community"},
    {"sub": "anxiety", "focus": "Anxiety community"},
    {"sub": "ADHD", "focus": "ADHD medications"},
    {"sub": "bipolar", "focus": "Bipolar disorder"},
    {"sub": "epilepsy", "focus": "Anticonvulsants"},
    # Chronic disease (long-term drug exposure)
    {"sub": "diabetes", "focus": "Diabetes meds (metformin, GLP-1, insulin)"},
    {"sub": "diabetes_t1", "focus": "Type 1 diabetes — pumps, CGM, glucometers"},
    {"sub": "Type1Diabetes", "focus": "T1D devices (Omnipod, Dexcom, Tandem)"},
    {"sub": "ContinuousGlucoseMon", "focus": "CGM device experiences"},
    {"sub": "InsulinPump", "focus": "Insulin pump malfunctions / failures"},
    {"sub": "SleepApnea", "focus": "CPAP / BiPAP device issues"},
    {"sub": "HipReplacement", "focus": "Hip implant outcomes"},
    {"sub": "KneeReplacement", "focus": "Knee implant outcomes"},
    {"sub": "thyroid", "focus": "Thyroid / levothyroxine"},
    {"sub": "MultipleSclerosis", "focus": "MS disease-modifying drugs"},
    {"sub": "CrohnsDisease", "focus": "IBD biologics / immunosuppressants"},
    {"sub": "rheumatoid", "focus": "RA biologics / DMARDs"},
    {"sub": "psoriasis", "focus": "Immunosuppressants / biologics"},
    {"sub": "Fibromyalgia", "focus": "Pain / CNS meds"},
    {"sub": "ChronicPain", "focus": "Analgesics / opioids"},
    # Oncology
    {"sub": "cancer", "focus": "Chemo / immunotherapy AEs"},
    {"sub": "breastcancer", "focus": "Oncology AEs"},
    # Vaccines
    {"sub": "vaccines", "focus": "Vaccine safety discussion"},
    {"sub": "CovidVaccinated", "focus": "COVID-19 vaccine experiences"},
    # Women's / reproductive health
    {"sub": "birthcontrol", "focus": "Contraceptive AEs"},
    {"sub": "Pregnancy", "focus": "Pregnancy drug exposure"},
    # Dermatology (retinoids, biologics)
    {"sub": "SkincareAddiction", "focus": "Topical / oral dermatology drugs"},
    {"sub": "accutane", "focus": "Isotretinoin experiences"},
]

# Patch SOURCES note now that _HEALTH_SUBS is defined.
SOURCES[1]["note"] = (
    f"{len(_HEALTH_SUBS)} curated health communities (AskDocs, pharmacy, cancer, "
    f"vaccines, ADHD, diabetes…). GET /api/ingest/reddit-health/subs for the full list."
)


def reddit_health_subs() -> List[dict]:
    """Return the curated subreddit panel (for UI / API discovery)."""
    return [{"subreddit": s["sub"], "focus": s["focus"],
             "url": f"https://www.reddit.com/r/{s['sub']}/"}
            for s in _HEALTH_SUBS]


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def _entry_to_post(entry, sub: str | None = None) -> dict:
    body = getattr(entry, "summary", "") or getattr(entry, "title", "")
    posted = datetime.utcnow()
    if getattr(entry, "published_parsed", None):
        posted = datetime(*entry.published_parsed[:6])
    link = getattr(entry, "link", "")
    post = {
        "external_id": getattr(entry, "id", link),
        "platform": "reddit",
        "url": link,
        "author": _hash(getattr(entry, "author", "anon")),
        "title": getattr(entry, "title", ""),
        "body": body,
        "region": "Global",
        "posted_at": posted,
    }
    if sub:
        post["subreddit"] = sub
        post["source_label"] = f"r/{sub}"
    return post


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 VigilAI/1.0"
)


def _parse_rss_url(url: str):
    """Fetch RSS with a browser User-Agent (bare feedparser gets 403/429 on Reddit)."""
    try:
        import httpx

        r = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=12.0,
                        follow_redirects=True)
        if r.status_code == 200 and r.text:
            return feedparser.parse(r.text)
    except Exception:
        pass
    return feedparser.parse("")


def crawl_reddit_rss(query: str, limit: int = 25) -> List[dict]:
    """Search Reddit via public RSS (no auth). Returns [] on any failure."""
    posts: List[dict] = []
    try:
        q = quote(query)
        url = f"https://www.reddit.com/search.rss?q={q}&sort=new&limit={limit}"
        feed = _parse_rss_url(url)
        for entry in feed.entries[:limit]:
            posts.append(_entry_to_post(entry))
    except Exception:
        return []
    return posts


def crawl_reddit_health(query: str, limit: int = 60) -> dict:
    """Search across curated health subreddits (worldwide, no key).

    Dedupes by external_id across subs. Returns
    ``{posts, subs_queried, unique_fetched, subreddit_count}``.
    """
    posts: List[dict] = []
    seen: set[str] = set()
    subs_queried: List[str] = []
    per = max(2, limit // len(_HEALTH_SUBS))
    q = quote(query)

    for spec in _HEALTH_SUBS:
        sub = spec["sub"]
        subs_queried.append(sub)
        try:
            url = (f"https://www.reddit.com/r/{sub}/search.rss"
                   f"?q={q}&restrict_sr=1&sort=new&limit={per}")
            feed = _parse_rss_url(url)
            for entry in feed.entries[:per]:
                post = _entry_to_post(entry, sub=sub)
                eid = post["external_id"]
                if eid in seen:
                    continue
                seen.add(eid)
                posts.append(post)
        except Exception:
            continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "subs_queried": subs_queried,
        "subreddit_count": len(subs_queried),
        "unique_fetched": len(posts),
    }


# Curated Google News RSS queries for pharmacovigilance (no API key).
_GOOGLE_NEWS_QUERIES: List[dict] = [
    {"key": "drug_ae", "query": "drug side effect OR adverse drug reaction",
     "focus": "General drug adverse events"},
    {"key": "vaccine_ae", "query": "vaccine adverse reaction OR vaccine safety",
     "focus": "Vaccine safety signals"},
    {"key": "recall", "query": "FDA drug recall OR medicine recall",
     "focus": "Regulatory recalls"},
    {"key": "black_box", "query": "FDA safety warning OR boxed warning drug",
     "focus": "Safety communications / label warnings"},
    {"key": "pv", "query": "pharmacovigilance OR drug safety signal",
     "focus": "Industry / regulatory PV news"},
    {"key": "device_ae", "query": "medical device malfunction OR implant recall OR pacemaker failure",
     "focus": "Medical device adverse events"},
    {"key": "device_diabetes", "query": "insulin pump failure OR CGM inaccurate OR Dexcom Omnipod recall",
     "focus": "Diabetes device safety"},
    {"key": "device_cpap", "query": "CPAP recall OR Philips Respironics device safety",
     "focus": "Respiratory device safety"},
]


def google_news_queries() -> List[dict]:
    """Return the curated Google News query panel."""
    return [{"key": q["key"], "query": q["query"], "focus": q["focus"]}
            for q in _GOOGLE_NEWS_QUERIES]


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.encode("ascii", "ignore").decode("ascii")


def _news_entry_to_post(entry, query_key: str | None = None) -> dict:
    title = _strip_html(getattr(entry, "title", "") or "")
    summary = _strip_html(getattr(entry, "summary", "") or "")
    body = summary or title
    posted = datetime.utcnow()
    if getattr(entry, "published_parsed", None):
        posted = datetime(*entry.published_parsed[:6])
    link = getattr(entry, "link", "") or ""
    source_name = ""
    if getattr(entry, "source", None):
        source_name = getattr(entry.source, "title", "") or ""
    return {
        "external_id": getattr(entry, "id", link) or link,
        "platform": "google_news",
        "url": link,
        "author": _hash(source_name or "news"),
        "title": title[:500],
        "body": f"{title}. {body}"[:4000] if title and body != title else body[:4000],
        "region": "Global",
        "posted_at": posted,
        "news_source": source_name,
        "news_query": query_key,
        "product_type": "device" if (query_key or "").startswith("device_") else "drug",
    }


def crawl_google_news(query: str | None = None, limit: int = 40,
                      hl: str = "en-US", gl: str = "US") -> dict:
    """Fetch pharmacovigilance-relevant articles from Google News RSS (no key).

    If ``query`` is omitted, runs all curated PV queries and dedupes by article URL.
    Returns ``{posts, queries_run, unique_fetched, query_count}``.
    """
    posts: List[dict] = []
    seen: set[str] = set()
    queries_run: List[str] = []
    specs = _GOOGLE_NEWS_QUERIES if not query else [
        {"key": "custom", "query": query, "focus": "Custom search"},
    ]
    per = max(5, limit // len(specs))

    feed_errors: List[str] = []
    for spec in specs:
        qtext = spec["query"]
        queries_run.append(qtext)
        try:
            q = quote(qtext)
            url = (f"https://news.google.com/rss/search?q={q}"
                   f"&hl={hl}&gl={gl}&ceid={gl}:en")
            feed = _parse_rss_url(url)
            for entry in feed.entries[:per]:
                try:
                    post = _news_entry_to_post(entry, query_key=spec["key"])
                    eid = post["external_id"]
                    if eid in seen:
                        continue
                    seen.add(eid)
                    posts.append(post)
                except Exception:
                    continue
        except Exception as exc:
            feed_errors.append(f"{spec.get('key', 'query')}: {exc}")

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    out = {
        "posts": posts[:limit],
        "queries_run": queries_run,
        "query_count": len(queries_run),
        "unique_fetched": len(posts),
    }
    if feed_errors:
        out["feed_errors"] = feed_errors
    return out



def crawl_faers(limit: int = 30, days_back: int = 90) -> dict:
    """Pull recent serious adverse event reports from openFDA FAERS (no key).

    Converts each ICSR report into a VigilAI post: drug → symptom text so NLP
    can extract signals. Dedupes by FDA safety report ID.
    Returns ``{posts, unique_fetched, query_count}``.
    """
    import httpx
    from datetime import timedelta

    posts: List[dict] = []
    seen: set[str] = set()

    # Date window: last N days
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)
    date_range = f"{start:%Y%m%d}+TO+{end:%Y%m%d}"

    # openFDA date range uses [YYYYMMDD+TO+YYYYMMDD] syntax in the search param
    date_filter = f"receivedate:[{start:%Y%m%d}+TO+{end:%Y%m%d}]"
    queries = [
        f"serious:1+AND+{date_filter}",
        f"serious:1",  # fallback without date filter
    ]

    for search in queries:
        try:
            r = httpx.get(
                "https://api.fda.gov/drug/event.json",
                params={"search": search, "limit": limit // 2,
                        "sort": "receivedate:desc"},
                headers={"User-Agent": _USER_AGENT},
                timeout=12.0,
            )
            if r.status_code != 200:
                continue
            for event in r.json().get("results", []):
                safetyid = event.get("safetyreportid", "")
                if not safetyid or safetyid in seen:
                    continue
                seen.add(safetyid)

                drugs = event.get("patient", {}).get("drug", [])
                reactions = event.get("patient", {}).get("reaction", [])
                country = event.get("occurcountry", "")
                receive_date = event.get("receivedate", "")

                drug_names = [d.get("medicinalproduct", "").title()
                              for d in drugs if d.get("medicinalproduct")]
                reaction_terms = [r2.get("reactionmeddrapt", "")
                                  for r2 in reactions if r2.get("reactionmeddrapt")]

                if not drug_names or not reaction_terms:
                    continue

                drug_str = ", ".join(drug_names[:3])
                rx_str = ", ".join(reaction_terms[:5])
                body = (f"FDA adverse event report: {drug_str} associated with "
                        f"{rx_str}. Serious report received {receive_date}.")
                if event.get("serious") == "1":
                    body += " Serious case."

                # Parse date
                posted = datetime.utcnow()
                if receive_date and len(receive_date) == 8:
                    try:
                        posted = datetime.strptime(receive_date, "%Y%m%d")
                    except ValueError:
                        pass

                posts.append({
                    "external_id": f"faers_{safetyid}",
                    "platform": "faers",
                    "url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=reportsSearch.process&query={safetyid}",
                    "author": _hash("fda_faers"),
                    "title": f"FAERS: {drug_str[:60]} -> {rx_str[:60]}",
                    "body": body,
                    "region": _country_to_region(country),
                    "country": country or None,
                    "posted_at": posted,
                    "faers_report_id": safetyid,
                })
        except Exception:
            continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "query_count": len(queries),
    }


def crawl_dailymed_rss(limit: int = 40) -> dict:
    """Pull newly approved / updated drug labels from DailyMed RSS (no key).

    Converts each label entry into a post so the NLP pipeline can extract
    the drug name and any adverse-reaction language in the title/summary.
    Returns ``{posts, unique_fetched}``.
    """
    posts: List[dict] = []
    seen: set[str] = set()

    rss_urls = [
        "https://dailymed.nlm.nih.gov/dailymed/rss.cfm?type=newlabelxml&mailid=0",
        "https://dailymed.nlm.nih.gov/dailymed/rss.cfm?type=revisedlabelxml&mailid=0",
    ]

    for url in rss_urls:
        feed = _parse_rss_url(url)
        for entry in feed.entries[:limit // len(rss_urls)]:
            link = getattr(entry, "link", "") or ""
            eid = getattr(entry, "id", link) or link
            if not eid or eid in seen:
                continue
            seen.add(eid)
            title = _strip_html(getattr(entry, "title", "") or "")
            summary = _strip_html(getattr(entry, "summary", "") or "")
            posted = datetime.utcnow()
            if getattr(entry, "published_parsed", None):
                posted = datetime(*entry.published_parsed[:6])
            body = f"{title}. {summary}" if summary and summary != title else title
            posts.append({
                "external_id": f"dailymed_{_hash(eid)}",
                "platform": "dailymed",
                "url": link,
                "author": _hash("dailymed_nlm"),
                "title": title[:500],
                "body": body[:4000],
                "region": "Global",
                "posted_at": posted,
            })

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {"posts": posts[:limit], "unique_fetched": len(posts)}


def crawl_pubmed_live(query: str | None = None, limit: int = 20) -> dict:
    """Pull recent PubMed literature via NCBI E-utilities (no key, no SSL issues).

    Uses curated PV search terms if query is omitted. Converts each article into
    a post body mentioning drug + adverse reaction for NLP extraction.
    Returns ``{posts, unique_fetched, query_count}``.
    """
    import httpx

    pv_queries = [
        query or "pharmacovigilance adverse drug reaction",
        "drug safety signal detection",
        "vaccine adverse event",
    ] if not query else [query]

    posts: List[dict] = []
    seen: set[str] = set()
    per = max(3, limit // len(pv_queries))

    for q in pv_queries:
        try:
            # Step 1: search for PMIDs
            sr = httpx.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db": "pubmed", "term": q, "retmax": per,
                        "sort": "pub date", "retmode": "json",
                        **({"api_key": settings.ncbi_api_key} if settings.ncbi_api_key else {})},
                headers={"User-Agent": _USER_AGENT}, timeout=12.0,
            )
            if sr.status_code != 200:
                continue
            ids = sr.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                continue
            # Step 2: fetch summaries
            ss = httpx.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "json",
                        **({"api_key": settings.ncbi_api_key} if settings.ncbi_api_key else {})},
                headers={"User-Agent": _USER_AGENT}, timeout=12.0,
            )
            if ss.status_code != 200:
                continue
            result = ss.json().get("result", {})
            for pmid in ids:
                if pmid in seen or pmid not in result:
                    continue
                seen.add(pmid)
                art = result[pmid]
                title = art.get("title", "")
                authors = ", ".join(
                    a.get("name", "") for a in art.get("authors", [])[:3]
                )
                pub_date = art.get("pubdate", "")
                journal = art.get("source", "")
                body = (f"PubMed article: {title}. "
                        f"Authors: {authors}. Journal: {journal}. "
                        f"Published: {pub_date}.")

                posted = datetime.utcnow()
                try:
                    posted = datetime.strptime(pub_date[:4], "%Y")
                except ValueError:
                    pass

                posts.append({
                    "external_id": f"pubmed_{pmid}",
                    "platform": "pubmed_live",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "author": _hash(authors or "pubmed"),
                    "title": _strip_html(title[:500]),
                    "body": _strip_html(body[:4000]),
                    "region": "Global",
                    "posted_at": posted,
                    "pmid": pmid,
                })
        except Exception:
            continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "query_count": len(pv_queries),
    }


def _country_to_region(code: str) -> str:
    """Map ISO 2-letter country to broad region for pipeline geo-tagging."""
    _MAP = {
        "US": "North America", "CA": "North America", "MX": "North America",
        "GB": "Europe", "DE": "Europe", "FR": "Europe", "IT": "Europe",
        "ES": "Europe", "NL": "Europe", "SE": "Europe", "NO": "Europe",
        "CH": "Europe", "AT": "Europe", "BE": "Europe", "PL": "Europe",
        "PT": "Europe", "DK": "Europe", "FI": "Europe", "IE": "Europe",
        "IN": "Asia", "JP": "Asia", "CN": "Asia", "KR": "Asia",
        "AU": "Oceania", "NZ": "Oceania",
        "BR": "South America", "AR": "South America", "CO": "South America",
        "ZA": "Africa", "NG": "Africa", "KE": "Africa", "EG": "Africa",
    }
    return _MAP.get((code or "").upper(), "Global")


_REGULATORY_NEWS_QUERIES: list[dict] = [
    {"key": "fda_medwatch",  "query": "FDA MedWatch safety alert drug recall",              "label": "FDA MedWatch alerts"},
    {"key": "fda_recalls",   "query": "FDA recall drug device biologic enforcement",         "label": "FDA recalls & enforcement"},
    {"key": "fda_approvals", "query": "FDA drug approval new medicine approved",             "label": "FDA drug approvals"},
    {"key": "ema_safety",    "query": "EMA European Medicines Agency safety pharmacovigilance", "label": "EMA safety updates"},
    {"key": "who_alerts",    "query": "WHO World Health Organization drug safety alert",      "label": "WHO drug alerts"},
    {"key": "mhra_safety",   "query": "MHRA drug safety yellow card United Kingdom",         "label": "MHRA safety (UK)"},
]


def fda_rss_feeds() -> List[dict]:
    """Return the regulatory news query panel for UI/API discovery."""
    return [
        {"key": q["key"], "label": q["label"], "query": q["query"]}
        for q in _REGULATORY_NEWS_QUERIES
    ]


def crawl_fda_medwatch(limit: int = 30) -> dict:
    """FDA MedWatch safety alerts via Google News (confirmed working)."""
    return crawl_google_news("FDA MedWatch safety alert drug recall warning", limit=limit)


def crawl_fda_recalls(limit: int = 30) -> dict:
    """FDA recalls via Google News + openFDA enforcement API."""
    news = crawl_google_news("FDA recall drug device biologic enforcement action", limit=limit // 2)
    # Also pull from openFDA enforcement (confirmed working)
    enforcement_posts: List[dict] = []
    try:
        import httpx
        r = httpx.get(
            "https://api.fda.gov/drug/enforcement.json",
            params={"search": "status:Ongoing", "limit": limit // 2, "sort": "recall_initiation_date:desc"},
            headers={"User-Agent": _USER_AGENT}, timeout=10,
        )
        if r.status_code == 200:
            for rec in r.json().get("results", []):
                product = rec.get("product_description", "")[:80]
                reason = rec.get("reason_for_recall", "")[:200]
                brand = rec.get("brand_name", "")
                recalling_firm = rec.get("recalling_firm", "")
                date_str = rec.get("recall_initiation_date", "")
                posted = datetime.utcnow()
                try:
                    posted = datetime.strptime(date_str, "%Y%m%d") if date_str else posted
                except ValueError:
                    pass
                body = f"FDA drug recall: {brand or product}. Reason: {reason}. Firm: {recalling_firm}."
                eid = rec.get("recall_number", _hash(body))
                enforcement_posts.append({
                    "external_id": f"fda_enforce_{eid}",
                    "platform": "fda_enforcement",
                    "url": f"https://www.accessdata.fda.gov/scripts/enforcement/enforce_rpt-Product-Tabs.cfm",
                    "author": _hash("fda_enforcement"),
                    "title": f"FDA Recall: {brand or product[:60]}",
                    "body": body[:4000],
                    "region": "North America",
                    "country": "US",
                    "posted_at": posted,
                })
    except Exception:
        pass
    all_posts = news["posts"] + enforcement_posts
    seen: set[str] = set()
    deduped: List[dict] = []
    for p in all_posts:
        if p["external_id"] not in seen:
            seen.add(p["external_id"])
            deduped.append(p)
    deduped.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {"posts": deduped[:limit], "unique_fetched": len(deduped), "query_count": 2}


def crawl_fda_press(limit: int = 30) -> dict:
    """FDA approvals & press releases via Google News."""
    return crawl_google_news("FDA drug approval new medicine approved press release", limit=limit)


def crawl_fda_all(limit: int = 60) -> dict:
    """All regulatory news (FDA + EMA + WHO) via Google News — confirmed working."""
    posts: List[dict] = []
    seen: set[str] = set()
    per = max(5, limit // len(_REGULATORY_NEWS_QUERIES))
    queries_run: List[str] = []
    for spec in _REGULATORY_NEWS_QUERIES:
        queries_run.append(spec["query"])
        q = quote(spec["query"])
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        feed = _parse_rss_url(url)
        for entry in feed.entries[:per]:
            post = _news_entry_to_post(entry, query_key=spec["key"])
            if post["external_id"] not in seen:
                seen.add(post["external_id"])
                posts.append(post)
    # Also pull openFDA enforcement (direct API, confirmed working)
    try:
        import httpx
        r = httpx.get(
            "https://api.fda.gov/drug/enforcement.json",
            params={"search": "status:Ongoing", "limit": 10, "sort": "recall_initiation_date:desc"},
            headers={"User-Agent": _USER_AGENT}, timeout=10,
        )
        if r.status_code == 200:
            for rec in r.json().get("results", []):
                brand = rec.get("brand_name", "")
                product = rec.get("product_description", "")[:80]
                reason = rec.get("reason_for_recall", "")[:200]
                eid = f"fda_enforce_{rec.get('recall_number', _hash(reason))}"
                if eid in seen:
                    continue
                seen.add(eid)
                date_str = rec.get("recall_initiation_date", "")
                posted = datetime.utcnow()
                try:
                    posted = datetime.strptime(date_str, "%Y%m%d") if date_str else posted
                except ValueError:
                    pass
                posts.append({
                    "external_id": eid,
                    "platform": "fda_enforcement",
                    "url": "https://www.accessdata.fda.gov/scripts/enforcement/enforce_rpt-Product-Tabs.cfm",
                    "author": _hash("fda_enforcement"),
                    "title": f"FDA Recall: {brand or product[:60]}",
                    "body": f"FDA drug recall: {brand or product}. Reason: {reason}.",
                    "region": "North America", "country": "US",
                    "posted_at": posted,
                })
    except Exception:
        pass

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "feeds_run": queries_run,
        "feed_count": len(_REGULATORY_NEWS_QUERIES),
        "unique_fetched": len(posts),
    }


def crawl_reddit_pullpush(query: str, limit: int = 50) -> dict:
    """Search Reddit via Pullpush.io (Reddit archive API) — works when reddit.com is blocked.

    Pullpush mirrors Reddit submissions. Returns recent posts across all curated
    health subreddits without hitting reddit.com directly.
    Returns ``{posts, unique_fetched, subs_queried}``.
    """
    import httpx

    posts: List[dict] = []
    seen: set[str] = set()
    subs_queried: List[str] = []
    per = max(2, limit // len(_HEALTH_SUBS))

    for spec in _HEALTH_SUBS:
        sub = spec["sub"]
        subs_queried.append(sub)
        try:
            r = httpx.get(
                "https://api.pullpush.io/reddit/search/submission/",
                params={"subreddit": sub, "q": query, "size": per, "sort": "desc",
                        "sort_type": "created_utc"},
                headers={"User-Agent": _USER_AGENT},
                timeout=8.0,
            )
            if r.status_code != 200:
                continue
            for item in r.json().get("data", []):
                pid = str(item.get("id", ""))
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                title = _strip_html(item.get("title", ""))
                body = _strip_html(item.get("selftext", "") or item.get("url", ""))
                created = item.get("created_utc", 0)
                posted = datetime.utcfromtimestamp(float(created)) if created else datetime.utcnow()
                posts.append({
                    "external_id": f"reddit_pp_{pid}",
                    "platform": f"reddit/{sub}",
                    "url": f"https://www.reddit.com{item.get('permalink', '')}",
                    "author": _hash(str(item.get("author", "anon"))),
                    "title": title[:500],
                    "body": f"{title}. {body}"[:4000] if body and body != title else title,
                    "region": "Global",
                    "posted_at": posted,
                    "subreddit": sub,
                    "source_label": f"r/{sub}",
                })
        except Exception:
            continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "subs_queried": subs_queried,
        "subreddit_count": len(subs_queried),
        "method": "pullpush",
    }


def crawl_twitter(query: str, limit: int = 25) -> List[dict]:
    """TwitterAPI.io advanced search — only if key configured; else empty."""
    if not settings.twitter_api_key:
        return []
    posts: List[dict] = []
    try:
        import httpx

        resp = httpx.get(
            "https://api.twitterapi.io/twitter/tweet/advanced_search",
            params={"query": query, "queryType": "Latest"},
            headers={"X-API-Key": settings.twitter_api_key},
            timeout=8.0,
        )
        for t in resp.json().get("tweets", [])[:limit]:
            posts.append({
                "external_id": t.get("id"),
                "platform": "twitter",
                "url": t.get("url", ""),
                "author": _hash(str(t.get("author", {}).get("id", "anon"))),
                "title": "",
                "body": t.get("text", ""),
                "posted_at": datetime.utcnow(),
            })
    except Exception:
        return []
    return posts


# --------------------------------------------------------------------------- #
# MHRA device alerts — UK Field Safety Notices + Device Safety Information
# --------------------------------------------------------------------------- #
_MHRA_FEEDS = [
    {"key": "mhra_devices", "url": "https://www.gov.uk/drug-device-alerts.atom",
     "label": "MHRA device alerts & FSNs"},
    {"key": "mhra_drug_safety", "url": "https://www.gov.uk/drug-safety-update.atom",
     "label": "MHRA drug safety updates"},
]


def crawl_mhra_devices(limit: int = 40) -> dict:
    """UK MHRA device alerts + FSNs from gov.uk Atom feed (no key).

    Pulls Field Safety Notices, Device Safety Information, and monthly safety
    roundups. Posts tagged product_type=device when alert mentions a device.
    Returns {posts, unique_fetched, feeds_run}.
    """
    posts: List[dict] = []
    seen: set[str] = set()
    per = max(10, limit // len(_MHRA_FEEDS))

    for spec in _MHRA_FEEDS:
        feed = _parse_rss_url(spec["url"])
        for entry in feed.entries[:per]:
            link = getattr(entry, "link", "") or ""
            eid = getattr(entry, "id", link) or link
            if not eid or eid in seen:
                continue
            seen.add(eid)
            title = _strip_html(getattr(entry, "title", "") or "")
            summary = _strip_html(getattr(entry, "summary", "") or "")
            body = f"{title}. {summary}" if summary and summary != title else title
            posted = datetime.utcnow()
            if getattr(entry, "published_parsed", None):
                posted = datetime(*entry.published_parsed[:6])
            body_lower = body.lower()
            is_device = any(k in body_lower for k in (
                "field safety notice", "fsn", "device safety", "medical device",
                "implant", "ventilator", "pump", "stent", "pacemaker", "catheter",
                "infusion", "defibrillator", "imaging", "ultrasound", "endoscope",
                "cgm", "glucose monitor", "glucometer", "cpap", "iud", "mesh",
                "hip replacement", "knee replacement", "breast implant", "dialysis",
            ))
            # Prefer device when the feed is the device-alerts Atom (not drug safety update)
            if spec["key"] == "mhra_devices":
                is_device = True
            posts.append({
                "external_id": f"mhra_{_hash(eid)}",
                "platform": "mhra_devices",
                "url": link,
                "author": _hash("mhra_gov_uk"),
                "title": title[:500],
                "body": (
                    f"{body}. Medical device field safety notice — device malfunction "
                    f"or adverse event requiring corrective action."
                    if is_device else body
                )[:4000],
                "region": "Europe",
                "country": "United Kingdom",
                "posted_at": posted,
                "product_type": "device" if is_device else "drug",
            })

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "feeds_run": [s["key"] for s in _MHRA_FEEDS],
    }


# --------------------------------------------------------------------------- #
# FDA MAUDE live ingest — device MDRs as pipeline posts
# --------------------------------------------------------------------------- #
def crawl_maude_live(limit: int = 30, days_back: int = 60) -> dict:
    """Pull recent MDRs from MAUDE via openFDA — device product_type posts.

    Returns {posts, unique_fetched}.
    """
    import httpx
    from datetime import timedelta

    posts: List[dict] = []
    seen: set[str] = set()
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)

    date_range = f"[{start:%Y%m%d}+TO+{end:%Y%m%d}]"
    queries = [
        f"event_type:malfunction+AND+date_received:{date_range}",
        f"event_type:injury+AND+date_received:{date_range}",
    ]

    for q in queries:
        try:
            url = (f"https://api.fda.gov/device/event.json"
                   f"?search={q}&limit={limit // 2}&sort=date_received:desc")
            r = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=12)
            if r.status_code != 200:
                continue
            for ev in r.json().get("results", []):
                report_id = (ev.get("report_number") or
                             ev.get("mdr_report_key", ""))
                if not report_id or report_id in seen:
                    continue
                seen.add(report_id)
                devices = ev.get("device", []) or []
                texts = ev.get("mdr_text", []) or []
                brand = ""
                generic = ""
                for d in devices:
                    brand = brand or (d.get("brand_name") or "").strip()
                    generic = generic or (d.get("generic_name") or "").strip()
                    openfda = d.get("openfda") or {}
                    if not generic:
                        names = openfda.get("device_name") or []
                        if names:
                            generic = names[0]
                dev_name = brand or generic or "Unknown device"
                # Prefer longer narrative fields; fall back to any MDR text.
                narratives = [
                    t.get("text", "") for t in texts
                    if t.get("text_type_code") in ("2500", "1000", "3000") and t.get("text")
                ]
                if not narratives:
                    narratives = [t.get("text", "") for t in texts if t.get("text")]
                narrative = " ".join(narratives)[:800]
                event_type = (ev.get("event_type") or "malfunction").strip().lower()
                date_str = ev.get("date_received", "")
                country = ev.get("manufacturer_g1_country", "")
                posted = datetime.utcnow()
                if date_str and len(date_str) == 8:
                    try:
                        posted = datetime.strptime(date_str, "%Y%m%d")
                    except ValueError:
                        pass
                # Enrich so 4-gate AE can fire: explicit product + failure + adverse cue.
                # Brand/model strings (MINIMED 780G, GUARDIAN4) map via device brand lexicon.
                failure_cue = {
                    "malfunction": "device malfunction and failure to operate",
                    "injury": "patient injury adverse event from device malfunction",
                    "death": "patient death adverse event associated with device failure",
                }.get(event_type, "device malfunction adverse event")
                alias = f"{brand} {generic}".strip()
                body = (
                    f"FDA MAUDE adverse device report. Device product: {dev_name}. "
                    f"{('Also known as: ' + alias + '. ') if alias and alias != dev_name else ''}"
                    f"Reported event: {event_type} — {failure_cue}. "
                    f"This was a serious negative patient experience. {narrative}"
                ).strip()
                posts.append({
                    "external_id": f"maude_{report_id}",
                    "platform": "maude_live",
                    "url": (f"https://www.accessdata.fda.gov/scripts/cdrh/"
                            f"cfdocs/cfmaude/detail.cfm?mdrfoi__id={report_id}"),
                    "author": _hash("fda_maude"),
                    "title": f"MAUDE: {(dev_name or 'Device')[:60]} - {event_type}",
                    "body": body[:4000],
                    "region": _country_to_region(country),
                    "country": country or None,
                    "posted_at": posted,
                    "product_type": "device",
                })
        except Exception:
            continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {"posts": posts[:limit], "unique_fetched": len(posts)}


# --------------------------------------------------------------------------- #
# Device safety news + FDA device recalls (free, no key)
# --------------------------------------------------------------------------- #
_DEVICE_NEWS_QUERIES = [
    q for q in _GOOGLE_NEWS_QUERIES if q["key"].startswith("device_")
] + [
    {"key": "device_implant", "query": "hip implant recall OR knee implant failure OR surgical mesh",
     "focus": "Orthopedic / mesh device safety"},
    {"key": "device_cardiac", "query": "pacemaker recall OR ICD malfunction OR defibrillator advisory",
     "focus": "Cardiac rhythm device safety"},
]


def crawl_device_news(limit: int = 40) -> dict:
    """Google News RSS focused on medical-device safety (no key).

    Posts are tagged product_type=device and lightly enriched so AE gates can fire.
    """
    posts: List[dict] = []
    seen: set[str] = set()
    per = max(5, limit // max(1, len(_DEVICE_NEWS_QUERIES)))
    for spec in _DEVICE_NEWS_QUERIES:
        try:
            q = quote(spec["query"])
            url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            feed = _parse_rss_url(url)
            for entry in feed.entries[:per]:
                post = _news_entry_to_post(entry, query_key=spec["key"])
                eid = post["external_id"]
                if not eid or eid in seen:
                    continue
                seen.add(eid)
                post["product_type"] = "device"
                post["platform"] = "device_news"
                # Adverse cue so dry headlines still pass Gate 3 when a device is named.
                post["body"] = (
                    f"{post.get('body') or ''}. Medical device adverse event / "
                    f"malfunction or safety recall report."
                )[:4000]
                posts.append(post)
        except Exception:
            continue
    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "queries_run": [q["key"] for q in _DEVICE_NEWS_QUERIES],
    }


def crawl_device_recalls(limit: int = 30) -> dict:
    """FDA device recalls via openFDA device/enforcement + device-news fallback."""
    import httpx

    posts: List[dict] = []
    seen: set[str] = set()
    try:
        r = httpx.get(
            "https://api.fda.gov/device/enforcement.json",
            params={
                "search": "status:Ongoing",
                "limit": limit,
                "sort": "recall_initiation_date:desc",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=12,
        )
        if r.status_code == 200:
            for rec in r.json().get("results", []):
                product = (rec.get("product_description") or "")[:120]
                reason = (rec.get("reason_for_recall") or "")[:300]
                firm = rec.get("recalling_firm") or ""
                classification = rec.get("classification") or ""
                date_str = rec.get("recall_initiation_date") or ""
                rid = rec.get("recall_number") or rec.get("event_id") or product
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                posted = datetime.utcnow()
                try:
                    posted = datetime.strptime(date_str, "%Y%m%d") if date_str else posted
                except ValueError:
                    pass
                body = (
                    f"FDA medical device recall ({classification}): {product}. "
                    f"Reason: {reason}. Firm: {firm}. "
                    f"This is a serious adverse device safety action involving "
                    f"device malfunction or patient injury risk."
                )
                posts.append({
                    "external_id": f"dev_recall_{_hash(str(rid))}",
                    "platform": "device_recalls",
                    "url": "https://www.fda.gov/medical-devices/medical-device-safety",
                    "author": _hash("fda_device_enforcement"),
                    "title": f"Device recall: {product[:80]}",
                    "body": body[:4000],
                    "region": "North America",
                    "country": "United States",
                    "posted_at": posted,
                    "product_type": "device",
                })
    except Exception:
        pass

    if len(posts) < limit // 2:
        news = crawl_device_news(limit=limit - len(posts))
        for p in news.get("posts", []):
            eid = p.get("external_id")
            if eid and eid not in seen:
                seen.add(eid)
                p["platform"] = "device_recalls"
                posts.append(p)

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {"posts": posts[:limit], "unique_fetched": len(posts)}


# --------------------------------------------------------------------------- #
# EUDAMED public API — EU device registry lookup (no key)
# --------------------------------------------------------------------------- #
def query_eudamed(device_name: str, timeout: float = 8.0) -> dict:
    """Lookup a device in EUDAMED public API (no key, no registration).

    Returns {available, basic_udi, primary_di, device_name, manufacturer,
             risk_class, gmdn_code, gmdn_term, country}.
    """
    import httpx

    name = (device_name or "").strip()
    if not name:
        return {"available": False}
    try:
        r = httpx.get(
            "https://ec.europa.eu/tools/eudamed/api/devices/udiDiData",
            params={"query": name, "page": 0, "pageSize": 3,
                    "languageIso2Code": "en"},
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        if r.status_code != 200:
            return {"available": False, "source": "eudamed"}
        items = r.json().get("content", [])
        if not items:
            return {"available": False, "source": "eudamed"}
        d = items[0]
        mfr = d.get("manufacturer") or {}
        mfr_names = mfr.get("names") or []
        mfr_name = (mfr.get("name") or
                    (mfr_names[0].get("name") if mfr_names else ""))
        # risk class comes as {code: "refdata.risk-class.class-iia"} → extract "IIa"
        raw_class = d.get("riskClass") or {}
        code_str = raw_class.get("code", "") if isinstance(raw_class, dict) else str(raw_class)
        risk_class = code_str.split("class-")[-1].upper() if "class-" in code_str else code_str

        # GMDN may be nested in a list
        gmdn_list = d.get("gmdnTerms") or []
        gmdn_term = d.get("gmdnPtDefinition") or (gmdn_list[0].get("definition") if gmdn_list else None)
        gmdn_code = d.get("gmdnPtCode") or (gmdn_list[0].get("code") if gmdn_list else None)

        return {
            "available": True,
            "source": "eudamed",
            "basic_udi": d.get("basicUdi"),
            "primary_di": d.get("primaryDi"),
            "device_name": d.get("deviceName") or d.get("tradeName"),
            "manufacturer": mfr_name,
            "risk_class": risk_class or None,
            "gmdn_code": gmdn_code,
            "gmdn_term": gmdn_term,
            "country": (mfr.get("country") or {}).get("name"),
        }
    except Exception:
        return {"available": False, "source": "eudamed"}


# --------------------------------------------------------------------------- #
# HackerNews — Algolia Search API (no key, no rate limit for moderate use)
# --------------------------------------------------------------------------- #
_HN_PV_QUERIES = [
    "drug side effect adverse reaction",
    "medication side effects",
    "vaccine adverse reaction",
    "FDA recall drug safety",
    "pharmacovigilance drug safety signal",
]


def crawl_hackernews(query: str | None = None, limit: int = 30) -> dict:
    """Search HackerNews via Algolia API (no key required).

    Returns posts/comments mentioning drug safety topics from HN's
    tech/science community — a distinct audience from Reddit/Twitter.
    Returns {posts, unique_fetched, queries_run}.
    """
    import httpx

    posts: List[dict] = []
    seen: set[str] = set()
    queries = [query] if query else _HN_PV_QUERIES
    per = max(3, limit // len(queries))

    for q in queries:
        for tag in ("story", "comment"):
            try:
                r = httpx.get(
                    "https://hn.algolia.com/api/v1/search",
                    params={"query": q, "tags": tag, "hitsPerPage": per},
                    headers={"User-Agent": _USER_AGENT},
                    timeout=10.0,
                )
                if r.status_code != 200:
                    continue
                for hit in r.json().get("hits", []):
                    oid = str(hit.get("objectID", ""))
                    if not oid or oid in seen:
                        continue
                    seen.add(oid)
                    title = _strip_html(
                        hit.get("title") or hit.get("story_title") or ""
                    )
                    body = _strip_html(
                        hit.get("comment_text") or hit.get("story_text") or ""
                    )
                    text = f"{title}. {body}".strip(". ") if body else title
                    if not text or len(text) < 15:
                        continue
                    created = hit.get("created_at_i", 0)
                    posted = (datetime.utcfromtimestamp(float(created))
                              if created else datetime.utcnow())
                    url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
                    posts.append({
                        "external_id": f"hn_{oid}",
                        "platform": "hackernews",
                        "url": url,
                        "author": _hash(str(hit.get("author", "anon"))),
                        "title": title[:500],
                        "body": text[:4000],
                        "region": "Global",
                        "posted_at": posted,
                    })
            except Exception:
                continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "queries_run": queries,
        "query_count": len(queries),
    }


# --------------------------------------------------------------------------- #
# Life-science news pack — curated public RSS feeds (no key)
# --------------------------------------------------------------------------- #
# Only outlets verified reachable from typical networks (no 403/404).
_LIFE_SCIENCE_FEEDS: List[dict] = [
    {"id": "sciencedaily", "name": "ScienceDaily Health & Medicine",
     "url": "https://www.sciencedaily.com/rss/health_medicine.xml",
     "focus": "Research news - drug trials, obesity, vaccines"},
    {"id": "stat", "name": "STAT News",
     "url": "https://www.statnews.com/feed/",
     "focus": "Pharma / biotech journalism"},
    {"id": "nature_medicine", "name": "Nature Medicine",
     "url": "https://www.nature.com/nm.rss",
     "focus": "High-prestige clinical & translational research"},
    {"id": "who", "name": "WHO News",
     "url": "https://www.who.int/rss-feeds/news-english.xml",
     "focus": "Global health alerts, diagnostics, outbreaks"},
    {"id": "npr_health", "name": "NPR Health",
     "url": "https://feeds.npr.org/1007/rss.xml",
     "focus": "Consumer health stories"},
    {"id": "medicalxpress", "name": "Medical Xpress",
     "url": "https://medicalxpress.com/rss-feed/",
     "focus": "Medicine research aggregations"},
    {"id": "fiercepharma", "name": "Fierce Pharma",
     "url": "https://www.fiercepharma.com/rss/xml",
     "focus": "FDA actions, pharma pipeline, commercial safety news"},
    {"id": "endpoints", "name": "Endpoints News",
     "url": "https://endpoints.news/feed/",
     "focus": "Biotech deal / pipeline / safety coverage"},
    {"id": "genengnews", "name": "GEN Genetic Engineering News",
     "url": "https://www.genengnews.com/feed/",
     "focus": "Biotech M&A, platforms, clinical programs"},
]


def life_science_feeds() -> List[dict]:
    """Return the curated life-science RSS panel (for UI / API discovery)."""
    return [{"id": f["id"], "name": f["name"], "focus": f["focus"], "url": f["url"]}
            for f in _LIFE_SCIENCE_FEEDS]


def crawl_life_science_news(feed_id: str | None = None, limit: int = 50) -> dict:
    """Fetch articles from curated life-science / pharma RSS outlets (no key).

    If ``feed_id`` is set, only that outlet is crawled; otherwise all feeds run
    and articles are deduped by URL/id. Returns
    ``{posts, feeds_run, feed_count, unique_fetched}``.
    """
    posts: List[dict] = []
    seen: set[str] = set()
    feeds_run: List[str] = []
    specs = (
        [f for f in _LIFE_SCIENCE_FEEDS if f["id"] == feed_id]
        if feed_id else list(_LIFE_SCIENCE_FEEDS)
    )
    if not specs:
        return {"posts": [], "feeds_run": [], "feed_count": 0, "unique_fetched": 0,
                "note": f"Unknown feed_id={feed_id!r}"}
    per = max(3, limit // len(specs))

    feed_errors: List[str] = []
    for spec in specs:
        feeds_run.append(spec["id"])
        try:
            feed = _parse_rss_url(spec["url"])
            for entry in feed.entries[:per]:
                try:
                    title = _strip_html(getattr(entry, "title", "") or "")
                    summary = _strip_html(getattr(entry, "summary", "") or "")
                    body = summary or title
                    if not title and not body:
                        continue
                    posted = datetime.utcnow()
                    if getattr(entry, "published_parsed", None):
                        posted = datetime(*entry.published_parsed[:6])
                    elif getattr(entry, "updated_parsed", None):
                        posted = datetime(*entry.updated_parsed[:6])
                    link = getattr(entry, "link", "") or ""
                    eid = getattr(entry, "id", None) or link or f"{spec['id']}_{_hash(title)}"
                    if not eid or eid in seen:
                        continue
                    seen.add(eid)
                    posts.append({
                        "external_id": f"ls_{spec['id']}_{_hash(eid)}",
                        "platform": "life_science",
                        "url": link,
                        "author": _hash(spec["name"]),
                        "title": title[:500],
                        "body": (f"{title}. {body}"[:4000]
                                 if title and body != title else body[:4000]),
                        "region": "Global",
                        "posted_at": posted,
                        "news_source": spec["name"],
                        "news_query": spec["id"],
                    })
                except Exception:
                    continue
        except Exception as exc:
            feed_errors.append(f"{spec['id']}: {exc}")

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    out = {
        "posts": posts[:limit],
        "feeds_run": feeds_run,
        "feed_count": len(feeds_run),
        "unique_fetched": len(posts),
    }
    if feed_errors:
        out["feed_errors"] = feed_errors
    return out


# --------------------------------------------------------------------------- #
# YouTube — YouTube Data API v3 (needs YOUTUBE_API_KEY)
# --------------------------------------------------------------------------- #
# Ingests more than comments: video title + description (+ tags/channel),
# then top-level comments. Captions/transcripts need OAuth (not API-key) so
# they are intentionally out of scope for the free-key path.
_YT_PV_QUERIES = [
    "ozempic side effects experience",
    "drug adverse reaction experience",
    "vaccine side effects reaction",
    "medication side effects review",
]


def _yt_parse_time(iso: str | None) -> datetime:
    posted = datetime.utcnow()
    if not iso:
        return posted
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return posted


def crawl_youtube(query: str | None = None, limit: int = 30,
                  include_videos: bool = True,
                  include_comments: bool = True) -> dict:
    """Fetch YouTube PV content: video metadata + comment threads.

    Requires YOUTUBE_API_KEY (free quota ~10k units/day).
    ``search`` is expensive (~100 units); ``videos`` + ``commentThreads`` are cheap.
    Returns {posts, unique_fetched, query_count, video_posts, comment_posts}.
    """
    import httpx

    yt_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not yt_key:
        return {"posts": [], "unique_fetched": 0, "query_count": 0,
                "video_posts": 0, "comment_posts": 0,
                "note": "Set YOUTUBE_API_KEY to enable YouTube ingestion"}

    posts: List[dict] = []
    seen: set[str] = set()
    queries = [query] if query else _YT_PV_QUERIES
    per = max(2, min(8, limit // max(len(queries), 1)))
    errors: List[str] = []
    n_videos = 0
    n_comments = 0

    for q in queries:
        try:
            # Step 1: search for videos (100 quota units)
            sr = httpx.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={"part": "snippet", "q": q, "type": "video",
                        "maxResults": min(per, 10), "key": yt_key,
                        "relevanceLanguage": "en", "safeSearch": "moderate",
                        "order": "relevance"},
                headers={"User-Agent": _USER_AGENT},
                timeout=12.0,
            )
            if sr.status_code != 200:
                try:
                    msg = sr.json().get("error", {}).get("message", sr.text[:200])
                except Exception:
                    msg = sr.text[:200]
                errors.append(f"search HTTP {sr.status_code}: {msg}")
                continue

            search_items = sr.json().get("items", [])
            video_ids = [i["id"]["videoId"] for i in search_items
                         if i.get("id", {}).get("videoId")]
            if not video_ids:
                continue

            # Step 2: enrich with videos.list (1 unit) — title, description, tags, stats
            meta_by_id: dict = {}
            try:
                vr = httpx.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"part": "snippet,statistics,contentDetails",
                            "id": ",".join(video_ids[:10]), "key": yt_key},
                    headers={"User-Agent": _USER_AGENT},
                    timeout=12.0,
                )
                if vr.status_code == 200:
                    for item in vr.json().get("items", []):
                        meta_by_id[item.get("id")] = item
                else:
                    try:
                        msg = vr.json().get("error", {}).get("message", vr.text[:160])
                    except Exception:
                        msg = vr.text[:160]
                    errors.append(f"videos HTTP {vr.status_code}: {msg}")
            except Exception as exc:
                errors.append(f"videos {type(exc).__name__}: {exc}")

            # Fallback meta from search snippets when videos.list fails
            for it in search_items:
                vid = (it.get("id") or {}).get("videoId")
                if vid and vid not in meta_by_id:
                    meta_by_id[vid] = {"id": vid, "snippet": it.get("snippet") or {}}

            for vid in video_ids[:5]:
                meta = meta_by_id.get(vid) or {}
                snip = meta.get("snippet") or {}
                stats = meta.get("statistics") or {}
                title = _strip_html(snip.get("title") or "")
                desc = _strip_html(snip.get("description") or "")
                channel = snip.get("channelTitle") or "youtube"
                tags = snip.get("tags") or []
                tag_bit = (", ".join(tags[:12]) if isinstance(tags, list) else "")
                views = stats.get("viewCount")
                likes = stats.get("likeCount")
                published = snip.get("publishedAt")

                if include_videos and (title or desc):
                    eid = f"yt_video_{vid}"
                    if eid not in seen:
                        seen.add(eid)
                        body_parts = [title]
                        if desc:
                            body_parts.append(desc[:2500])
                        if tag_bit:
                            body_parts.append(f"Tags: {tag_bit}")
                        meta_line = []
                        if views:
                            meta_line.append(f"{views} views")
                        if likes:
                            meta_line.append(f"{likes} likes")
                        if meta_line:
                            body_parts.append(" · ".join(meta_line))
                        body = ". ".join(p for p in body_parts if p)
                        posts.append({
                            "external_id": eid,
                            "platform": "youtube",
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "author": _hash(channel),
                            "title": title[:500],
                            "body": body[:4000],
                            "region": "Global",
                            "posted_at": _yt_parse_time(published),
                            "news_source": channel[:80],
                            "yt_kind": "video",
                        })
                        n_videos += 1

                if not include_comments:
                    continue

                # Step 3: top-level comments (1 unit each call)
                try:
                    cr = httpx.get(
                        "https://www.googleapis.com/youtube/v3/commentThreads",
                        params={"part": "snippet", "videoId": vid,
                                "maxResults": 8, "key": yt_key,
                                "order": "relevance", "textFormat": "plainText"},
                        headers={"User-Agent": _USER_AGENT},
                        timeout=12.0,
                    )
                    if cr.status_code != 200:
                        try:
                            msg = cr.json().get("error", {}).get("message", cr.text[:160])
                        except Exception:
                            msg = cr.text[:160]
                        # commentsDisabled is common — not fatal
                        if "commentsDisabled" not in msg and "disabled" not in msg.lower():
                            errors.append(f"comments HTTP {cr.status_code}: {msg}")
                        continue
                    for item in cr.json().get("items", []):
                        cid = item.get("id", "")
                        if not cid or cid in seen:
                            continue
                        seen.add(cid)
                        csnip = (item.get("snippet", {})
                                   .get("topLevelComment", {})
                                   .get("snippet", {}))
                        text = _strip_html(
                            csnip.get("textOriginal") or csnip.get("textDisplay") or ""
                        )
                        if not text or len(text) < 20:
                            continue
                        # Prefixed title so NLP sees the drug context from the video
                        ctitle = (f"Re: {title}" if title else "")[:500]
                        body = (f"{title}. {text}" if title and title.lower() not in text.lower()
                                else text)
                        posts.append({
                            "external_id": f"yt_{cid}",
                            "platform": "youtube",
                            "url": f"https://www.youtube.com/watch?v={vid}&lc={cid}",
                            "author": _hash(csnip.get("authorDisplayName") or "anon"),
                            "title": ctitle,
                            "body": body[:4000],
                            "region": "Global",
                            "posted_at": _yt_parse_time(csnip.get("publishedAt")),
                            "news_source": channel[:80],
                            "yt_kind": "comment",
                        })
                        n_comments += 1
                except Exception as exc:
                    errors.append(f"comments {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    note = None
    if not posts and errors:
        uniq = []
        for e in errors:
            if e not in uniq:
                uniq.append(e)
        joined = " | ".join(uniq[:2])
        hint = ""
        if "IP address restriction" in joined or "violates this restriction" in joined:
            hint = (
                " Fix: Google Cloud → Credentials → API key → Application restrictions: "
                "add your current public IP (IPv4 and IPv6 if shown), or set "
                "Application restrictions = None (keep API restriction = YouTube Data API v3)."
            )
        note = joined + hint
    elif posts:
        note = (f"Ingested {n_videos} video(s) + {n_comments} comment(s). "
                "Captions/transcripts require OAuth (not available with API key alone).")
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts),
        "query_count": len(queries),
        "video_posts": n_videos,
        "comment_posts": n_comments,
        "note": note,
        "errors": errors[:5] if errors else [],
    }
