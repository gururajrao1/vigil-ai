"""Central configuration. Everything degrades gracefully when keys are absent.

VigilAI is worldwide-first: global data, models, and standards are the default,
with India-specific handling layered on top. Every network/LLM capability has an
offline deterministic fallback so the whole product runs with zero API keys.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _b(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        # Resolve SQLite path to an absolute path anchored at the backend directory
        # so the DB is always created in backend/ regardless of the working directory
        # uvicorn was started from. PostgreSQL DATABASE_URL env vars are used as-is.
        _default_db = os.getenv("DATABASE_URL", "sqlite:///./vigilai.db")
        if _default_db.startswith("sqlite:///./"):
            _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _db_file = _default_db.replace("sqlite:///./", "")
            _default_db = f"sqlite:///{os.path.join(_backend_dir, _db_file)}"
        self.database_url: str = _default_db

        # Optional live sources
        self.twitter_api_key: str = os.getenv("TWITTERAPI_IO_KEY", "").strip()
        self.firecrawl_api_key: str = os.getenv("FIRECRAWL_API_KEY", "").strip()
        self.youtube_api_key: str = os.getenv("YOUTUBE_API_KEY", "").strip()

        # Optional LLM. Ollama is local + free (no key). Default URL points at the
        # standard local daemon; if it is not running, callers fall back cleanly.
        self.ollama_base_url: str = os.getenv(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
        ).strip()
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
        self.use_llm: bool = _b("USE_LLM", "true")
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.openrouter_base_url: str = os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).strip()

        # openFDA (no key needed)
        self.openfda_api_key: str = os.getenv("OPENFDA_API_KEY", "").strip()
        self.ncbi_api_key: str = os.getenv("NCBI_API_KEY", "").strip()
        self.openfda_base_url: str = os.getenv(
            "OPENFDA_BASE_URL", "https://api.fda.gov"
        ).strip()

        # Worldwide public terminology services (no key)
        self.rxnorm_base_url: str = os.getenv(
            "RXNORM_BASE_URL", "https://rxnav.nlm.nih.gov/REST"
        ).strip()
        self.icd11_base_url: str = os.getenv(
            "ICD11_BASE_URL", "https://id.who.int/icd"
        ).strip()

        # Additional keyless evidence connectors (all optional, offline fallback)
        self.dailymed_base_url: str = os.getenv(
            "DAILYMED_BASE_URL", "https://dailymed.nlm.nih.gov/dailymed/services/v2"
        ).strip()
        self.pubmed_base_url: str = os.getenv(
            "PUBMED_BASE_URL", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        ).strip()
        # Master switch for label/recall/literature/device-class enrichment.
        # Enrichment runs LAZILY per signal on first detail view (<=4 cached calls),
        # never as a bulk burst, so it is safe to leave ON. Set false to fully disable
        # external enrichment (pure offline).
        self.use_evidence_enrichment: bool = _b("USE_EVIDENCE_ENRICHMENT", "true")

        # Feature flags. Transformer NER + drug normalization default ON (internet
        # available) but always fall back to the offline lexicon path.
        self.use_transformer_ner: bool = _b("USE_TRANSFORMER_NER", "true")
        self.transformer_ner_model: str = os.getenv(
            "TRANSFORMER_NER_MODEL", "d4data/biomedical-ner-all"
        ).strip()
        self.use_presidio: bool = _b("USE_PRESIDIO", "true")
        self.use_rxnorm: bool = _b("USE_RXNORM", "true")
        self.use_online_translation: bool = _b("USE_ONLINE_TRANSLATION", "true")

        # Auth
        self.jwt_secret: str = os.getenv("JWT_SECRET", "vigilai-dev-secret-change-me").strip()
        self.jwt_algorithm: str = "HS256"
        self.jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
        self.seed_admin_email: str = os.getenv("SEED_ADMIN_EMAIL", "admin@vigilai.dev").strip()
        self.seed_admin_password: str = os.getenv("SEED_ADMIN_PASSWORD", "admin123").strip()

        # Forge (synthetic data) knobs
        self.forge_quality_threshold: int = int(os.getenv("FORGE_QUALITY_THRESHOLD", "80"))
        self.forge_max_repair: int = int(os.getenv("FORGE_MAX_REPAIR_ATTEMPTS", "1"))

        # Optional outbound alert webhook (Slack/Teams/custom). Empty = log-only.
        self.alert_webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "").strip()

        # Agentic discovery pipeline (Steps 2–3) — optional; offline fallbacks always available
        self.exa_api_key: str = os.getenv("EXA_API_KEY", "").strip()
        self.tavily_api_key: str = os.getenv("TAVILY_API_KEY", "").strip()
        self.playwright_storage_state_path: str = os.getenv("PLAYWRIGHT_STORAGE_STATE_PATH", "").strip()
        # Self-hosted Pathfinder (preferred over SaaS when available)
        self.searxng_base_url: str = os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
        self.firecrawl_base_url: str = os.getenv("FIRECRAWL_BASE_URL", "").rstrip("/")  # self-hosted Firecrawl API
        self.firecrawl_api_key: str = os.getenv("FIRECRAWL_API_KEY", "").strip()
        self.stitch_api_base: str = os.getenv(
            "STITCH_CHEM_API_BASE", "https://string-db.org/api"
        ).rstrip("/")  # STITCH/STRING-compatible enrichment endpoint

    @property
    def llm_enabled(self) -> bool:
        """Whether any LLM backend is configured (Ollama local counts)."""
        return bool(
            self.use_llm
            and (self.ollama_base_url or self.gemini_api_key or self.openrouter_api_key)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
