"""OMOP CDM v5.4 ORM surface for VigilAI (Module 3).

Defines SQLAlchemy models for the core tables required by the unified SPA:

* ``concept``
* ``person``
* ``drug_exposure``
* ``condition_occurrence``
* ``drug_condition_baseline`` (SIDER / in-label expected pairs)

Physical table names keep the existing ``omop_*`` staging prefix so prior
sync / Universe-vs-Subset code keeps working. Column sets follow OMOP CDM
v5.4 required fields; VigilAI linkage columns (``project_id``, ``author_hash``,
``source_raw_id``) are additive staging extensions and never replace CDM FKs.

``concept_id`` columns are **BIGINT** so RxNorm Extension / Athena-style IDs
and VigilAI surrogate hashes in the 2e9 range do not overflow PostgreSQL
INTEGER (max 2_147_483_647).

Concept IDs / codes are open surrogates (RxNorm Extension, MedDRA-style PT
keys, SNOMED-style gender 8507/8532). Licensed SNOMED-CT and MedDRA are NOT
bundled.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from ..database import Base

# SNOMED-style gender concept IDs (OMOP convention)
GENDER_MALE = 8507
GENDER_FEMALE = 8532
GENDER_UNKNOWN = 0

# Condition type concepts (VigilAI staging convention)
CONDITION_TYPE_PRIMARY_AE = 32879  # "AE from source" surrogate
CONDITION_TYPE_COMORBIDITY = 32840  # "EHR problem list" surrogate

OMOP_CDM_VERSION = "5.4"
OMOP_DISCLAIMER = ""


class Concept(Base):
    """OMOP CONCEPT — vocabulary row (drug, condition, gender, …)."""

    __tablename__ = "omop_concept"

    concept_id = Column(BigInteger, primary_key=True, autoincrement=False)
    concept_name = Column(String(255), nullable=False, index=True)
    domain_id = Column(String(20), nullable=False, index=True)
    vocabulary_id = Column(String(20), nullable=False, index=True)
    concept_class_id = Column(String(20), nullable=False, default="Clinical Finding")
    standard_concept = Column(String(1), nullable=True)
    concept_code = Column(String(50), nullable=False, index=True)
    valid_start_date = Column(Date, nullable=False, default=date(1970, 1, 1))
    valid_end_date = Column(Date, nullable=False, default=date(2099, 12, 31))
    invalid_reason = Column(String(1), nullable=True)


class Person(Base):
    """OMOP PERSON — one row per pseudonymous subject."""

    __tablename__ = "omop_person"

    person_id = Column(Integer, primary_key=True, autoincrement=True)
    gender_concept_id = Column(BigInteger, default=GENDER_UNKNOWN, index=True)
    year_of_birth = Column(Integer, nullable=True)
    month_of_birth = Column(Integer, nullable=True)
    day_of_birth = Column(Integer, nullable=True)
    birth_datetime = Column(DateTime, nullable=True)
    race_concept_id = Column(BigInteger, default=0, nullable=False)
    ethnicity_concept_id = Column(BigInteger, default=0, nullable=False)
    location_id = Column(Integer, nullable=True)
    provider_id = Column(Integer, nullable=True)
    care_site_id = Column(Integer, nullable=True)
    person_source_value = Column(String(50), nullable=True)
    gender_source_value = Column(String(50), nullable=True)
    gender_source_concept_id = Column(BigInteger, default=0)
    race_source_value = Column(String(50), nullable=True)
    race_source_concept_id = Column(BigInteger, default=0)
    ethnicity_source_value = Column(String(50), nullable=True)
    ethnicity_source_concept_id = Column(BigInteger, default=0)
    # VigilAI staging extensions
    author_hash = Column(String(64), index=True)
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    drug_exposures = relationship("DrugExposure", back_populates="person")
    condition_occurrences = relationship("ConditionOccurrence", back_populates="person")


class DrugExposure(Base):
    """OMOP DRUG_EXPOSURE — product exposure linked to PERSON (+ optional CONCEPT)."""

    __tablename__ = "omop_drug_exposure"

    drug_exposure_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(
        Integer, ForeignKey("omop_person.person_id"), index=True, nullable=False
    )
    drug_concept_id = Column(String(64), index=True)
    drug_concept_id_int = Column(
        BigInteger, ForeignKey("omop_concept.concept_id"), nullable=True, index=True
    )
    drug_exposure_start_date = Column(Date, index=True, nullable=True)
    drug_exposure_end_date = Column(Date, nullable=True)
    drug_type_concept_id = Column(BigInteger, default=38000177)
    stop_reason = Column(String(20), nullable=True)
    refills = Column(Integer, nullable=True)
    quantity = Column(Integer, nullable=True)
    days_supply = Column(Integer, nullable=True)
    sig = Column(Text, nullable=True)
    route_concept_id = Column(BigInteger, default=0)
    lot_number = Column(String(50), nullable=True)
    provider_id = Column(Integer, nullable=True)
    visit_occurrence_id = Column(Integer, nullable=True)
    drug_source_value = Column(String(256), nullable=True)
    drug_source_concept_id = Column(BigInteger, default=0)
    route_source_value = Column(String(64), nullable=True)
    dose_unit_source_value = Column(String(50), nullable=True)
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    person = relationship("Person", back_populates="drug_exposures")
    drug_concept = relationship("Concept", foreign_keys=[drug_concept_id_int])


class ConditionOccurrence(Base):
    """OMOP CONDITION_OCCURRENCE — AE / comorbidity linked to PERSON."""

    __tablename__ = "omop_condition_occurrence"

    condition_occurrence_id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(
        Integer, ForeignKey("omop_person.person_id"), index=True, nullable=False
    )
    condition_concept_id = Column(String(128), index=True)
    condition_concept_id_int = Column(
        BigInteger, ForeignKey("omop_concept.concept_id"), nullable=True, index=True
    )
    condition_start_date = Column(Date, index=True, nullable=True)
    condition_end_date = Column(Date, nullable=True)
    condition_type_concept_id = Column(
        BigInteger, default=CONDITION_TYPE_PRIMARY_AE, index=True
    )
    condition_status_concept_id = Column(BigInteger, nullable=True)
    stop_reason = Column(String(20), nullable=True)
    provider_id = Column(Integer, nullable=True)
    visit_occurrence_id = Column(Integer, nullable=True)
    condition_source_value = Column(String(256), nullable=True)
    condition_source_concept_id = Column(BigInteger, default=0)
    condition_status_source_value = Column(String(64), nullable=True)
    # SIDER / label-known AE flag (dashboard can filter expected baseline)
    is_expected_baseline = Column(Boolean, default=False, index=True)
    project_id = Column(Integer, index=True)
    source_raw_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    person = relationship("Person", back_populates="condition_occurrences")
    condition_concept = relationship("Concept", foreign_keys=[condition_concept_id_int])


class DrugConditionBaseline(Base):
    """SIDER / package-insert expected drug↔AE pairings (in-label baseline)."""

    __tablename__ = "omop_drug_condition_baseline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    drug_concept_id = Column(BigInteger, index=True, nullable=True)
    condition_concept_id = Column(BigInteger, index=True, nullable=True)
    drug_source_value = Column(String(256), nullable=True, index=True)
    condition_source_value = Column(String(256), nullable=True, index=True)
    is_expected_baseline = Column(Boolean, default=True, nullable=False, index=True)
    source = Column(String(64), default="SIDER 4.1", nullable=False)
    project_id = Column(Integer, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Back-compat names used across mapper / analytics / routes
OmopConcept = Concept
OmopPerson = Person
OmopDrugExposure = DrugExposure
OmopConditionOccurrence = ConditionOccurrence
OmopDrugConditionBaseline = DrugConditionBaseline


def today_or(dt: datetime | date | None) -> date:
    if dt is None:
        return date.today()
    if isinstance(dt, datetime):
        return dt.date()
    return dt
