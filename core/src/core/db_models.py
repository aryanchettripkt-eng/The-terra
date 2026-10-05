"""SQLAlchemy 2.0 ORM Declarative Models for SETU-DRR.

Matches database schema defined in infra/migrations/002_core_schema.sql and 005_candidate_site_metadata.sql.
"""

from __future__ import annotations

import uuid
from datetime import datetime, date, timezone
from typing import Any, Optional, List
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date as SQLDate,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from geoalchemy2 import Geometry, Geography


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


class SourceSnapshot(Base):
    __tablename__ = "source_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    valid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    uri: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    pipeline_runs: Mapped[List[PipelineRun]] = relationship(
        "PipelineRun", back_populates="source_snapshot"
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    code_version: Mapped[str] = mapped_column(String, nullable=False)
    config_version: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    source_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("source_snapshot.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    source_snapshot: Mapped[Optional[SourceSnapshot]] = relationship(
        "SourceSnapshot", back_populates="pipeline_runs"
    )


class ServingVersion(Base):
    __tablename__ = "serving_version"

    dataset_name: Mapped[str] = mapped_column(String, primary_key=True)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    pipeline_run: Mapped[PipelineRun] = relationship("PipelineRun")


class AdminBoundary(Base):
    __tablename__ = "admin_boundary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    lgd_code: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="CASCADE"), nullable=True
    )
    geom: Mapped[Optional[Any]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True, deferred=True
    )
    bbox: Mapped[Optional[Any]] = mapped_column(
        Geometry("POLYGON", srid=4326), nullable=True, deferred=True
    )

    children: Mapped[List[AdminBoundary]] = relationship(
        "AdminBoundary", backref="parent", remote_side=[id]
    )
    habitations: Mapped[List[Habitation]] = relationship(
        "Habitation", back_populates="admin_boundary"
    )
    grid_cells: Mapped[List[GridCell]] = relationship(
        "GridCell", back_populates="admin_boundary"
    )


class Habitation(Base):
    __tablename__ = "habitation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lgd_code: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, default="village", nullable=False)
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True
    )
    geom_point: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    geom_footprint: Mapped[Optional[Any]] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True
    )
    population: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    households: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_habitation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    import_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("data_import_run.id", ondelete="RESTRICT"), nullable=True
    )
    risk_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)

    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship(
        "AdminBoundary", back_populates="habitations"
    )
    vulnerability: Mapped[Optional[Vulnerability]] = relationship(
        "Vulnerability", back_populates="habitation", uselist=False
    )
    risk_profile: Mapped[Optional[HabitationRisk]] = relationship(
        "HabitationRisk", back_populates="habitation", uselist=False, cascade="all, delete-orphan"
    )
    relocation_plans: Mapped[List[RelocationPlan]] = relationship(
        "RelocationPlan", back_populates="habitation"
    )


class GridCell(Base):
    __tablename__ = "grid_cell"

    h3: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    res: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True
    )
    habitation_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("habitation.id", ondelete="SET NULL"), nullable=True
    )
    centroid: Mapped[Any] = mapped_column(Geography("POINT", srid=4326), nullable=False)
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    population: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    built_area_m2: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String, default="v1.0", nullable=False)

    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship(
        "AdminBoundary", back_populates="grid_cells"
    )
    hazard_statics: Mapped[List[HazardStatic]] = relationship(
        "HazardStatic", back_populates="grid_cell", cascade="all, delete-orphan"
    )
    mhi_snapshots: Mapped[List[MHISnapshot]] = relationship(
        "MHISnapshot", back_populates="grid_cell", cascade="all, delete-orphan"
    )
    explanation: Mapped[Optional[Explanation]] = relationship(
        "Explanation", back_populates="grid_cell", uselist=False, cascade="all, delete-orphan"
    )


class HazardStatic(Base):
    __tablename__ = "hazard_static"

    h3: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("grid_cell.h3", ondelete="CASCADE"), primary_key=True
    )
    hazard_type: Mapped[str] = mapped_column(String, primary_key=True)
    susceptibility: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    quality_flag: Mapped[str] = mapped_column(String, default="full", nullable=False)
    model_version: Mapped[str] = mapped_column(String, default="v1.0.0", nullable=False)
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )

    grid_cell: Mapped[GridCell] = relationship("GridCell", back_populates="hazard_statics")


