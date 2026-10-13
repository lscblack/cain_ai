"""Aggregate everything KAI knows about a person/identifier from the local corpus.

Given a name (or a phone/email/username), pull together the faces, the pages that
mention it, and every contact identifier co-located with it — the "everything that
might belong to them" dossier. Computed live from the corpus, so it keeps getting
richer as crawls land. Observations only, never asserted identity.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.face import Face
from app.database.models.source import Page
from app.intelligence.detect import QueryType, detect_query_type
from app.intelligence.face.crops import has_crop
from app.intelligence.face.describe import describe_face

_MAX_FACES = 24
_MAX_PAGES = 40


async def gather_dossier(
    session: AsyncSession, term: str, *, public: bool = False, as_name: bool = False
) -> dict:
    """Everything linked to `term`: faces, pages, and aggregated contacts.

    as_name=True forces person-name handling (face names + page text) even for a
    single word that would otherwise be read as a username — used by name investigations.
    """
    term = (term or "").strip()
    crop_base = "/intelligence/face/public/crop/" if public else "/intelligence/face/crop/"
    det = detect_query_type(term)
    needle = det.normalized or term
    name_mode = as_name or det.type == QueryType.UNKNOWN

    faces_out: list[dict] = []
    emails: set[str] = set()
    phones: set[str] = set()
    usernames: set[str] = set()
    titles: set[str] = set()
    orgs: set[str] = set()
    locations: set[str] = set()
    social: set[str] = set()
    pages_out: list[dict] = []

    # 1) Faces that name this person (names/free text are detected as UNKNOWN).
    #    Substring match against any name in extra.names (case-insensitive) so
    #    "Paul Kagame" also hits a stored "Perezida Paul Kagame".
    words = [w for w in term.split() if len(w) >= 2]
    if name_mode and words:
        # Match a face whose extra.names contains ALL of the query words, in any
        # order — so "alain muhirwa michael" also hits "Michael Alain Muhirwa".
        wconds = " AND ".join(f"n ILIKE :w{i}" for i in range(len(words)))
        params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
        params["lim"] = _MAX_FACES
        ids = (
            await session.execute(
                text(
                    "SELECT id FROM faces f "
                    f"WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(f.extra->'names') n WHERE {wconds}) "
                    "ORDER BY f.quality DESC LIMIT :lim"
                ),
                params,
            )
        ).scalars().all()
        face_rows = (
            (await session.execute(select(Face).where(Face.id.in_(ids)))).scalars().all()
            if ids else []
        )
        for fa in face_rows:
            ex = fa.extra or {}
            for e in ex.get("emails") or []:
                emails.add(e)
            for p in ex.get("phones") or []:
                phones.add(p)
            for u in ex.get("usernames") or []:
                usernames.add(u)
            for t in ex.get("titles") or []:
                titles.add(t)
            for o in ex.get("orgs") or []:
                orgs.add(o)
            for lc in ex.get("locations") or []:
                locations.add(lc)
            if has_crop(str(fa.id)):
                faces_out.append({
                    "face_id": str(fa.id),
                    "crop_url": f"{crop_base}{fa.id}",
                    "source_url": fa.source_url,
                    "description": describe_face(ex, fa.source_url),
                })

    # 2) Pages that mention the term (name in title/description) or carry the
    #    identifier (phone/email/username co-located).
    conds = []
    if not name_mode and det.type == QueryType.EMAIL:
        conds.append(Page.emails.contains([needle]))
    elif not name_mode and det.type == QueryType.PHONE:
        conds.append(Page.phones.contains([needle]))
    elif not name_mode and det.type == QueryType.USERNAME:
        conds.append(Page.usernames.contains([needle.lstrip("@")]))
    else:
        # all query words present in the title, OR all in the description (any order)
        w = words or [term]
        conds = [
            and_(*[Page.title.ilike(f"%{x}%") for x in w]),
            and_(*[Page.description.ilike(f"%{x}%") for x in w]),
        ]
    pages = (
        await session.execute(select(Page).where(or_(*conds)).limit(_MAX_PAGES))
    ).scalars().all()
    for p in pages:
        for e in p.emails or []:
            emails.add(e)
        for ph in p.phones or []:
            phones.add(ph)
        for u in p.usernames or []:
            usernames.add(u)
        pm = p.meta or {}
        for t in pm.get("titles") or []:
            titles.add(t)
        for o in pm.get("orgs") or []:
            orgs.add(o)
        for lc in pm.get("locations") or []:
            locations.add(lc)
        for so in pm.get("social") or []:
            social.add(so)
        pages_out.append({
            "url": p.url,
            "title": p.title,
            "description": p.description,
            "thumbnail": pm.get("thumbnail"),
            "source": pm.get("source"),
            "emails": p.emails or [],
            "phones": p.phones or [],
            "usernames": p.usernames or [],
        })

    return {
        "term": term,
        "detected_type": det.type.value,
        "faces": faces_out,
        "pages": pages_out,
        "phones": sorted(phones),
        "emails": sorted(emails),
        "usernames": sorted(usernames),
        "titles": sorted(titles),
        "orgs": sorted(orgs),
        "locations": sorted(locations),
        "social": sorted(social),
        "counts": {
            "faces": len(faces_out),
            "pages": len(pages_out),
            "phones": len(phones),
            "emails": len(emails),
            "usernames": len(usernames),
            "titles": len(titles),
            "orgs": len(orgs),
            "locations": len(locations),
        },
    }
