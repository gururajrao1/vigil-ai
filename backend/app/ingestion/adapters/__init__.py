"""Modular Phase-1 ingestion adapters over VigilAI crawl connectors."""
from .base import AdapterResult, IngestAdapter
from .clinical_notes import ClinicalNotesAdapter
from .faers import FaersAdapter
from .literature import LiteratureAdapter
from .maude import MaudeAdapter
from .reddit import RedditAdapter

__all__ = [
    "AdapterResult",
    "IngestAdapter",
    "FaersAdapter",
    "MaudeAdapter",
    "LiteratureAdapter",
    "RedditAdapter",
    "ClinicalNotesAdapter",
]
