"""Data-enrichment registry: configurable external endpoints + the identity /
land / telecom records scraped through them.

Everything here is the operator's OWN data, pulled from the operator's OWN
external databases via endpoints they register. Records are deduplicated (a
content hash lets an unchanged record be skipped) and parcel ownership is kept
as an ordered history so owner changes over time are preserved.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.database.base import TimestampMixin, UUIDMixin

# ── endpoint semantic roles the scraper understands ──────────────────────── #
KIND_PERSON_BY_NID = "person_by_nid"
KIND_PHONES_BY_NID = "phones_by_nid"
KIND_UPIS_BY_NID = "upis_by_nid"
KIND_NID_BY_PHONE = "nid_by_phone"
KIND_UPI_OWNERS = "upi_owners"
KIND_CUSTOM = "custom"

ENDPOINT_KINDS = (
    KIND_PERSON_BY_NID, KIND_PHONES_BY_NID, KIND_UPIS_BY_NID,
    KIND_NID_BY_PHONE, KIND_UPI_OWNERS, KIND_CUSTOM,
)


class ExternalEndpoint(UUIDMixin, TimestampMixin, table=True):
    """A registered external data endpoint. Drives the scraper (for the known
    semantic ``kind``s) and is injected into KAI's knowledge so the model can
    use it when asked something in its category.

    Secrets are referenced by NAME only (resolved from the process environment
    at call time) — never stored here. Templates may contain ``{nid}``,
    ``{phone}``, ``{upi}`` (from call params) and ``{env:VAR_NAME}``.
    """

    __tablename__ = "external_endpoints"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_endpoint_user_slug"),)

    user_id: uuid.UUID = Field(index=True, nullable=False)
    slug: str = Field(index=True, nullable=False)              # e.g. person_by_nid
    title: str = Field(nullable=False)                         # human title
    category: str = Field(default="general", index=True)       # groups KAI knowledge
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    kind: str = Field(default=KIND_CUSTOM, index=True)         # one of ENDPOINT_KINDS

    method: str = Field(default="GET")                          # GET | POST
    url_template: str = Field(nullable=False)                   # http://.../person/{nid}
    query_template: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    headers: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    body_template: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))

    auth_type: str = Field(default="none")                      # none|bearer|header_key|basic
    auth_config: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))

    # Where the useful payload sits in the JSON response (dotted path; "" = root).
    result_path: str = Field(default="")
    # Dotted keys (relative to result_path) whose values are base64 images.
    image_keys: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))

    enabled: bool = Field(default=True, index=True)
    rate_limit_per_min: int = Field(default=10)
    sample_response: str = Field(default="", sa_column=Column(Text, nullable=False))


class Person(UUIDMixin, TimestampMixin, table=True):
    """A citizen record keyed by national ID (NID)."""

    __tablename__ = "enrich_persons"

    nid: str = Field(index=True, unique=True, nullable=False)
    surnames: str | None = Field(default=None)
    forenames: str | None = Field(default=None)       # ForeName + Surnames composite handled in code
    father_names: str | None = Field(default=None)
    mother_names: str | None = Field(default=None)
    sex: str | None = Field(default=None)
    date_of_birth: str | None = Field(default=None)
    civil_status: str | None = Field(default=None)
    marital_status: str | None = Field(default=None)
    nationality: str | None = Field(default=None)

    province: str | None = Field(default=None, index=True)
    district: str | None = Field(default=None, index=True)
    sector: str | None = Field(default=None)
    cell: str | None = Field(default=None)
    village: str | None = Field(default=None)
    village_id: str | None = Field(default=None)

    place_of_birth: str | None = Field(default=None)
    country_of_birth: str | None = Field(default=None)
    country_of_domicile: str | None = Field(default=None)

    document_number: str | None = Field(default=None)
    application_number: str | None = Field(default=None)
    issue_number: str | None = Field(default=None)
    date_of_issue: str | None = Field(default=None)
    date_of_expiry: str | None = Field(default=None)

    photo_face_id: uuid.UUID | None = Field(default=None, index=True)
    raw: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    content_hash: str = Field(default="", index=True)  # skip-unchanged detection
    source_endpoint: str | None = Field(default=None)
    last_scraped_at: str | None = Field(default=None)


class Parcel(UUIDMixin, TimestampMixin, table=True):
    """A land parcel keyed by UPI. Current owner + full ownership history (see
    :class:`ParcelOwnership`)."""

    __tablename__ = "enrich_parcels"

    upi: str = Field(index=True, unique=True, nullable=False)
    province: str | None = Field(default=None)
    district: str | None = Field(default=None)
    sector: str | None = Field(default=None)
    cell: str | None = Field(default=None)
    village: str | None = Field(default=None)
    land_use: str | None = Field(default=None)
    size: float | None = Field(default=None)

    current_owner_nid: str | None = Field(default=None, index=True)
    raw: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    source_endpoint: str | None = Field(default=None)
    last_scraped_at: str | None = Field(default=None)


class ParcelOwnership(UUIDMixin, TimestampMixin, table=True):
    """One ownership record for a UPI. Ordered chain of these = the ownership
    hierarchy over time. ``is_current`` marks the present owner."""

    __tablename__ = "enrich_parcel_ownership"
    __table_args__ = (
        UniqueConstraint("upi", "owner_nid", "content_hash", name="uq_ownership_upi_owner_hash"),
    )

    upi: str = Field(index=True, nullable=False)
    owner_nid: str | None = Field(default=None, index=True)
    is_current: bool = Field(default=True, index=True)
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    transaction_type: str | None = Field(default=None)
    sale_price: float | None = Field(default=None)
    size: float | None = Field(default=None)
    source: str = Field(default="scrape")   # csv | scrape | <endpoint slug>
    content_hash: str = Field(default="", index=True)


class PhoneNumber(UUIDMixin, TimestampMixin, table=True):
    """A phone number linked to a person (NID)."""

    __tablename__ = "enrich_phones"
    __table_args__ = (UniqueConstraint("msisdn", "nid", name="uq_phone_msisdn_nid"),)

    msisdn: str = Field(index=True, nullable=False)
    nid: str | None = Field(default=None, index=True)
    mno: str | None = Field(default=None)              # mobile network operator
    service_period: str | None = Field(default=None)
    source: str = Field(default="scrape")


class ScrapeJob(UUIDMixin, TimestampMixin, table=True):
    """A background enrichment run. Progress + per-category counters are
    persisted so the UI can poll live status."""

    __tablename__ = "enrich_scrape_jobs"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    kind: str = Field(nullable=False)   # phone_seed | csv_upi | nid_seed
    # queued | running | paused | cancelled | done | error
    status: str = Field(default="queued", index=True)
    params: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    rate_limit_per_min: int = Field(default=10)

    total: int = Field(default=0)
    processed: int = Field(default=0)
    stats: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    log: list = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    last_message: str = Field(default="", sa_column=Column(Text, nullable=False))

    started_at: str | None = Field(default=None)
    finished_at: str | None = Field(default=None)
