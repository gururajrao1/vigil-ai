"""OMOP CDM v5.4 *staging* tables for VigilAI (compat shim).

Canonical definitions live in ``app.db.omop_models`` (Module 3). This module
re-exports them so existing imports (`omop_mapper`, `omop_analytics`, routes)
keep working without a mass rename.
"""
from __future__ import annotations

from ..omop_models import (  # noqa: F401
    CONDITION_TYPE_COMORBIDITY,
    CONDITION_TYPE_PRIMARY_AE,
    GENDER_FEMALE,
    GENDER_MALE,
    GENDER_UNKNOWN,
    OMOP_CDM_VERSION,
    OMOP_DISCLAIMER,
    Concept,
    ConditionOccurrence,
    DrugConditionBaseline,
    DrugExposure,
    OmopConcept,
    OmopConditionOccurrence,
    OmopDrugConditionBaseline,
    OmopDrugExposure,
    OmopPerson,
    Person,
    today_or,
)

# Optional device table remains local so device PV sync does not break.
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String

from ...database import Base


class OmopDeviceExposure(Base):
    """OMOP DEVICE_EXPOSURE — device / combination product exposure."""

    __tablename__ = "omop_device_exposure"

    device_exposure_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("omop_person.person_id"), index=True, nullable=False)
    device_concept_id = Column(String(64), index=True)
    device_exposure_start_date = Column(Date, index=True)
    unique_device_id = Column(String(128), nullable=True)
    device_source_value = Column(String(256))
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