class HazardStaticFlood(Base):
    """Per-cell riverine flood drivers from Step 10 zonal aggregation (migration 007)."""

    __tablename__ = "hazard_static_flood"

    h3: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("grid_cell.h3", ondelete="CASCADE"), primary_key=True
    )
    max_susceptibility: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valid_pixel_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hard_zero_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_inundation_frequency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_hand_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_hand_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_slope_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_cropland_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hazard_regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mean_anomalous_frequency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    jrc_occurrence_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_water_fraction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dist_tributary_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dist_mainstem_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observation_ceiling: Mapped[int] = mapped_column(SmallInteger, default=30, nullable=False)
    model_version: Mapped[str] = mapped_column(
        String, default="flood-susceptibility-v0.1", nullable=False
    )
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )


class HazardDynamic(Base):
    __tablename__ = "hazard_dynamic"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    h3: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hazard_type: Mapped[str] = mapped_column(String, nullable=False)
    valid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    forecast_cycle_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )


class MHISnapshot(Base):
    __tablename__ = "mhi_snapshot"

    h3: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("grid_cell.h3", ondelete="CASCADE"), primary_key=True
    )
    valid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    mhi_static: Mapped[float] = mapped_column(Float, nullable=False)
    mhi_live: Mapped[float] = mapped_column(Float, nullable=False)
    mhi_fcst: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dominant_hazard: Mapped[str] = mapped_column(String, nullable=False)
    zone_class: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )

    grid_cell: Mapped[GridCell] = relationship("GridCell", back_populates="mhi_snapshots")


class Explanation(Base):
    __tablename__ = "explanation"

    h3: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("grid_cell.h3", ondelete="CASCADE"), primary_key=True
    )
    model_version: Mapped[str] = mapped_column(String, default="v1.0.0", nullable=False)
    factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    screening_grade: Mapped[str] = mapped_column(
        String,
        default="Screening Grade: Geotechnical investigation required before decision",
        nullable=False,
    )

    grid_cell: Mapped[GridCell] = relationship("GridCell", back_populates="explanation")


class Vulnerability(Base):
    __tablename__ = "vulnerability"

    habitation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("habitation.id", ondelete="CASCADE"), primary_key=True
    )
    v_demographic: Mapped[float] = mapped_column(Float, nullable=False)
    v_structural: Mapped[float] = mapped_column(Float, nullable=False)
    v_access: Mapped[float] = mapped_column(Float, nullable=False)
    v_economic: Mapped[float] = mapped_column(Float, nullable=False)
    v_index: Mapped[float] = mapped_column(Float, nullable=False)
    is_district_flat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )

    habitation: Mapped[Habitation] = relationship("Habitation", back_populates="vulnerability")


class HabitationRisk(Base):
    __tablename__ = "habitation_risk"

    habitation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("habitation.id", ondelete="CASCADE"), primary_key=True
    )
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True
    )
    population: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    households: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hazard_intensity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    prz_overlap_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    decayed_loss: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    v_index: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    caseload_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    active_deformation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fatal_event_last_3_monsoons: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mitigation_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    relocation_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    adverse_trend: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hazard_regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    relocation_pathway: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    triage_rationale: Mapped[str] = mapped_column(String, default="", nullable=False)
    contributing_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    dominant_hazard: Mapped[str] = mapped_column(String, default="landslide", nullable=False)
    model_version: Mapped[str] = mapped_column(String, default="baseline-v1", nullable=False)
    scoring_version: Mapped[str] = mapped_column(String, default="priority-v1.0", nullable=False)
    dataset_version: Mapped[str] = mapped_column(String, default="v1.0", nullable=False)
    data_quality: Mapped[str] = mapped_column(String, default="observed", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )

    habitation: Mapped[Habitation] = relationship("Habitation", back_populates="risk_profile")
    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship("AdminBoundary")


