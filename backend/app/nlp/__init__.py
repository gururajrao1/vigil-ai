"""VigilAI NLP engine.

Phase 3 biomedical resolvers (Omni-Search normalization):

* ``sapbert_encoder.SapBERTEncoder`` — SapBERT / BioBERT / n-gram embeddings
* ``rxnorm_resolver.RxNormResolver`` — brand / INN → OMOP RxNorm + ingredients / ATC
* ``meddra_resolver.MedDRAResolver`` — colloquial AE → MedDRA PT / SOC
* ``omni_search_service.OmniSearchService`` — drug vs AE routing → OMOP ``concept_id``
"""

from .omni_search_service import OmniSearchHit, OmniSearchService, omni_normalize
from .rxnorm_resolver import RxNormResolution, RxNormResolver
from .meddra_resolver import MedDRAResolution, MedDRAResolver
from .sapbert_encoder import SapBERTEncoder, get_sapbert_encoder

__all__ = [
    "SapBERTEncoder",
    "get_sapbert_encoder",
    "RxNormResolver",
    "RxNormResolution",
    "MedDRAResolver",
    "MedDRAResolution",
    "OmniSearchService",
    "OmniSearchHit",
    "omni_normalize",
]
