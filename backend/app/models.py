"""Database models for VigilAI.

Two-vault pattern (from SignalRx) + signal/analytics layer (from Algo-Pharma) +
knowledge-graph projection (new).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


# --------------------------------------------------------------------------- #
# Step 1 — Project-scoped workspace isolation
# --------------------------------------------------------------------------- #
class Project(Base):
    """Therapeutic surveillance workspace (oncology vs vaccine vs device, etc.)."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, index=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(Text)
    therapeutic_area = Column(String(64), index=True)  # oncology | vaccine | device | general
    keywords_json = Column(Text)  # JSON list of medical keywords for pathfinder
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    posts = relationship("RawPost", back_populates="project", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="project", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="project", cascade="all, delete-orphan")
    suggested_sources = relationship(
        "SuggestedSource", back_populates="project", cascade="all, delete-orphan"
    )
    pathfinder_runs = relationship(
        "PathfinderRun", back_populates="project", cascade="all, delete-orphan"
    )
    monitored_queries = relationship(
        "MonitoredQuery", back_populates="project", cascade="all, delete-orphan"
    )


class MonitoredQuery(Base):
    """Project-bound surveillance query parameters (feeds pathfinder + ingest)."""

    __tablename__ = "monitored_queries"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    query_text = Column(String(512), nullable=False)
    source_hint = Column(String(64))  # optional platform bias
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="monitored_queries")


class PathfinderRun(Base):
    """Audit log for autonomous discovery loops (Step 2)."""

    __tablename__ = "pathfinder_runs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status = Column(String(32), default="pending")  # pending|running|completed|failed
    provider = Column(String(32))  # exa|tavily|offline
    query_used = Column(Text)
    urls_discovered = Column(Integer, default=0)
    result_json = Column(Text)
    error = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)

    project = relationship("Project", back_populates="pathfinder_runs")


class SuggestedSource(Base):
    """Approval queue for discovered URLs (Step 3)."""

    __tablename__ = "suggested_sources"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    url = Column(String(1024), nullable=False, index=True)
    domain = Column(String(255), index=True)
    title = Column(String(512))
    access_status = Column(String(32), default="public", index=True)  # public | login_required
    access_flags_json = Column(Text)  # DOM friction tags detected
    approval_status = Column(String(32), default="pending", index=True)  # pending|approved|rejected|ingesting
    discovery_run_id = Column(Integer, ForeignKey("pathfinder_runs.id"), nullable=True)
    storage_profile = Column(String(128))  # playwright storage_state filename
    onboarded_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    project = relationship("Project", back_populates="suggested_sources")


class RawPost(Base):
    """Ingested, PII-scrubbed source text (the 'intake vault')."""

    __tablename__ = "raw_posts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True)
    external_id = Column(String(128), index=True)  # dedupe key
    platform = Column(String(64), index=True)       # reddit / twitter / forum / stream
    product_type = Column(String(16), default="drug", index=True)  # drug | device | combination
    url = Column(String(1024))
    author_hash = Column(String(64))                # pseudonymized
    title = Column(Text)
    body = Column(Text)                              # already PII-scrubbed (English)
    body_original = Column(Text)                      # pre-translation scrubbed text
    lang = Column(String(16), default="en")          # detected source language
    lang_name = Column(String(32), default="English")
    translated = Column(Boolean, default=False)
    region = Column(String(32), index=True, default="Global")  # continent/region
    country = Column(String(48), index=True)          # ISO country name
    pii_found = Column(Text)                          # JSON list of redacted PII types
    posted_at = Column(DateTime, index=True)
    ingested_at = Column(DateTime, default=datetime.utcnow, index=True)
    processed = Column(Boolean, default=False, index=True)
    # Semantic narrative fingerprint (normalized title+body SHA-256) for cross-platform dedupe
    content_hash = Column(String(64), index=True)
    # Syndicated copies suppressed after this master was committed
    duplicate_count = Column(Integer, default=0)

    processed_post = relationship(
        "ProcessedPost", back_populates="raw", uselist=False, cascade="all, delete-orphan"
    )
    project = relationship("Project", back_populates="posts")


