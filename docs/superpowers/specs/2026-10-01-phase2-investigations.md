# KAI — Phase 2: Investigation / Case System (Design + Plan)

**Date:** 2026-10-01 · **Status:** building · **Depends on:** Phase 1

## Purpose

Everything in KAI revolves around an **Investigation** (a case). Phase 2 turns
the Phase-1 contract stubs (`EntityContract`/`EvidenceContract`/
`RelationshipContract`) into concrete, persisted tables and exposes CRUD so the
operator can create a case and attach entities, evidence, and observed
relationships. This is the backbone every later OSINT module writes into.

## Core principle (carried from spec)

Evidence always carries provenance (`source_url` + `collected_at`).
Relationships are **observed**, never asserted as identity — each edge stores
`source_url`, `observed_at`, `rel_type`, optional `confidence`, and an
`evidence_excerpt`. No endpoint ever merges two entities into "the same person".

## Data model (new tables, Alembic migration 0002)

```
investigations
  id uuid pk, code text unique (CASE-YYYY-NNNN), name text, description text|null,
  status text (open|archived) default open, created_by uuid|null (users.id),
  created_at, updated_at

entities
  id uuid pk, investigation_id uuid fk->investigations (cascade),
  type text (face|phone|email|username|domain|url|image|organization|location|
             document|vehicle|aircraft|vessel),
  value text, label text|null, metadata jsonb default {}, created_at, updated_at
  index (investigation_id, type)

evidence
  id uuid pk, investigation_id uuid fk (cascade), entity_id uuid fk->entities|null,
  type text (same enum), source_url text NOT NULL, collected_at timestamptz NOT NULL,
  first_seen timestamptz|null, last_seen timestamptz|null,
  hash text|null, confidence float|null, band text|null (confidence band enum),
  raw_metadata jsonb default {}, processed_metadata jsonb default {},
  created_at, updated_at
  index (investigation_id), (entity_id)

relationships
  id uuid pk, investigation_id uuid fk (cascade),
  source_entity_id uuid fk->entities, target_entity_id uuid fk->entities,
  rel_type text, source_url text NOT NULL, observed_at timestamptz NOT NULL,
  confidence float|null, evidence_excerpt text|null, created_at, updated_at
  index (investigation_id)
```

## API (all require operator auth; prefix /investigations)

- `POST /investigations` {name, description?} → creates with auto `code`
  (CASE-<year>-<zero-padded sequence>). 201.
- `GET /investigations` → list (newest first) with counts.
- `GET /investigations/{id}` → detail incl. entity/evidence/relationship counts.
- `PATCH /investigations/{id}` {name?, description?, status?}.
- `DELETE /investigations/{id}` → cascade.
- `POST /investigations/{id}/entities` {type, value, label?, metadata?} → 201.
- `GET /investigations/{id}/entities`
- `POST /investigations/{id}/evidence` {type, source_url, collected_at?, entity_id?,
  first_seen?, last_seen?, hash?, confidence?, band?, raw_metadata?,
  processed_metadata?} → validates source_url is http(s) via SSRF-safe parse
  (scheme/host only, no network fetch); collected_at defaults to now. 201.
- `GET /investigations/{id}/evidence`
- `POST /investigations/{id}/relationships` {source_entity_id, target_entity_id,
  rel_type, source_url, observed_at?, confidence?, evidence_excerpt?} →
  both entities must belong to the investigation; 201.
- `GET /investigations/{id}/graph` → {nodes:[entities], edges:[relationships]}
  for the Phase-7/16 graph UI.

Audit: investigation.create / .delete recorded.

## Files

- models: `investigation.py`, `entity.py`, `evidence.py`, `relationship.py`
  (+ register in models/__init__.py)
- repositories: `investigation_repo.py` (incl. next-code sequence), `entity_repo.py`,
  `evidence_repo.py`, `relationship_repo.py`
- schemas: `investigation.py` (In/Out + nested), `graph.py`
- api: `investigations.py` (router), mounted in main
- service: `code.py` (generate_case_code) — pure, tested
- migration: `0002_investigations.py`
- tests: `test_case_code.py`, `test_investigations_api.py`, `test_graph.py`
- frontend: `pages/Investigations.tsx` (list + create), `pages/Investigation.tsx`
  (detail: entities/evidence/relationship tabs), `lib/investigations.ts`,
  routing in App (react-router), nav wiring.

## Tests (TDD, Review Focus)

- Case code: first code of a year = CASE-2026-0001; increments; year rollover.
- Create/list/get/patch/delete investigation; 404 on missing; auth required (401).
- Add entity; add evidence with provenance; evidence rejects non-http(s) source_url (422).
- Relationship rejects entity not in the investigation (400/422).
- Graph returns nodes+edges for the case only (isolation between cases).
- Deleting an investigation cascades entities/evidence/relationships.

## Done when

All Phase 2 tests pass; migration applies; frontend lists/creates an
investigation and shows its detail with live counts; full suite still green.
