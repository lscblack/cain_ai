"""External-endpoint registry: CRUD helpers + seeding of the known endpoints.

Seeds are created per operator only when the matching slug is missing, so an
operator's own edits are never overwritten. Secrets live in the environment and
are referenced by name (``{env:VAR}``) inside templates.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import (
    ExternalEndpoint,
    KIND_NID_BY_PHONE,
    KIND_PERSON_BY_NID,
    KIND_PHONES_BY_NID,
    KIND_UPI_OWNERS,
    KIND_UPIS_BY_NID,
)

# Default endpoints modelled on the operator's described services. The four
# identity/land/telecom endpoints plus the UPI→owners reverse lookup the CSV
# flow needs (to be built by the operator; disabled until its URL is confirmed).
SEED_ENDPOINTS: list[dict] = [
    {
        "slug": "person_by_nid",
        "title": "Citizen information from ID",
        "category": "identity",
        "description": "Full citizen record (names, DOB, address, photo, signature) for a national ID.",
        "kind": KIND_PERSON_BY_NID,
        "method": "GET",
        "url_template": "{env:IDENTITY_API_BASE}/person/{nid}",
        "result_path": "GetCitizenResult",
        "image_keys": ["Photo", "Signature"],
        "auth_type": "none",
    },
    {
        "slug": "phones_by_nid",
        "title": "Phone numbers from ID",
        "category": "telecom",
        "description": "All MSISDNs (with operator + service period) registered to a national ID.",
        "kind": KIND_PHONES_BY_NID,
        "method": "GET",
        "url_template": "{env:IDENTITY_API_BASE}/nid/{nid}/phonenumbers",
        "result_path": "",
        "auth_type": "none",
    },
    {
        "slug": "nid_by_phone",
        "title": "NID from phone number",
        "category": "telecom",
        "description": "Resolve a phone number to its owner's national ID.",
        "kind": KIND_NID_BY_PHONE,
        "method": "GET",
        "url_template": "{env:IDENTITY_API_BASE}/phoneuser/{phone}",
        "result_path": "",
        "auth_type": "none",
    },
    {
        "slug": "upis_by_nid",
        "title": "Parcels (UPIs) from ID",
        "category": "land",
        "description": "Land parcels (UPI, land use, size) owned by a national ID. Requires a bearer token.",
        "kind": KIND_UPIS_BY_NID,
        "method": "GET",
        "url_template": "{env:LAND_API_BASE}/upis/",
        "query_template": {"idno": "{nid}", "idtypeid": "NID"},
        "result_path": "",
        "auth_type": "bearer",
        "auth_config": {
            "token_url": "{env:LAND_API_BASE}/authenticate",
            "token_method": "POST",
            "token_body": {
                "username": "{env:UPI_AUTH_USERNAME}",
                "password": "{env:UPI_AUTH_PASSWORD}",
            },
            "token_field": "token",
            "header": "Authorization",
            "scheme": "Bearer",
            "cache_ttl_s": 300,
        },
    },
    {
        "slug": "upi_owners",
        "title": "Owners from a UPI (reverse lookup)",
        "category": "land",
        "description": (
            "Reverse lookup: given a UPI, return the owning national ID(s). "
            "PLACEHOLDER — set the real URL/auth once this endpoint is built. "
            "Expected response: a list of NID strings, or objects with an 'nid' field."
        ),
        "kind": KIND_UPI_OWNERS,
        "method": "GET",
        "url_template": "{env:LAND_API_BASE}/upis/{upi}/owners",
        "result_path": "",
        "auth_type": "bearer",
        "auth_config": {
            "token_url": "{env:LAND_API_BASE}/authenticate",
            "token_method": "POST",
            "token_body": {
                "username": "{env:UPI_AUTH_USERNAME}",
                "password": "{env:UPI_AUTH_PASSWORD}",
            },
            "token_field": "token",
            "header": "Authorization",
            "scheme": "Bearer",
            "cache_ttl_s": 300,
        },
        "enabled": False,
    },
]


async def seed_defaults(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Create any missing seed endpoints for this operator. Returns the count
    created. Never overwrites an existing slug."""
    existing = {
        e.slug
        for e in (
            await session.execute(
                select(ExternalEndpoint).where(ExternalEndpoint.user_id == user_id)
            )
        ).scalars().all()
    }
    created = 0
    for spec in SEED_ENDPOINTS:
        if spec["slug"] in existing:
            continue
        session.add(ExternalEndpoint(user_id=user_id, **spec))
        created += 1
    if created:
        await session.flush()
    return created


async def list_endpoints(session: AsyncSession, user_id: uuid.UUID) -> list[ExternalEndpoint]:
    return list(
        (
            await session.execute(
                select(ExternalEndpoint)
                .where(ExternalEndpoint.user_id == user_id)
                .order_by(ExternalEndpoint.category, ExternalEndpoint.title)
            )
        ).scalars().all()
    )


async def get_by_slug(
    session: AsyncSession, user_id: uuid.UUID, slug: str
) -> ExternalEndpoint | None:
    return (
        await session.execute(
            select(ExternalEndpoint).where(
                ExternalEndpoint.user_id == user_id, ExternalEndpoint.slug == slug
            )
        )
    ).scalar_one_or_none()


async def get_by_kind(
    session: AsyncSession, user_id: uuid.UUID, kind: str, *, enabled_only: bool = True
) -> ExternalEndpoint | None:
    stmt = select(ExternalEndpoint).where(
        ExternalEndpoint.user_id == user_id, ExternalEndpoint.kind == kind
    )
    if enabled_only:
        stmt = stmt.where(ExternalEndpoint.enabled == True)  # noqa: E712
    return (await session.execute(stmt)).scalars().first()


def endpoint_out(e: ExternalEndpoint) -> dict:
    return {
        "id": str(e.id),
        "slug": e.slug,
        "title": e.title,
        "category": e.category,
        "description": e.description,
        "kind": e.kind,
        "method": e.method,
        "url_template": e.url_template,
        "query_template": e.query_template,
        "headers": e.headers,
        "body_template": e.body_template,
        "auth_type": e.auth_type,
        "auth_config": e.auth_config,
        "result_path": e.result_path,
        "image_keys": e.image_keys,
        "enabled": e.enabled,
        "rate_limit_per_min": e.rate_limit_per_min,
        "sample_response": e.sample_response,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