class ProcessedPost(Base):
    """NLP output for a raw post (the 'intelligence vault')."""

    __tablename__ = "processed_posts"

    id = Column(Integer, primary_key=True)
    raw_id = Column(Integer, ForeignKey("raw_posts.id"), index=True)

    entities_json = Column(Text)        # {"drugs":[...],"symptoms":[...],"conditions":[...]}
    sentiment_label = Column(String(16))
    sentiment_score = Column(Float)
    negation_json = Column(Text)        # {symptom: is_negated}

    ae_flag = Column(Boolean, default=False, index=True)
    ae_confidence = Column(Float, default=0.0)
    ae_reason = Column(Text)            # human-readable gate trace
    gate_trace_json = Column(Text)      # structured per-gate pass/fail

    created_at = Column(DateTime, default=datetime.utcnow)

    raw = relationship("RawPost", back_populates="processed_post")


class Signal(Base):
    """Aggregated drug-symptom safety signal with statistics + evidence."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True)
    drug = Column(String(128), index=True)           # product (drug OR device) name
    symptom = Column(String(128), index=True)         # event OR device failure mode

    # product classification (worldwide, drugs + devices)
    product_type = Column(String(16), default="drug", index=True)  # drug|device|combination
    device_gmdn = Column(String(128))                 # GMDN / FDA product-code surrogate
    imdrf_code = Column(String(32))                   # IMDRF adverse-event code (devices)
    imdrf_term = Column(String(128))                  # IMDRF human-readable term (devices)

    # worldwide standardization
    drug_atc = Column(String(16))                    # WHO ATC class (drugs)
    meddra_pt = Column(String(128))                  # MedDRA-style Preferred Term
    meddra_soc = Column(String(96))                  # System Organ Class
    meddra_soc_code = Column(String(16))
    regions_json = Column(Text)                       # {region: count} spread

    post_count = Column(Integer, default=0)
    expected = Column(Float, default=0.0)             # expected count under independence
    prr = Column(Float)                  # proportional reporting ratio
    prr_ci_low = Column(Float)
    prr_ci_high = Column(Float)
    ror = Column(Float)                  # reporting odds ratio
    ror_ci_low = Column(Float)
    ror_ci_high = Column(Float)
    chi_square = Column(Float)
    ic = Column(Float)                   # BCPNN Information Component
    ic025 = Column(Float)                # IC 2.5% lower bound (UMC threshold: > 0)
    ebgm = Column(Float)                 # MGPS Empirical Bayes Geometric Mean
    eb05 = Column(Float)                 # EBGM 5% lower bound (FDA threshold: >= 2)
    strength = Column(String(16))        # STRONG / MODERATE / WEAK
    sdr_flag = Column(Boolean, default=False, index=True)  # signal of disproportionate reporting

    # trend / spike (new)
    trend_score = Column(Float, default=0.0)     # EWMA slope
    spike_flag = Column(Boolean, default=False)
    spike_z = Column(Float, default=0.0)

    # causality + evidence (from SignalRx)
    who_umc = Column(String(32))         # Certain/Probable/Possible/Unlikely
    who_umc_score = Column(Float, default=0.0)
    who_umc_factors_json = Column(Text)  # JSON list of causality factors
    severity = Column(String(16))        # Critical/High/Medium/Low
    fda_evidence_json = Column(Text)     # openFDA FAERS/MAUDE corroboration

    # additional keyless evidence connectors (all with offline fallback)
    label_evidence_json = Column(Text)   # DailyMed SPL label match
    recall_json = Column(Text)           # openFDA recall / enforcement history
    literature_json = Column(Text)       # PubMed literature (count + top article)
    device_class_json = Column(Text)     # real openFDA device classification

    # pharmacogenomic (PGx) risk overlay (CPIC/PharmGKB surrogate)
    pgx_actionable = Column(Boolean, default=False, index=True)
    pgx_json = Column(Text)              # {gene, allele, phenotype, recommendation, ...}

    # Standardised MedDRA Query (SMQ) syndrome membership (open surrogate)
    smq_json = Column(Text)              # JSON list of {smq, name, scope, soc}

    # FDA boxed (black-box) warning overlay (curated offline surrogate)
    boxed_warning = Column(Boolean, default=False, index=True)  # drug carries a boxed warning
    boxed_json = Column(Text)            # {has_boxed, covers_event, topics, novelty, ...}

    # Mechanistic plausibility (Bradford Hill biological plausibility; MoA -> AE KB)
    mechanism_plausible = Column(Boolean, default=False, index=True)
    mechanism_json = Column(Text)        # {plausible, target_or_moa, mechanism_explanation, ...}

    # Class effect (ATC roll-up) + chemical read-across (structural analogs)
    class_effect = Column(Boolean, default=False, index=True)  # 2+ class members report this event
    class_json = Column(Text)            # class-level summary {class_name, member_drugs, eb05, ...}
    read_across_json = Column(Text)      # [{analog, similarity, analog_has_same_event}]

    # Active-comparator (same-class) disproportionality — contrasts the drug against the
    # OTHER drugs in its ATC class (shared indication) to reduce confounding-by-indication
    stands_out_in_class = Column(Boolean, default=False, index=True)  # AC ROR CI-low > 1
    active_comparator_json = Column(Text)  # {comparator_class, n_comparator_drugs, ac_ror, ac_ror_ci, ac_prr, stands_out_in_class, note}

    # Vaccine pharmacovigilance overlay (AESI / Brighton level / SCRI surrogate)
    is_vaccine = Column(Boolean, default=False, index=True)  # product is a known vaccine
    aesi = Column(String(96))            # matched Adverse Event of Special Interest name
    vaccine_json = Column(Text)          # {vaccine_name, platform, aesi_name, brighton_level, scri}

    # Spatial (geographic) cluster detection — Kulldorff-style Poisson scan statistic
    spatial_cluster = Column(Boolean, default=False, index=True)  # geographically concentrated
    spatial_json = Column(Text)          # {hotspot, level, observed, expected, rr, llr, by_area, region}

    # Empirical calibration (Schuemie negative-control null) + E-values (VanderWeele)
    calibrated_p = Column(Float)         # p-value calibrated against the empirical null
    calibrated_signal = Column(Boolean, default=False, index=True)  # survives calibration (cal p<0.05)
    e_value = Column(Float)              # confounding needed to explain the point estimate
    e_value_ci = Column(Float)           # E-value for the CI bound nearest the null
    calibration_json = Column(Text)      # {calibrated, null_mu, null_sigma, n_controls, calibrated_ci}

    # Quantitative benefit–risk (BRAT/MCDA + NNT vs NNH) — illustrative surrogate
    br_verdict = Column(String(16), index=True)        # Favourable | Uncertain | Unfavourable
    benefit_risk_json = Column(Text)     # {indication, nnt, benefit_outcome, nnh, harm_outcome, ...}

    # Cox PH time-to-event surrogate (social-listening hazard ratio)
    hr = Column(Float)                   # hazard ratio (exp(β̂)) — illustrative surrogate
    hr_ci_json = Column(Text)            # JSON [lo, hi] — 95% CI
    hr_p = Column(Float)                 # Wald p-value
    hr_elevated = Column(Boolean, default=False, index=True)  # CI lower bound > 1
    hr_json = Column(Text)               # full Cox result incl. method note

    # UMC vigiGrade-style report completeness (documentation-quality surrogate)
    completeness = Column(Float, default=0.0)          # mean completeness over supporting posts [0,1]
    well_documented = Column(Boolean, default=False, index=True)  # mean completeness >= threshold
    completeness_json = Column(Text)     # {mean, grade, n_posts, best, worst, dimension_coverage}

    # MaxSPRT — Maximized Sequential Probability Ratio Test (Kulldorff 2011)
    # Sequential surveillance statistic that controls type-I error over repeated looks.
    maxsprt_llr = Column(Float)                       # running maximum LLR at latest recompute
    maxsprt_crossed = Column(Boolean, default=False, index=True)  # boundary exceeded → flag
    maxsprt_json = Column(Text)          # full MaxSPRT result: {n_looks, llr_series, cv, ...}

    # LLM / explainability
    narrative = Column(Text)             # plain-English signal summary
    narrative_source = Column(String(16), default="deterministic")  # llm|deterministic

    # LLM Safety-Scientist Copilot (RAG-based structured assessment memo)
    copilot_json = Column(Text)          # structured assessment JSON (8 sections)
    copilot_source = Column(String(16))  # llm|deterministic

    supporting_post_ids = Column(Text)   # JSON list of processed_post ids
    earliest_post_at = Column(DateTime)  # first supporting post -> time-to-detection
    detected_at = Column(DateTime, default=datetime.utcnow)  # when signal first surfaced

    # Sybil-defense trust score (PulseAI-inspired)
    # Derived from author entropy × temporal spread × text diversity of supporting posts.
    # 1.0 = maximally trustworthy diverse cohort; 0.0 = sybil/coordinated burst.
    trust_score = Column(Float, default=1.0)
    trust_label = Column(String(16), default="high")  # high|medium|low|sybil

    # Deprecated — Federated/DP UI removed; column retained for schema compatibility
    federated_json = Column(Text)

    # Labeling-gap detection (DailyMed adverse-reaction text vs detected event)
    label_novelty = Column(String(16), index=True)   # novel | in_label | boxed | unknown
    label_gap_json = Column(Text)                    # {novelty_tier, label_match, label_section, confidence, note}

    # HCP review / feedback loop (feeds KPIs: actionable rate, false-positive ratio)
    review_state = Column(String(16), default="unreviewed", index=True)  # unreviewed|confirmed|dismissed
    reviewed_by = Column(String(255))
    reviewed_at = Column(DateTime)

    # GVP Module IX signal lifecycle management
    lifecycle_status = Column(String(32), default="new", index=True)  # new|under_evaluation|validated|prioritized|assessed|closed|rejected
    priority_score = Column(Float, default=0.0)                        # composite 0-100 score
    lifecycle_owner = Column(String(255))                              # assigned pharmacovigilance scientist
    lifecycle_notes = Column(Text)                                     # assessment notes / justification
    lifecycle_updated_at = Column(DateTime)                            # last lifecycle state change

    first_seen = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="signals")


class Alert(Base):
    """Emitted when a signal crosses severity/confidence thresholds."""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), index=True)
    drug = Column(String(128))
    symptom = Column(String(128))
    severity = Column(String(16))
    message = Column(Text)
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    project = relationship("Project", back_populates="alerts")


class User(Base):
    """Application user with a role (admin / analyst / viewer)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True)
    full_name = Column(String(128))
    hashed_password = Column(String(255))
    role = Column(String(16), default="analyst")   # admin | analyst | viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)


class AuditLog(Base):
    """Append-only audit trail for signal/alert/review actions (compliance KPI)."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor = Column(String(255), default="system")
    action = Column(String(64), index=True)   # signal_detected|signal_reviewed|alert_ack|...
    entity_type = Column(String(32))           # signal|alert|post
    entity_id = Column(Integer)
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ForgeRecord(Base):
    """A synthetic patient post produced by the Forge (persisted)."""

    __tablename__ = "forge_records"

    id = Column(Integer, primary_key=True)
    batch_id = Column(String(64), index=True)
    drug = Column(String(128))
    condition = Column(String(128))
    platform = Column(String(64))
    region = Column(String(48))
    language = Column(String(32))
    post_text = Column(Text)
    structured_json = Column(Text)       # extracted symptoms/AEs
    scenario_json = Column(Text)
    quality_score = Column(Float, default=0.0)
    scores_json = Column(Text)           # component scores
    export_ready = Column(Boolean, default=False)
    repaired = Column(Boolean, default=False)
    source = Column(String(16), default="deterministic")  # llm|deterministic
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
