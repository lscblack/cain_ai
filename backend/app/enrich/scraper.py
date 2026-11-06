"""The enrichment scraper engine.

Two seed flows, both rate-limited and idempotent:

* ``phone_seed`` — start from phone numbers: phone → NID → citizen record (+ face
  photo) → that person's phones → that person's parcels (UPIs).
* ``csv_upi`` — start from a UPI transaction CSV: upsert each parcel + its
  transaction, reverse-look up the owning NID(s), then enrich each owner exactly
  like the phone flow (person + photo + phones), recording ownership changes as
  an ordered history.

Deduplication: an unchanged person (same content hash) is skipped (bio + face
not rewritten) but its phones and ownership links are still ensured. A parcel
whose current owner is unchanged is left alone; a changed owner closes the prior
ownership record and opens a new current one, preserving the chain.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.enrich import (
    KIND_NID_BY_PHONE,
    KIND_PERSON_BY_NID,
    KIND_PHONES_BY_NID,
    KIND_UPI_OWNERS,
    KIND_UPIS_BY_NID,
    ExternalEndpoint,
    Parcel,
    ParcelOwnership,
    Person,
    PhoneNumber,
    ScrapeJob,
)
from app.enrich import endpoints as ep_mod
from app.enrich.client import call_endpoint, dotted_get
from app.enrich.faces_link import index_person_photo


# ───────────────────────── rate limiter ─────────────────────────────────── #
class RateLimiter:
    """Allow at most ``per_min`` acquisitions in any rolling 60s window."""

    def __init__(self, per_min: int) -> None:
        self.per_min = max(1, int(per_min or 10))
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
            if len(self._calls) >= self.per_min:
                wait = 60 - (now - self._calls[0]) + 0.02
                if wait > 0:
                    await asyncio.sleep(wait)
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
            self._calls.append(time.monotonic())


# ───────────────────────── job control (pause/cancel) ───────────────────── #
class JobControl:
    def __init__(self) -> None:
        self._cancel = asyncio.Event()
        self._pause = asyncio.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    async def gate(self) -> None:
        while self._pause.is_set() and not self._cancel.is_set():
            await asyncio.sleep(0.5)


# ───────────────────────── small helpers ────────────────────────────────── #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_nid(value: str | None) -> str:
    """Collapse a NID to its digits (e.g. '1 2004 8 0002578 1 50' → …)."""
    return re.sub(r"\D", "", str(value or ""))


def _as_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


class Ctx:
    """Shared context for one job run."""

    def __init__(self, session: AsyncSession, job: ScrapeJob, control: JobControl,
                 endpoints: dict[str, ExternalEndpoint]) -> None:
        self.session = session
        self.job = job
        self.control = control
        self.endpoints = endpoints
        self.limiter = RateLimiter(job.rate_limit_per_min)

    def bump(self, key: str, n: int = 1) -> None:
        self.job.stats[key] = int(self.job.stats.get(key, 0)) + n
        flag_modified(self.job, "stats")

    def log(self, msg: str, level: str = "info") -> None:
        self.job.last_message = msg[:500]
        entry = {"t": _now_iso(), "level": level, "msg": msg[:500]}
        self.job.log = (list(self.job.log or []) + [entry])[-200:]
        flag_modified(self.job, "log")

    async def persist(self) -> None:
        self.session.add(self.job)
        await self.session.commit()

    async def call(self, kind: str, params: dict):
        """Rate-limited call to the endpoint registered for ``kind``."""
        endpoint = self.endpoints.get(kind)
        if endpoint is None:
            return None
        await self.limiter.acquire()
        self.bump("api_calls")
        res = await call_endpoint(endpoint, params)
        if not res.ok:
            self.bump("errors")
            self.log(f"{kind} failed for {params}: {res.error}", "error")
            return None
        return res


# ───────────────────────── upserts ──────────────────────────────────────── #
def _person_fields(cit: dict) -> dict:
    """Map a GetCitizenResult payload to Person columns."""
    g = lambda *keys: next((cit[k] for k in keys if cit.get(k) not in (None, "")), None)  # noqa: E731
    return {
        "surnames": g("Surnames"),
        "forenames": g("ForeName", "ForeNames"),
        "father_names": g("FatherNames"),
        "mother_names": g("MotherNames"),
        "sex": g("Sex"),
        "date_of_birth": g("DateOfBirth"),
        "civil_status": g("CivilStatus"),
        "marital_status": g("MaritalStatus"),
        "nationality": g("Nationality"),
        "province": g("Province"),
        "district": g("District"),
        "sector": g("Sector"),
        "cell": g("Cell"),
        "village": g("Village"),
        "village_id": g("VillageId"),
        "place_of_birth": g("PlaceOfBirth"),
        "country_of_birth": g("CountryOfBirth", "BirthCountry"),
        "country_of_domicile": g("CountryOfDomicile"),
        "document_number": g("DocumentNumber"),
        "application_number": g("ApplicationNumber"),
        "issue_number": g("IssueNumber"),
        "date_of_issue": g("DateOfIssue"),
        "date_of_expiry": g("DateOfExpiry"),
    }


def _content_hash(fields: dict) -> str:
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def _get_person(session: AsyncSession, nid: str) -> Person | None:
    return (
        await session.execute(select(Person).where(Person.nid == nid))
    ).scalar_one_or_none()


async def upsert_person(ctx: Ctx, nid: str, cit: dict, images: dict) -> tuple[Person, str]:
    """Create/update a Person from a citizen payload. Returns (person, status)
    where status ∈ {added, updated, skipped}."""
    fields = _person_fields(cit)
    chash = _content_hash(fields)
    person = await _get_person(ctx.session, nid)
    status = "added"
    if person is None:
        person = Person(nid=nid, raw=cit, content_hash=chash,
                        source_endpoint=KIND_PERSON_BY_NID, last_scraped_at=_now_iso(), **fields)
        ctx.session.add(person)
        await ctx.session.flush()
        ctx.bump("persons_added")
    elif person.content_hash != chash:
        for k, v in fields.items():
            setattr(person, k, v)
        person.raw = cit
        person.content_hash = chash
        person.last_scraped_at = _now_iso()
        ctx.session.add(person)
        await ctx.session.flush()
        status = "updated"
        ctx.bump("persons_updated")
    else:
        person.last_scraped_at = _now_iso()
        ctx.session.add(person)
        status = "skipped"
        ctx.bump("persons_skipped")

    # Index / refresh the NID face only when the record is new/changed or has no
    # face yet (avoids re-embedding the same photo every run).
    photo = None
    for key in ("Photo", "GetCitizenResult.Photo"):
        photo = photo or (images.get(key) or dotted_get(cit, key.split(".")[-1]))
    if photo and (status != "skipped" or person.photo_face_id is None):
        face_id = await index_person_photo(ctx.session, person=person, photo_b64=photo)
        if face_id is not None:
            person.photo_face_id = face_id
            ctx.session.add(person)
            await ctx.session.flush()
            ctx.bump("faces_indexed")
    return person, status


async def upsert_phone(ctx: Ctx, msisdn: str, nid: str | None,
                       mno: str | None, service_period: str | None, source: str) -> bool:
    msisdn = str(msisdn or "").strip()
    if not msisdn:
        return False
    existing = (
        await ctx.session.execute(
            select(PhoneNumber).where(PhoneNumber.msisdn == msisdn, PhoneNumber.nid == nid)
        )
    ).scalar_one_or_none()
    if existing is not None:
        changed = False
        if mno and not existing.mno:
            existing.mno = mno; changed = True
        if service_period and not existing.service_period:
            existing.service_period = service_period; changed = True
        if changed:
            ctx.session.add(existing)
        return False
    ctx.session.add(PhoneNumber(msisdn=msisdn, nid=nid, mno=mno,
                                service_period=service_period, source=source))
    await ctx.session.flush()
    ctx.bump("phones_added")
    return True


async def upsert_parcel(ctx: Ctx, upi: str, attrs: dict, source: str) -> Parcel:
    upi = str(upi).strip()
    parcel = (
        await ctx.session.execute(select(Parcel).where(Parcel.upi == upi))
    ).scalar_one_or_none()
    if parcel is None:
        parcel = Parcel(upi=upi, source_endpoint=source, last_scraped_at=_now_iso(),
                        **{k: attrs.get(k) for k in
                           ("province", "district", "sector", "cell", "village", "land_use", "size")})
        ctx.session.add(parcel)
        await ctx.session.flush()
        ctx.bump("parcels_added")
    else:
        for k in ("province", "district", "sector", "cell", "village", "land_use", "size"):
            if attrs.get(k) not in (None, "") and getattr(parcel, k) in (None, ""):
                setattr(parcel, k, attrs.get(k))
        parcel.last_scraped_at = _now_iso()
        ctx.session.add(parcel)
    return parcel


async def record_transaction(ctx: Ctx, upi: str, row: dict) -> None:
    """Record a CSV transaction row as a (ownerless) ownership/transaction event."""
    chash = hashlib.sha256(
        f"{upi}|{row.get('start_date')}|{row.get('sale_price')}|{row.get('transaction_type')}".encode()
    ).hexdigest()
    exists = (
        await ctx.session.execute(
            select(ParcelOwnership).where(
                ParcelOwnership.upi == upi,
                ParcelOwnership.owner_nid.is_(None),
                ParcelOwnership.content_hash == chash,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return
    ctx.session.add(ParcelOwnership(
        upi=upi, owner_nid=None, is_current=False,
        start_date=row.get("start_date"), transaction_type=row.get("transaction_type"),
        sale_price=row.get("sale_price"), size=row.get("size"),
        source="csv", content_hash=chash,
    ))
    await ctx.session.flush()
    ctx.bump("transactions_added")


async def set_current_owner(ctx: Ctx, upi: str, owner_nid: str,
                            *, source: str, start_date: str | None = None) -> None:
    """Make ``owner_nid`` the current owner of ``upi``, closing any prior current
    owner (preserving the ownership chain). No-op if already current."""
    current = (
        await ctx.session.execute(
            select(ParcelOwnership).where(
                ParcelOwnership.upi == upi, ParcelOwnership.is_current == True  # noqa: E712
            )
        )
    ).scalars().all()
    if any(o.owner_nid == owner_nid for o in current):
        return  # owner unchanged → skip
    for o in current:
        o.is_current = False
        o.end_date = _now_iso()
        ctx.session.add(o)
    chash = hashlib.sha256(f"{upi}|{owner_nid}|current".encode()).hexdigest()
    ctx.session.add(ParcelOwnership(
        upi=upi, owner_nid=owner_nid, is_current=True,
        start_date=start_date or _now_iso(), source=source, content_hash=chash,
    ))
    await ctx.session.flush()
    # update the parcel pointer
    parcel = (await ctx.session.execute(select(Parcel).where(Parcel.upi == upi))).scalar_one_or_none()
    if parcel is not None:
        parcel.current_owner_nid = owner_nid
        ctx.session.add(parcel)
    if current:
        ctx.bump("ownership_changes")
    else:
        ctx.bump("ownership_new")


# ───────────────────────── enrich one NID ───────────────────────────────── #
async def enrich_nid(ctx: Ctx, nid: str, *, fetch_parcels: bool = True) -> Person | None:
    """Pull person + phones (+ optionally their parcels) for a NID."""
    nid = normalize_nid(nid)
    if not nid:
        return None

    pres = await ctx.call(KIND_PERSON_BY_NID, {"nid": nid})
    if pres is None or not isinstance(pres.data, dict):
        return None
    person, _status = await upsert_person(ctx, nid, pres.data, pres.images)

    # phones
    phres = await ctx.call(KIND_PHONES_BY_NID, {"nid": nid})
    if phres is not None and isinstance(phres.data, list):
        for item in phres.data:
            if isinstance(item, dict):
                await upsert_phone(ctx, item.get("msidn") or item.get("msisdn") or "",
                                   nid, item.get("mno"), item.get("serviceperiod"),
                                   source=KIND_PHONES_BY_NID)

    # parcels owned by this person
    if fetch_parcels:
        upres = await ctx.call(KIND_UPIS_BY_NID, {"nid": nid})
        if upres is not None and isinstance(upres.data, list):
            for item in upres.data:
                if not isinstance(item, dict):
                    continue
                upi = item.get("upi")
                if not upi:
                    continue
                await upsert_parcel(ctx, upi, {
                    "land_use": item.get("landuse") or item.get("land_use"),
                    "size": _as_float(item.get("size")),
                }, source=KIND_UPIS_BY_NID)
                await set_current_owner(ctx, upi, nid, source=KIND_UPIS_BY_NID)
    return person


# ───────────────────────── flows ────────────────────────────────────────── #
async def run_phone_seed(ctx: Ctx) -> None:
    phones = [str(p).strip() for p in ctx.job.params.get("phones", []) if str(p).strip()]
    ctx.job.total = len(phones)
    await ctx.persist()
    for phone in phones:
        if ctx.control.cancelled:
            return
        await ctx.control.gate()
        try:
            res = await ctx.call(KIND_NID_BY_PHONE, {"phone": phone})
            nid = None
            if res is not None:
                nid = res.data.get("result") if isinstance(res.data, dict) else res.data
                nid = normalize_nid(nid) if nid else None
            if nid:
                # make sure the seed phone is linked even if the person's phone
                # list is fetched separately
                await enrich_nid(ctx, nid)
                await upsert_phone(ctx, phone, nid, None, None, source=KIND_NID_BY_PHONE)
                ctx.log(f"phone {phone} → NID {nid} enriched")
            else:
                ctx.log(f"phone {phone}: no NID found", "warn")
        except Exception as exc:  # noqa: BLE001
            ctx.bump("errors")
            ctx.log(f"phone {phone} error: {exc}", "error")
        ctx.job.processed += 1
        await ctx.persist()


async def run_csv_upi(ctx: Ctx) -> None:
    rows = ctx.job.params.get("rows", [])
    ctx.job.total = len(rows)
    expand = bool(ctx.job.params.get("expand_owner_parcels", False))
    await ctx.persist()
    for row in rows:
        if ctx.control.cancelled:
            return
        await ctx.control.gate()
        upi = str(row.get("upi") or "").strip()
        if not upi:
            ctx.job.processed += 1
            continue
        try:
            await upsert_parcel(ctx, upi, row, source="csv")
            await record_transaction(ctx, upi, row)

            owners_res = await ctx.call(KIND_UPI_OWNERS, {"upi": upi})
            owner_nids: list[str] = []
            if owners_res is not None:
                payload = owners_res.data
                items = payload if isinstance(payload, list) else [payload]
                for it in items:
                    if isinstance(it, str):
                        owner_nids.append(normalize_nid(it))
                    elif isinstance(it, dict):
                        owner_nids.append(normalize_nid(
                            it.get("nid") or it.get("idno") or it.get("owner") or ""))
            owner_nids = [n for n in owner_nids if n]

            for nid in owner_nids:
                if ctx.control.cancelled:
                    return
                await enrich_nid(ctx, nid, fetch_parcels=expand)
                await set_current_owner(ctx, upi, nid, source=KIND_UPI_OWNERS,
                                        start_date=row.get("start_date"))
            if owner_nids:
                ctx.log(f"UPI {upi}: {len(owner_nids)} owner(s) enriched")
            else:
                ctx.log(f"UPI {upi}: no owners returned (is the upi_owners endpoint built/enabled?)", "warn")
        except Exception as exc:  # noqa: BLE001
            ctx.bump("errors")
            ctx.log(f"UPI {upi} error: {exc}", "error")
        ctx.job.processed += 1
        await ctx.persist()


async def run_job(session: AsyncSession, job: ScrapeJob, control: JobControl,
                  user_id: uuid.UUID) -> None:
    """Dispatch a job to its flow. Loads the operator's endpoints by kind."""
    eps = {e.kind: e for e in await ep_mod.list_endpoints(session, user_id) if e.enabled}
    ctx = Ctx(session, job, control, eps)
    if job.kind == "phone_seed":
        await run_phone_seed(ctx)
    elif job.kind == "csv_upi":
        await run_csv_upi(ctx)
    elif job.kind == "nid_seed":
        nids = [normalize_nid(n) for n in job.params.get("nids", [])]
        job.total = len([n for n in nids if n])
        await ctx.persist()
        for nid in nids:
            if control.cancelled:
                return
            await control.gate()
            if nid:
                try:
                    await enrich_nid(ctx, nid)
                    ctx.log(f"NID {nid} enriched")
                except Exception as exc:  # noqa: BLE001
                    ctx.bump("errors")
                    ctx.log(f"NID {nid} error: {exc}", "error")
            job.processed += 1
            await ctx.persist()
    else:
        raise ValueError(f"unknown job kind: {job.kind}")
