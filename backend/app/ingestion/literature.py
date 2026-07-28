"""Medical abstract / literature ingest — PubMed, Europe PMC, Semantic Scholar, Cochrane.

All connectors are keyless with deterministic offline fixtures. Posts are tagged
``type=literature`` so they stay distinguishable from spontaneous ICSRs / social AE
narratives in the corpus.
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, List, Optional
from xml.sax.saxutils import unescape

import httpx

from ..config import settings

logger = logging.getLogger("vigilai.literature")

_USER_AGENT = "VigilAI/1.0 (pharmacovigilance; offline-first; mailto:admin@vigilai.dev)"

# MeSH-leaning PV queries (NCBI query syntax). Used when the caller omits ``query``.
_PV_MESH_QUERIES: List[str] = [
    (
        '("Drug-Related Side Effects and Adverse Reactions"[MeSH Terms] OR '
        '"adverse drug reaction"[tiab]) AND '
        '("Pharmacovigilance"[MeSH Terms] OR "Product Surveillance, Postmarketing"[MeSH Terms] '
        'OR disproportionality[tiab] OR "signal detection"[tiab])'
    ),
    (
        '("Vaccines"[MeSH Terms] OR vaccine[tiab]) AND '
        '("adverse effects"[Subheading] OR "adverse event"[tiab] OR myocarditis[tiab])'
    ),
    (
        '("Antineoplastic Agents"[MeSH Terms] OR immunotherapy[tiab] OR "immune checkpoint"[tiab]) '
        'AND ("adverse effects"[Subheading] OR colitis[tiab] OR pneumonitis[tiab])'
    ),
    (
        '("Equipment Failure"[MeSH Terms] OR "Device Failure"[tiab] OR "medical device"[tiab]) '
        'AND (malfunction[tiab] OR "adverse event"[tiab] OR recall[tiab])'
    ),
]

_PROJECT_QUERY_MAP: dict[str, List[str]] = {
    "oncology": [
        (
            '("Antineoplastic Agents"[MeSH] OR pembrolizumab[tiab] OR nivolumab[tiab] '
            'OR "immune checkpoint"[tiab]) AND '
            '("adverse effects"[Subheading] OR irAE[tiab] OR colitis[tiab] OR pneumonitis[tiab])'
        ),
        "immune-related adverse events checkpoint inhibitor pharmacovigilance",
    ],
    "vaccine": [
        (
            '("Vaccines"[MeSH] OR "COVID-19 Vaccines"[MeSH] OR "mRNA vaccine"[tiab]) AND '
            '("adverse effects"[Subheading] OR myocarditis[tiab] OR anaphylaxis[tiab])'
        ),
        "vaccine adverse event pharmacovigilance signal",
    ],
    "device": [
        (
            '("Equipment Failure"[MeSH] OR "Infusion Pumps"[MeSH] OR "Continuous Glucose Monitoring"[tiab]) '
            'AND (malfunction[tiab] OR injury[tiab] OR recall[tiab])'
        ),
        "medical device adverse event MAUDE malfunction",
    ],
}

_EPMC_OFFLINE = [
    {
        "id": "PMC0001",
        "pmid": "39000001",
        "title": "Disproportionality signals for immune-related colitis with PD-1 inhibitors",
        "abstract": (
            "Europe PMC surrogate abstract: pembrolizumab and nivolumab showed elevated "
            "reporting of colitis and diarrhoea in spontaneous reports; dechallenge was "
            "supportive in a subset of cases."
        ),
        "journal": "Drug Safety (surrogate)",
        "year": "2024",
    },
    {
        "id": "PMC0002",
        "pmid": "39000002",
        "title": "Statin-associated muscle symptoms: literature and FAERS concordance",
        "abstract": (
            "Europe PMC surrogate: myalgia and rhabdomyolysis with high-intensity "
            "atorvastatin and simvastatin; temporal association and positive dechallenge noted."
        ),
        "journal": "Pharmacoepidemiol (surrogate)",
        "year": "2023",
    },
]

_S2_OFFLINE = [
    {
        "paperId": "s2off001",
        "title": "Bayesian disproportionality methods for sparse adverse event data",
        "abstract": (
            "Semantic Scholar surrogate: EBGM and BCPNN shrinkage reduce small-N inflation "
            "versus crude PRR when screening drug–event pairs from social and spontaneous data."
        ),
        "year": 2022,
        "url": "https://www.semanticscholar.org/",
    },
    {
        "paperId": "s2off002",
        "title": "mRNA vaccine myocarditis: clinical course and causality assessment",
        "abstract": (
            "Semantic Scholar surrogate: temporal association of myocarditis after mRNA "
            "COVID-19 vaccination in young males; most cases mild with recovery after dechallenge."
        ),
        "year": 2023,
        "url": "https://www.semanticscholar.org/",
    },
]

_COCHRANE_OFFLINE = [
    {
        "id": "CN-00000001",
        "title": "Statins for primary prevention — adverse event appendix",
        "abstract": (
            "CENTRAL surrogate: myalgia and elevated CK reported more frequently with "
            "high-intensity statin arms versus placebo in randomised trials."
        ),
    },
    {
        "id": "CN-00000002",
        "title": "Immune checkpoint inhibitors — AESI clusters in oncology trials",
        "abstract": (
            "CENTRAL surrogate: colitis, pneumonitis, and hypothyroidism as AESI clusters "
            "in PD-1/PD-L1 inhibitor randomised and non-randomised records."
        ),
    },
    {
        "id": "CN-00000003",
        "title": "Influenza vaccines — reactogenicity systematic records",
        "abstract": (
            "CENTRAL surrogate: injection-site reactions and transient fever common; "
            "serious allergic events rare across influenza vaccine trial register entries."
        ),
    },
]


def _hash(s: str) -> str:
    return hashlib.sha256((s or "anon").encode()).hexdigest()[:12]


def _strip_html(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    t = unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _ncbi_params(extra: dict) -> dict:
    out = dict(extra)
    if settings.ncbi_api_key:
        out["api_key"] = settings.ncbi_api_key
    return out


def _mindate_str(days_back: int) -> str:
    """NCBI mindate as YYYY/MM/DD."""
    d = datetime.utcnow() - timedelta(days=max(30, int(days_back)))
    return d.strftime("%Y/%m/%d")


def _project_hint_from_context() -> tuple[Optional[str], List[str]]:
    """Best-effort active project name + keywords (request-scoped)."""
    try:
        from ..database import SessionLocal
        from ..projects.scope import current_project_id, project_keywords
        from ..models import Project

        pid = current_project_id()
        if pid is None:
            return None, []
        db = SessionLocal()
        try:
            row = db.query(Project).filter(Project.id == pid).first()
            if not row:
                return None, []
            return (row.name or "").strip() or None, project_keywords(row)
        finally:
            db.close()
    except Exception:
        return None, []


def resolve_literature_queries(
    query: Optional[str] = None,
    project_hint: Optional[str] = None,
    keywords: Optional[List[str]] = None,
) -> List[str]:
    """Build PubMed/Europe PMC query list: explicit → project → default MeSH pack."""
    if query and query.strip():
        return [query.strip()]

    hint = (project_hint or "").lower()
    if not hint:
        auto_name, auto_kws = _project_hint_from_context()
        hint = (auto_name or "").lower()
        if keywords is None:
            keywords = auto_kws

    for key, qs in _PROJECT_QUERY_MAP.items():
        if key in hint:
            out = list(qs)
            break
    else:
        out = list(_PV_MESH_QUERIES)

    kws = [k for k in (keywords or []) if k and len(k) >= 3][:4]
    if kws:
        # Narrow with project product keywords without dropping MeSH structure.
        joined = " OR ".join(f'"{k}"[tiab]' for k in kws)
        out = [f"({q}) AND ({joined})" for q in out[:2]] + out[2:3]

    return out


def _literature_post(
    *,
    external_id: str,
    platform: str,
    title: str,
    abstract: str,
    url: str,
    authors: str = "",
    journal: str = "",
    published: Optional[datetime] = None,
    source_label: str,
    extra: Optional[dict] = None,
) -> dict[str, Any]:
    title_c = _strip_html(title)[:500]
    abs_c = _strip_html(abstract)[:3500]
    meta_bits = [b for b in (authors, journal) if b]
    meta = f" ({'; '.join(meta_bits)})" if meta_bits else ""
    if abs_c:
        body = f"{title_c}{meta}. Abstract: {abs_c}"
    else:
        body = f"{title_c}{meta}. Literature record (abstract unavailable)."
    post: dict[str, Any] = {
        "external_id": external_id,
        "platform": platform,
        "url": url,
        "author": _hash(authors or platform),
        "title": title_c or external_id,
        "body": body[:4000],
        "region": "Global",
        "language": "en",
        "posted_at": published or datetime.utcnow(),
        "source_label": source_label,
        "content_type": "literature",
    }
    if extra:
        post.update(extra)
    return post


def _parse_pubmed_xml(xml_text: str, platform: str = "pubmed_live") -> List[dict]:
    out: List[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for art in root.findall(".//PubmedArticle"):
        pmid = (art.findtext(".//PMID") or "").strip()
        title = (art.findtext(".//ArticleTitle") or "").strip()
        abstract_parts = []
        for n in art.findall(".//AbstractText"):
            label = n.attrib.get("Label") or n.attrib.get("NlmCategory") or ""
            chunk = "".join(n.itertext()).strip()
            if not chunk:
                continue
            abstract_parts.append(f"{label}: {chunk}" if label else chunk)
        abstract = " ".join(abstract_parts).strip()
        if not pmid or not (title or abstract):
            continue
        authors = []
        for au in art.findall(".//Author")[:3]:
            last = (au.findtext("LastName") or "").strip()
            init = (au.findtext("Initials") or "").strip()
            if last:
                authors.append(f"{last} {init}".strip())
        journal = (art.findtext(".//Journal/Title") or art.findtext(".//ISOAbbreviation") or "").strip()
        year = (art.findtext(".//PubDate/Year") or art.findtext(".//ArticleDate/Year") or "").strip()
        posted = datetime.utcnow()
        if year.isdigit():
            try:
                posted = datetime(int(year), 1, 1)
            except ValueError:
                pass
        out.append(
            _literature_post(
                external_id=f"pubmed_{pmid}",
                platform=platform,
                title=title,
                abstract=abstract,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                authors=", ".join(authors),
                journal=journal,
                published=posted,
                source_label="Literature · PubMed",
                extra={"pmid": pmid},
            )
        )
    return out


def crawl_pubmed_abstracts(
    query: str | None = None,
    limit: int = 20,
    days_back: int = 730,
    project_hint: str | None = None,
) -> dict:
    """Pull PubMed records with full abstracts via esearch + efetch (no key required)."""
    queries = resolve_literature_queries(query, project_hint=project_hint)
    posts: List[dict] = []
    seen: set[str] = set()
    per = max(3, limit // max(1, len(queries)))
    mindate = _mindate_str(days_back)
    base = (settings.pubmed_base_url or "https://eutils.ncbi.nlm.nih.gov/entrez/eutils").rstrip("/")

    with httpx.Client(timeout=18.0, headers={"User-Agent": _USER_AGENT}) as client:
        for q in queries:
            if len(posts) >= limit:
                break
            try:
                sr = client.get(
                    f"{base}/esearch.fcgi",
                    params=_ncbi_params({
                        "db": "pubmed",
                        "term": q,
                        "retmax": per,
                        "sort": "pub date",
                        "retmode": "json",
                        "datetype": "pdat",
                        "mindate": mindate,
                        "maxdate": datetime.utcnow().strftime("%Y/%m/%d"),
                    }),
                )
                if sr.status_code != 200:
                    continue
                ids = sr.json().get("esearchresult", {}).get("idlist", []) or []
                ids = [i for i in ids if i not in seen]
                if not ids:
                    continue
                fr = client.get(
                    f"{base}/efetch.fcgi",
                    params=_ncbi_params({
                        "db": "pubmed",
                        "id": ",".join(ids),
                        "retmode": "xml",
                    }),
                )
                if fr.status_code != 200 or not fr.text:
                    continue
                for post in _parse_pubmed_xml(fr.text, platform="pubmed_live"):
                    pmid = post.get("pmid") or post["external_id"]
                    if pmid in seen:
                        continue
                    seen.add(str(pmid))
                    posts.append(post)
                    if len(posts) >= limit:
                        break
            except Exception as exc:
                logger.debug("PubMed query failed (%s): %s", q[:60], exc)
                continue

    if not posts:
        posts = _pubmed_offline(limit)

    posts.sort(key=lambda p: p.get("posted_at") or datetime.min, reverse=True)
    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts[:limit]),
        "query_count": len(queries),
        "queries": queries,
        "days_back": days_back,
        "content_type": "literature",
    }


def _pubmed_offline(limit: int) -> List[dict]:
    rows = [
        {
            "pmid": "38990001",
            "title": "Pharmacovigilance signal detection using social media and spontaneous reports",
            "abstract": (
                "Offline PubMed surrogate: combined FAERS and patient-forum narratives "
                "identified strengthening signals for GLP-1 agonist gastrointestinal events "
                "with temporal association and partial dechallenge."
            ),
            "journal": "Drug Saf (offline)",
            "year": "2024",
        },
        {
            "pmid": "38990002",
            "title": "Device malfunction surveillance: infusion pumps and CGM",
            "abstract": (
                "Offline PubMed surrogate: insulin pump occlusion and CGM sensor failure "
                "clusters reported in MAUDE-linked literature; injury risk when therapy delayed."
            ),
            "journal": "Expert Rev Med Devices (offline)",
            "year": "2023",
        },
    ]
    out = []
    for r in rows[:limit]:
        out.append(
            _literature_post(
                external_id=f"pubmed_{r['pmid']}",
                platform="pubmed_live",
                title=r["title"],
                abstract=r["abstract"],
                url=f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/",
                journal=r["journal"],
                published=datetime(int(r["year"]), 1, 1),
                source_label="Literature · PubMed (offline)",
                extra={"pmid": r["pmid"]},
            )
        )
    return out


def crawl_europe_pmc(
    query: str | None = None,
    limit: int = 20,
    project_hint: str | None = None,
) -> dict:
    """Europe PMC REST search (abstracts) — no key; offline fixtures on failure."""
    queries = resolve_literature_queries(query, project_hint=project_hint)
    # Europe PMC prefers simpler Lucene-ish queries; strip heavy MeSH brackets when custom.
    q = queries[0]
    if "[MeSH" in q or "[tiab]" in q:
        # Use a readable free-text companion for EPMC alongside MeSH for PubMed.
        q = query.strip() if query and query.strip() else "pharmacovigilance OR \"adverse drug reaction\" OR \"drug safety\""
        hint = (project_hint or "").lower()
        if not hint:
            hint, _ = _project_hint_from_context()
            hint = (hint or "").lower()
        if "oncology" in hint:
            q = "immune-related adverse events OR checkpoint inhibitor colitis"
        elif "vaccine" in hint:
            q = "vaccine adverse event OR vaccine myocarditis"
        elif "device" in hint:
            q = "medical device malfunction OR infusion pump adverse"

    posts: List[dict] = []
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": _USER_AGENT}) as client:
            r = client.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={
                    "query": q,
                    "format": "json",
                    "pageSize": min(limit, 50),
                    "resultType": "core",
                    "sort": "P_PDATE_D desc",
                },
            )
            r.raise_for_status()
            results = (r.json().get("resultList") or {}).get("result") or []
            for item in results:
                pmid = str(item.get("pmid") or "").strip()
                pmcid = str(item.get("pmcid") or item.get("id") or "").strip()
                title = item.get("title") or ""
                abstract = item.get("abstractText") or ""
                if not (title or abstract):
                    continue
                journal = item.get("journalTitle") or item.get("bookOrReportDetails", {}).get("publisher") or ""
                if isinstance(journal, dict):
                    journal = ""
                year = str(item.get("pubYear") or "").strip()
                posted = datetime.utcnow()
                if year.isdigit():
                    try:
                        posted = datetime(int(year), 1, 1)
                    except ValueError:
                        pass
                authors = item.get("authorString") or ""
                url = ""
                if pmid:
                    url = f"https://europepmc.org/article/MED/{pmid}"
                elif pmcid:
                    url = f"https://europepmc.org/article/PMC/{pmcid.replace('PMC', '')}"
                else:
                    url = "https://europepmc.org/"
                ext = f"epmc_{pmid or pmcid or item.get('id')}"
                posts.append(
                    _literature_post(
                        external_id=ext,
                        platform="europe_pmc",
                        title=title,
                        abstract=abstract,
                        url=url,
                        authors=authors[:200],
                        journal=str(journal)[:200],
                        published=posted,
                        source_label="Literature · Europe PMC",
                        extra={"pmid": pmid or None},
                    )
                )
    except Exception as exc:
        logger.warning("Europe PMC fetch failed: %s", exc)

    if not posts:
        for row in _EPMC_OFFLINE[:limit]:
            posts.append(
                _literature_post(
                    external_id=f"epmc_{row['pmid']}",
                    platform="europe_pmc",
                    title=row["title"],
                    abstract=row["abstract"],
                    url=f"https://europepmc.org/article/MED/{row['pmid']}",
                    journal=row["journal"],
                    published=datetime(int(row["year"]), 1, 1),
                    source_label="Literature · Europe PMC (offline)",
                    extra={"pmid": row["pmid"]},
                )
            )

    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts[:limit]),
        "query": q,
        "content_type": "literature",
    }


def crawl_semantic_scholar(
    query: str | None = None,
    limit: int = 20,
    project_hint: str | None = None,
) -> dict:
    """Semantic Scholar Academic Graph paper search — no key (optional key raises limits)."""
    hint = (project_hint or "").lower()
    if not hint:
        hint_name, _ = _project_hint_from_context()
        hint = (hint_name or "").lower()

    if query and query.strip():
        q = query.strip()
    elif "oncology" in hint:
        q = "immune checkpoint inhibitor adverse events colitis pneumonitis"
    elif "vaccine" in hint:
        q = "vaccine adverse events myocarditis pharmacovigilance"
    elif "device" in hint:
        q = "medical device malfunction adverse event infusion pump"
    else:
        q = "pharmacovigilance adverse drug reaction signal detection"

    headers = {"User-Agent": _USER_AGENT}
    s2_key = getattr(settings, "semantic_scholar_api_key", "") or ""
    if s2_key:
        headers["x-api-key"] = s2_key

    posts: List[dict] = []
    try:
        with httpx.Client(timeout=15.0, headers=headers) as client:
            r = client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": q,
                    "limit": min(limit, 40),
                    "fields": "title,abstract,year,authors,url,externalIds,venue",
                },
            )
            if r.status_code == 200:
                data = r.json().get("data") or []
                for item in data:
                    title = item.get("title") or ""
                    abstract = item.get("abstract") or ""
                    if not (title or abstract):
                        continue
                    paper_id = item.get("paperId") or ""
                    authors = ", ".join(
                        (a.get("name") or "") for a in (item.get("authors") or [])[:3]
                    )
                    year = item.get("year")
                    posted = datetime.utcnow()
                    if isinstance(year, int) and 1900 < year < 2100:
                        posted = datetime(year, 1, 1)
                    ext_ids = item.get("externalIds") or {}
                    pmid = str(ext_ids.get("PubMed") or "").strip()
                    url = item.get("url") or (
                        f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else
                        "https://www.semanticscholar.org/"
                    )
                    posts.append(
                        _literature_post(
                            external_id=f"s2_{paper_id or pmid or _hash(title)}",
                            platform="semantic_scholar",
                            title=title,
                            abstract=abstract,
                            url=url,
                            authors=authors,
                            journal=item.get("venue") or "",
                            published=posted,
                            source_label="Literature · Semantic Scholar",
                            extra={"pmid": pmid or None, "s2_id": paper_id},
                        )
                    )
            else:
                logger.warning("Semantic Scholar HTTP %s", r.status_code)
    except Exception as exc:
        logger.warning("Semantic Scholar fetch failed: %s", exc)

    if not posts:
        for row in _S2_OFFLINE[:limit]:
            posts.append(
                _literature_post(
                    external_id=f"s2_{row['paperId']}",
                    platform="semantic_scholar",
                    title=row["title"],
                    abstract=row["abstract"],
                    url=row["url"],
                    published=datetime(int(row["year"]), 1, 1),
                    source_label="Literature · Semantic Scholar (offline)",
                    extra={"s2_id": row["paperId"]},
                )
            )

    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts[:limit]),
        "query": q,
        "content_type": "literature",
    }


def crawl_cochrane_central(
    query: str | None = None,
    limit: int = 20,
    project_hint: str | None = None,
) -> dict:
    """Cochrane CENTRAL abstracts via Europe PMC SRC:cctr, else offline fixtures."""
    hint = (project_hint or "").lower()
    if not hint:
        hint_name, _ = _project_hint_from_context()
        hint = (hint_name or "").lower()

    if query and query.strip():
        core = query.strip()
    elif "oncology" in hint:
        core = "checkpoint inhibitor OR immunotherapy adverse"
    elif "vaccine" in hint:
        core = "vaccine adverse OR influenza vaccine reactogenicity"
    else:
        core = "adverse event OR adverse effects OR safety"

    epmc_q = f"(SRC:cctr) AND ({core})"
    posts: List[dict] = []
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": _USER_AGENT}) as client:
            r = client.get(
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={
                    "query": epmc_q,
                    "format": "json",
                    "pageSize": min(limit, 40),
                    "resultType": "core",
                },
            )
            if r.status_code == 200:
                results = (r.json().get("resultList") or {}).get("result") or []
                for item in results:
                    title = item.get("title") or ""
                    abstract = item.get("abstractText") or ""
                    if not (title or abstract):
                        continue
                    cid = str(item.get("id") or item.get("pmcid") or item.get("pmid") or _hash(title))
                    posts.append(
                        _literature_post(
                            external_id=f"cochrane_{cid}",
                            platform="cochrane_central",
                            title=title,
                            abstract=abstract or title,
                            url=f"https://www.cochranelibrary.com/central",
                            journal="Cochrane CENTRAL",
                            source_label="Literature · Cochrane CENTRAL",
                        )
                    )
    except Exception as exc:
        logger.debug("Cochrane/EuropePMC probe failed: %s", exc)

    if not posts:
        qlow = (query or "").lower()
        rows = [
            r for r in _COCHRANE_OFFLINE
            if not qlow or qlow in r["title"].lower() or qlow in r["abstract"].lower()
        ] or _COCHRANE_OFFLINE
        for r in rows[:limit]:
            posts.append(
                _literature_post(
                    external_id=f"cochrane_{r['id']}",
                    platform="cochrane_central",
                    title=r["title"],
                    abstract=r["abstract"],
                    url=f"https://www.cochranelibrary.com/central/doi/{r['id']}",
                    journal="Cochrane CENTRAL",
                    source_label="Literature · Cochrane CENTRAL (offline)",
                )
            )

    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts[:limit]),
        "query": epmc_q,
        "content_type": "literature",
    }