class DisasterEvent(Base):
    __tablename__ = "disaster_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[date] = mapped_column(SQLDate, nullable=False)
    hazard_type: Mapped[str] = mapped_column(String, nullable=False)
    geom: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=False)
    fatalities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    injured: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    houses_damaged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class CandidateSite(Base):
    __tablename__ = "candidate_site"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_site_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True
    )
    import_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("data_import_run.id", ondelete="RESTRICT"), nullable=True
    )
    assessment_status: Mapped[str] = mapped_column(String, default="screening_only", nullable=False)
    eligibility_status: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    centroid: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    tenure: Mapped[str] = mapped_column(String, nullable=False)
    slope_mean: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mhi_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cc_land: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cc_water: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cc_school: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cc_health: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cc_final: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    binding_constraint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    augmented: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    suitability: Mapped[Optional[int]] = mapped_column(SmallInteger, default=None, nullable=True)
    screening_infra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    infra_screening_status: Mapped[str] = mapped_column(
        String, default="unscreened", nullable=False
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )
    primary_health_facility_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("health_facility.id", ondelete="SET NULL"), nullable=True
    )
    health_travel_time_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    health_distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship("AdminBoundary")
    primary_health_facility: Mapped[Optional["HealthFacility"]] = relationship("HealthFacility")
    relocation_plans: Mapped[List[RelocationPlan]] = relationship(
        "RelocationPlan", back_populates="candidate_site"
    )


class OsmInfrastructureFacility(Base):
    __tablename__ = "osm_infrastructure_facility"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    osm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    osm_type: Mapped[str] = mapped_column(String, nullable=False)  # node, way, relation
    facility_type: Mapped[str] = mapped_column(String, nullable=False)  # school, health, water, road
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    operator_type: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="CASCADE"), nullable=True
    )
    source_snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("source_snapshot.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship("AdminBoundary")



class AllocationRun(Base):
    __tablename__ = "allocation_run"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="COMPLETED", nullable=False)
    solver_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_households_relocated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    pipeline_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipeline_run.id", ondelete="SET NULL"), nullable=True
    )

    relocation_plans: Mapped[List[RelocationPlan]] = relationship(
        "RelocationPlan", back_populates="allocation_run", cascade="all, delete-orphan"
    )


class RelocationPlan(Base):
    __tablename__ = "relocation_plan"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    allocation_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("allocation_run.id", ondelete="CASCADE"), nullable=False
    )
    habitation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("habitation.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("candidate_site.id", ondelete="CASCADE"), nullable=False
    )
    households: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    has_group_split: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PROPOSED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    allocation_run: Mapped[AllocationRun] = relationship(
        "AllocationRun", back_populates="relocation_plans"
    )
    habitation: Mapped[Habitation] = relationship(
        "Habitation", back_populates="relocation_plans"
    )
    candidate_site: Mapped[CandidateSite] = relationship(
        "CandidateSite", back_populates="relocation_plans"
    )


