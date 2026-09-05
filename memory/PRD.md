# SentinelMar — Maritime Oil-Spill Detection & Vessel Correlation (PRD)

## Original problem statement
Web-based decision-support system for maritime authorities that ingests satellite-derived spill observations and AIS tracks, detects spatial-temporal overlap, and produces auditable ranked vessel candidates — not legal conclusions. Provider-neutral ingestion (Sentinel-1 first), normalized spill/AIS schemas, configurable corridor/time-window correlation, drift-back uncertainty (wind/current or degraded), transparent scoring (spatial, time gap, track continuity, heading, drift plausibility, AIS reliability), evidence bundles, GeoJSON, confidence bands, processing logs, analyst review states, alerts, immutable decisions. Statuses: possible / probable / insufficient_evidence / analyst_confirmed / indeterminate. Reproducible, auditable results.

## User choices
- No auth for MVP (open API) · Leaflet + OSM tiles · external polygons + mock detector · seeded demo data · in-process asyncio job queue with MongoDB `jobs` collection + polling.

## Architecture
- Backend `/app/backend`: FastAPI (`server.py`), `db.py` (Motor, indexes: 2dsphere on AIS/spill/scene, time + unique dedup), `models.py` (Pydantic contracts + vocabularies), `geo.py` (shapely validation, haversine, drift helpers), `correlation.py` (`corr-1.0.0` deterministic scoring engine), `services.py` (ingestion, dedup/quality checks, mock detector, correlate job handler + alerting), `jobs.py` (async queue, retries ×3, job logs), `seed.py`, `routers/{ingest,cases,system}.py`.
- Frontend `/app/frontend/src`: React 19 + react-leaflet 5; pages Dashboard, CaseDetail (map + candidates + review + evidence + log), Ingest, Jobs & Alerts.
- Collections: scenes, spill_observations (raw_input preserved), cases (mutable state), correlation_results (immutable, versioned, input_hash), reviews (immutable), audit_events (separate), jobs, alerts, ais_positions.

## API (all under /api)
POST/GET scenes, POST scenes/{id}/detect (mock), POST/GET spill-observations, POST ais/positions (dedup + flags), GET ais/positions, GET ais/vessels, GET cases, GET cases/{id}, POST cases/{id}/correlate (202 job; sync=true option), GET cases/{id}/candidates, POST cases/{id}/review, GET cases/{id}/reviews, GET cases/{id}/evidence, GET cases/{id}/geojson, GET jobs, GET jobs/{id}, GET alerts, POST alerts/{id}/ack, GET audit, GET config/defaults, GET stats, POST seed.

## Implemented (2026-06 — MVP)
- Phases 1–4 of the stated plan: schemas/vocabulary, ingestion + validation + dedup + audit, baseline correlation with explainable factors and caps (severe spill flags, low detection confidence, low AIS reliability, multiple-vessel ambiguity, post-acquisition-only tracks), drift back-projection (3% wind + current) or `degraded`, GeoJSON export, high-confidence alerts, immutable analyst review preserving prior automated results, mock SAR detector as replaceable module.
- Tested: iteration_1 — 20/20 backend tests pass; frontend flows verified. Fixed testid forwarding on map, fragment keys.

## Implemented (iteration 2)
- **Authority accounts**: JWT (PyJWT, bcrypt) email/password auth, roles analyst < supervisor < admin (`auth.py`, `routers/auth.py`). All `/api/*` endpoints protected; actor identity (email/role) written on every audit event, review, job, alert ack and export. Brute-force lockout (5 fails / 15 min, X-Forwarded-For aware). Admin user management (`/api/users` CRUD, `/users` page). Supervisor-only: alert ack, `POST /cases/{id}/override`. Seeded accounts in `/app/memory/test_credentials.md`; admin = workspace owner email.
- **Evidence PDF**: `GET /api/cases/{id}/evidence.pdf` (reportlab + matplotlib map snapshot; case summary, sources, environment, ranked candidates + factor tables, processing log, versions, decisions, audit). Audited as `evidence.exported`.
- **Live weather drift**: `weather.py` Open-Meteo (ERA5 archive / forecast wind 10 m; Copernicus Marine surface current). `POST /cases/{id}/environment/fetch` persists wind/current + provenance on the spill observation; `correlate` accepts `fetch_environment: true`. UI: "Live weather" button + environment summary + param checkbox.
- **Time scrubber**: map slider/play replaying AIS tracks (interpolated heads, AIS-gap dashed markers, spill dimmed before satellite pass); GeoJSON tracks now carry timestamps/sog/cog.
- Tested: iteration_2 — 16/16 backend, all frontend flows pass. Fixed lockout identifier, scrubber setState warning, users loading state.

## Implemented (iteration 3)
- **Password reset**: `POST /auth/forgot-password` (generic response, no enumeration) → single-use sha256-hashed token, 60 min expiry; `POST /auth/reset-password`; Resend email via `emailer.py` (RESEND_API_KEY empty → link logged server-side and shown to admins at `GET /auth/reset-requests` / Users page "copy link"). Clears lockouts on reset. Pages `/forgot-password`, `/reset-password`.
- **CSV AIS upload**: `csv_ingest.py` header alias auto-detection, delimiter sniffing, timestamp parsing (ISO/epoch/common formats); `POST /ais/csv/preview` + `POST /ais/csv/ingest` (multipart, optional mapping JSON, row-level errors, dedup via existing pipeline). Drag-and-drop `CsvUpload` component with mapping selects on Ingestion page.
- **Jurisdiction zones**: `jurisdictions` collection (2dsphere), seeded simplified North Sea EEZs + Rotterdam port-state box (demo, not official); admin CRUD `/jurisdictions`, `/jurisdictions/geojson`, `resolve-all`, `/cases/{id}/jurisdiction/resolve`. Cases get `jurisdictions[]` + `primary_jurisdiction` (centroid containment, port_state > territorial > eez) on creation; shown on dashboard, case chip, case map layer, PDF. `/zones` page with map + admin form.
- **Vessel history**: `GET /vessels/{mmsi}/profile` (appearances from latest result per case, decisions naming the vessel, AIS coverage summary, disclaimer); `/vessels/:mmsi` page linked from candidate rows and vessel list.
- Tested: iteration_3 — 23/23 backend, all frontend flows pass, no issues.

## Backlog (prioritized)
- P1: Add RESEND_API_KEY + verified sender to enable real reset emails; real object storage for scene imagery/evidence artifacts; retention policies; rate limiting; official EEZ boundary import (Marine Regions GeoJSON).
- P2: Additional met/ocean providers, replay testing harness, observability/metrics, SAR segmentation model once labeled data exists, separate worker process (Celery/Redis).

## Known limitations
- Mock detector is a placeholder (MOCKED by design). Drift model is a simple 3%-wind + current linear back-projection. No encryption/RBAC yet.
