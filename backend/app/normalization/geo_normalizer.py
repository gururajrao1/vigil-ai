"""Step 4 — Geographic synonym normalization (GeoNames-inspired gazetteer).

Resolves historical / municipal aliases (Madras→Chennai, Bangalore→Bengaluru)
to a canonical city primary key with approximate centroid coordinates.
"""
from __future__ import annotations

import logging
from typing import Optional

from . import catalog
from .models import GeoResolution

logger = logging.getLogger("vigilai.mcn.geo")

FUZZY_THRESHOLD = 88.0


class GeoNormalizer:
    def __init__(self) -> None:
        places = catalog.load_geo_gazetteer().get("places", [])
        self._alias_index: dict[str, dict] = {}
        self._surfaces: list[str] = []
        for place in places:
            aliases = list(place.get("aliases") or []) + [place.get("canonical", "")]
            for alias in aliases:
                key = (alias or "").strip().lower()
                if not key:
                    continue
                if key not in self._alias_index:
                    self._alias_index[key] = place
                    self._surfaces.append(key)

    def normalize(self, verbatim: str) -> GeoResolution:
        text = (verbatim or "").strip()
        if not text:
            return GeoResolution(verbatim=text)

        key = text.lower()
        place = self._alias_index.get(key)
        method = "exact_alias"
        alias_used = key if place else None

        if place is None:
            fuzzy = self._fuzzy(key)
            if fuzzy:
                place, alias_used, _score = fuzzy
                method = "fuzzy_alias"

        if place is None:
            return GeoResolution(verbatim=text, match_method="unmatched")

        return GeoResolution(
            verbatim=text,
            matched=True,
            canonical=place.get("canonical"),
            country=place.get("country"),
            admin1=place.get("admin1"),
            lat=place.get("lat"),
            lon=place.get("lon"),
            geonames_id=place.get("geonames_id"),
            match_method=method,
            alias_used=alias_used,
        )

    def _fuzzy(self, query: str) -> Optional[tuple]:
        if not query:
            return None
        try:
            from rapidfuzz import fuzz, process

            hit = process.extractOne(
                query,
                self._surfaces,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
            if not hit:
                return None
            surface, score, _ = hit
            return self._alias_index[surface], surface, float(score) / 100.0
        except Exception:
            from difflib import SequenceMatcher

            best_s, best_p, best = "", None, 0.0
            for surface in self._surfaces:
                ratio = SequenceMatcher(None, query, surface).ratio()
                if ratio > best:
                    best, best_s, best_p = ratio, surface, self._alias_index[surface]
            if best_p and best * 100 >= FUZZY_THRESHOLD:
                return best_p, best_s, best
            return None


_GEO: Optional[GeoNormalizer] = None


def get_geo_normalizer() -> GeoNormalizer:
    global _GEO
    if _GEO is None:
        _GEO = GeoNormalizer()
    return _GEO


def normalize_location(verbatim: str) -> GeoResolution:
    return get_geo_normalizer().normalize(verbatim)
