"""OMOP CDM v5.4 *staging* tables for VigilAI.

These are an abstraction layer over social/ICSR-derived narratives — not a full
OMOP warehouse. Concept IDs use open surrogates (RxNorm/ATC strings, MedDRA-style
PT keys, GMDN codes, SNOMED-style gender codes 8507/8532). Licensed SNOMED-CT
and MedDRA are NOT bundled.

Tables are created by ``init_db()`` via SQLAlchemy ``create_all``.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from ...database import Base

# SNOMED-style gender concept IDs (OMOP convention)
GENDER_MALE = 8507
GENDER_FEMALE = 8532
GENDER_UNKNOWN = 0

# Condition type concepts (VigilAI staging convention)
CONDITION_TYPE_PRIMARY_AE = 32879  # "AE from source" surrogate
CONDITION_TYPE_COMORBIDITY = 32840  # "EHR problem list" surrogate


class OmopPerson(Base):
    """OMOP PERSON — one row per pseudonymous author / case subject."""

    __tablename__ = "omop_person"

    person_id = Column(Integer, primary_key=True, autoincrement=True)
    gender_concept_id = Column(Integer, default=GENDER_UNKNOWN, index=True)
    year_of_birth = Column(Integer, nullable=True)
    race_concept_id = Column(Integer, default=0)
    location_id = Column(Integer, nullable=True)
    # VigilAI linkage (not in core OMOP — staging extension)
    author_hash = Column(String(64), index=True)
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)  # first RawPost that created this person
    created_at = Column(DateTime, default=datetime.utcnow)


class OmopDrugExposure(Base):
    """OMOP DRUG_EXPOSURE — product mention as exposure event."""

    __tablename__ = "omop_drug_exposure"

    drug_exposure_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("omop_person.person_id"), index=True, nullable=False)
    drug_concept_id = Column(String(64), index=True)  # ATC / RxCUI / VIG-PC-*
    drug_exposure_start_date = Column(Date, index=True)
    drug_type_concept_id = Column(Integer, default=38000177)  # prescription / report
    drug_source_value = Column(String(256))  # surface brand/generic
    route_source_value = Column(String(64), nullable=True)
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OmopDeviceExposure(Base):
    """OMOP DEVICE_EXPOSURE — device / combination product exposure."""

    __tablename__ = "omop_device_exposure"

    device_exposure_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("omop_person.person_id"), index=True, nullable=False)
    device_concept_id = Column(String(64), index=True)  # GMDN / FDA product code
    device_exposure_start_date = Column(Date, index=True)
    unique_device_id = Column(String(128), nullable=True)
    device_source_value = Column(String(256))
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OmopConditionOccurrence(Base):
    """OMOP CONDITION_OCCURRENCE — AE PT or comorbidity."""

    __tablename__ = "omop_condition_occurrence"

    condition_occurrence_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("omop_person.person_id"), index=True, nullable=False)
    condition_concept_id = Column(String(128), index=True)  # MedDRA PT / CUI
    condition_start_date = Column(Date, index=True)
    condition_type_concept_id = Column(Integer, default=CONDITION_TYPE_PRIMARY_AE, index=True)
    condition_source_value = Column(String(256))
    condition_status_source_value = Column(String(64), nullable=True)  # ae|comorbidity
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def today_or(dt: datetime | date | None) -> date:
    if dt is None:
        return date.today()
    if isinstance(dt, datetime):
        return dt.date()
    return dt