class AppUser(Base):
    """User account entity for SETU-DRR authentication."""
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    google_sub: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String, default="google", nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True, index=True
    )

    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship("AdminBoundary")
    sessions: Mapped[List[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def jurisdiction(self) -> Optional[dict[str, Any]]:
        """Safe serializable jurisdiction descriptor for frontend contract."""
        if self.admin_boundary is not None:
            return {
                "admin_id": self.admin_boundary.id,
                "name": self.admin_boundary.name,
                "level": self.admin_boundary.level,
                "lgd_code": self.admin_boundary.lgd_code,
            }
        return None


class UserSession(Base):
    """Server-side authenticated session."""
    __tablename__ = "user_session"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[AppUser] = relationship("AppUser", back_populates="sessions")


class DataImportRun(Base):
    """Provenance and lifecycle record for external data imports."""
    __tablename__ = "data_import_run"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_name: Mapped[str] = mapped_column(String, nullable=False)
    district_name: Mapped[str] = mapped_column(String, nullable=False)
    source_pipeline: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String, nullable=False)
    artifact_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String, default="STAGED", nullable=False)
    row_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalRelocationRecommendation(Base):
    """Offline recommendation from external GIS pipelines, strictly decoupled from canonical SETU decisions."""
    __tablename__ = "external_relocation_recommendation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("data_import_run.id", ondelete="RESTRICT"), nullable=False
    )
    habitation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("habitation.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("candidate_site.id", ondelete="RESTRICT"), nullable=False
    )
    external_habitation_key: Mapped[str] = mapped_column(String, nullable=False)
    external_site_key: Mapped[str] = mapped_column(String, nullable=False)
    origin_type: Mapped[str] = mapped_column(String, default="external", nullable=False)
    decision_status: Mapped[str] = mapped_column(String, default="recommendation", nullable=False)
    households: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    site_suitability: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    site_cc_final: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    site_binding: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    has_group_split: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    screening_grade: Mapped[str] = mapped_column(
        String, default="Screening Grade: Cell-level external recommendation", nullable=False
    )
    screening_caveats: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_pipeline: Mapped[str] = mapped_column(String, default="external_gis_v1", nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String, default="v1.0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    import_run: Mapped[DataImportRun] = relationship("DataImportRun")
    habitation: Mapped[Habitation] = relationship("Habitation")
    candidate_site: Mapped[CandidateSite] = relationship("CandidateSite")


class HealthFacility(Base):
    __tablename__ = "health_facility"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nin_n: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    admin_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("admin_boundary.id", ondelete="SET NULL"), nullable=True
    )
    import_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("data_import_run.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    facility_type: Mapped[str] = mapped_column(String, nullable=False)
    ownership_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    location_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subdistrict: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    h3_res8: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_physical: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    norm_population: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    admin_boundary: Mapped[Optional[AdminBoundary]] = relationship("AdminBoundary")


class HistoricalDisasterLoss(Base):
    __tablename__ = "historical_disaster_loss"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    year_label: Mapped[str] = mapped_column(String(30), nullable=False)
    year_start: Mapped[int] = mapped_column(Integer, nullable=False)
    year_end: Mapped[int] = mapped_column(Integer, nullable=False)
    lives_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cattle_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    houses_damaged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    crop_area_affected_ha: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    hazard_types_included: Mapped[str] = mapped_column(
        String(255), default="Floods/Heavy Rains/Landslides/Cyclones", nullable=False
    )
    source_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    source_title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ministry: Mapped[str] = mapped_column(String(255), nullable=False)
    data_quality_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class NcrbNaturalHazardCasualty(Base):
    __tablename__ = "ncrb_natural_hazard_casualty"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    calendar_year: Mapped[int] = mapped_column(Integer, nullable=False)
    landslide_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flash_flood_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flood_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cloudburst_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cyclone_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avalanche_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lightning_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cold_heat_wave_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    other_nature_deaths: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_deaths: Mapped[int] = mapped_column(Integer, nullable=False)
    source_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class CwcFloodDamageRecord(Base):
    __tablename__ = "cwc_flood_damage_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    calendar_year: Mapped[int] = mapped_column(Integer, nullable=False)
    area_affected_mha: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    population_affected_m: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    human_lives_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cattle_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    houses_damaged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_damage_crores: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class HighwayDisasterDamage(Base):
    __tablename__ = "highway_disaster_damage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    reporting_period: Mapped[str] = mapped_column(String(50), nullable=False)
    damaged_length_km: Mapped[float] = mapped_column(Float, nullable=False)
    disaster_triggers: Mapped[str] = mapped_column(
        String(255), default="Heavy Rain / Landslide / Flood", nullable=False
    )
    source_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class DisasterReliefAllocation(Base):
    __tablename__ = "disaster_relief_allocation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(30), nullable=False)
    sdrf_central_share_cr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sdrf_state_share_cr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ndrf_releases_cr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    lives_saved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class DisasterCaseStudy(Base):
    __tablename__ = "disaster_case_study"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    disaster_type: Mapped[str] = mapped_column(String(100), nullable=False)
    state_name: Mapped[str] = mapped_column(String(100), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_date: Mapped[date] = mapped_column(SQLDate, nullable=False)
    fatalities: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    injured: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compensation_cr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    geotechnical_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

