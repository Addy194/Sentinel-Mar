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

## Implemented (iteration 4)
- **Official EEZ import**: `marine_regions.py` fetches Marine Regions WFS (eez by ISO3), repairs geometry (make_valid/unary_union/buffer(0), orient retry) for 2dsphere; `POST /jurisdictions/import-eez` (admin, 202 job) → zones flagged `official:true` + `mrgid`; re-resolves all cases. Zones page import panel + source labels.
- **Email settings**: admin-only `GET/PUT /auth/email-settings`, `POST /auth/email-settings/test`; DB settings override env; key masked. Users page `EmailSettings` panel (badge CONFIGURED / NOT CONFIGURED). **Real delivery NOT configured** — no Resend key supplied; forgot-password falls back to logged links.
- **Watchlist**: `routers/watchlist.py` (list any role; supervisor+ add/remove, severity whitelist, dup check); correlation enriches candidates with `watchlist{reason,severity}` and raises `watchlist_hit` alerts. `/watchlist` page, candidate badges, vessel-profile action.
- **Case timeline & sharing**: `routers/timeline.py` — `GET /cases/{id}/timeline` (JSON) + `/timeline.html`; supervisor+ `POST /cases/{id}/share` (sha256 token, 1–720 h expiry, note) → public `GET /api/share/{token}` read-only HTML (uses FRONTEND_URL), view counter, revoke. `CaseTimeline` tab in case detail.
- Tested: iteration_4 — 33/33 backend, all frontend flows pass, no issues.

## Implemented (iteration 5)
- **Scene imagery & evidence files**: `storage.py` (Emergent Object Storage, `EMERGENT_LLM_KEY`), chunked upload `POST /uploads/init` → `PUT /uploads/{id}/chunks/{i}` → `POST /uploads/{id}/complete` (≤50 MB; png/jpg/webp/tif/pdf/csv/txt/json/geojson; kinds sar_scene…other); `GET /cases/{id}/attachments`, `GET /attachments/{id}/download`, supervisor soft-delete. Images embedded in evidence PDF (section 8), attachments listed on timeline (JSON/HTML/share). Case detail "Files" tab (`Attachments.jsx`).
- **Alert email notifications**: `notifications.py` — every alert (high-confidence, watchlist, zone rule) emails active supervisors+admins (per-user `notify_alerts` opt-out on Users page) plus admin `alert_recipients`; `alerts_enabled` toggle in Email Settings. Outcome stored on `alert.notification` + `notifications` collection + audit `alert.notified`. **Delivery NOT configured** (no Resend key) → status `not_configured`.
- **Case comparison**: `GET /cases/compare/{a}/{b}` (geojson + candidates + shared_vessels); `/compare` page with split / overlay (side-tinted) maps, shared-vessel table, "Compare" button on case detail.
- **Zone alert rules**: `rules.py` + `routers/rules.py` — supervisor CRUD `/zone-rules` (zone_code, optional min_area_km2 / min_confidence, severity, primary_only, note), evaluated on case open, after correlation, and `POST /zone-rules/evaluate`; dedup per case+rule; `ZoneRules.jsx` panel on Zones page.
- Tested: iteration_5 — 29/29 backend, all frontend flows pass, no issues.

## Implemented (iteration 6)
- **Global satellite imagery**: `satellite.py` — Microsoft Planetary Computer STAC (open, no key): `GET /satellite/collections`, `POST /satellite/search` (bbox/date/collection, Sentinel-1 GRD + Sentinel-2 L2A w/ cloud filter), `GET /satellite/preview` (proxied quicklook, retry + cache + thumbnail fallback), `POST /satellite/register` (→ SentinelMar scene with STAC href/metadata; optional mock detect). NASA GIBS daily true-colour basemap (`GibsLayer.jsx`) on Scene Explorer and case map ("Satellite" toggle, acquisition date).
- **Scene Explorer** `/explorer`: world map with region presets, search current view, footprints + SAR/optical previews, register / register+mock-detect.
- **Live global AIS**: `ais_live.py` aisstream.io websocket collector (bboxes, PositionReport → existing dedup pipeline), `GET /ais/live/status`, admin `PUT /ais/live/settings`; `LiveAis` panel on Ingestion. **Key NOT provided → not configured.**
- Mock detector kept as labelled placeholder.
- Tested: iteration_6 — 19/19 backend, all frontend flows pass; preview retry/cache added after review.

## Implemented (iteration 7)
- **Tile performance**: lazy/visible-first tiles (`updateWhenIdle`, `keepBuffer:0`) on all maps + GIBS; Explorer previews load only when cards scroll into view; quicklooks cached in object storage (`scene.quicklook_path`).
- **Auto Scene Watch**: `scene_watches` (bbox, collection, auto_detect, last_polled); `.emergent/crons.yml` every 3 h → `POST /cron/scene-watch` (Bearer `WEBHOOK_CRON_SECRET`, idempotent on X-Webhook-Id) enqueues `scene_watch_poll` job; registers new passes, runs detector, raises `new_scene` alerts + email. Supervisor CRUD + "Poll now"; Explorer sidebar panel "Watch this view".
- **AIS density heatmap**: `GET /ais/density` server-side grid aggregation (zoom-sized bins, 60 s cache) → leaflet.heat layer on Explorer (24 h / 7 d / 90 d). *(Substituted for PostGIS/H3/MVT/Deck.gl to stay on the Mongo + Leaflet stack.)*
- **Scene overlay**: `GET /scenes/{id}/quicklook` + `/overlay` (EPSG:4326 bbox bounds) → Leaflet ImageOverlay on case map with toggle + opacity slider.
- **Dark-spot detector (EXPERIMENTAL)**: `detector.py` — OpenCV Gaussian + Otsu threshold on S1 VV quicklook, morphology, contour elongation ≥2.2, pixel→lon/lat affine via scene bbox; confidence ≤0.55, flags `lookalike_suspect`+`experimental_detector`; WebP crop thumbnail attached to each case. Replaces mock for STAC scenes (`detect_scene`); mock kept for imagery-less scenes.
- **Focus spill**: turf bbox of spill + top candidate, `flyToBounds`; marker label "TOP CANDIDATE — not confirmed" vs "RESPONSIBLE (analyst confirmed)" only when review_state confirmed for that MMSI.
- **Before/After**: `GET /cases/{id}/before-after` (STAC nearest scene before/after, S1 or S2, ±N days) → two synchronised Leaflet maps with ImageOverlay + spill polygon.
- **Events gallery** `/events`: `GET /spill-events` (offset/limit, compound indexes, filters start/end/min_conf/status/source/jurisdiction, thumb path) → react-window virtualized grid, URL-driven filters.
- Tested: iteration_7 — 20/20 backend, all frontend flows pass. Known cosmetic: console warning "<option> cannot be a child of <span>" (source not found in app code; likely injected/extension).

## Implemented (iteration 8)
- **Detector feedback**: `POST/GET /cases/{id}/detector-feedback` (TP/FP/uncertain + FP reason enum, versioned, audited, immutable), `GET /detector/precision` (TP/(TP+FP) per detector version, FP-reason breakdown, weekly, pending); Dashboard `DetectorPrecision` card (recharts donut); panel on case Review tab; PDF section under analyst decisions.
- **Live alert feed**: `events.py` in-process SSE broadcaster; `GET /alerts/stream?token=` (hello/alert/job events, keepalive), `GET /alerts/latest` polling fallback; `LiveFeedProvider` (EventSource → toast, header bell + unread count, critical red pulsing banner + Web-Audio siren for high severity, mute, auto-fallback to 10 s polling). Dashboard/case detail refresh on job completion. 10-minute inactivity auto-logout (`InactivityGuard`).
- **AIS gap filling** `gapfill.py`: gaps > `gap_threshold_min` (30) dead-reckoned from last SOG/COG blended to next fix (10-min synthetic points, `interpolated` flag); kinematically impossible transits (vs vessel-type max speed) → `spoof_suspect`, not interpolated; continuity uses real fixes only; spatial penalty ∝ gap length when closest approach is interpolated; dashed segments on map + tooltip; `params.fill_gaps` (default on).
- **Drift back-model** `drift.py` (lagrangian-backtrack-0.1.0): hourly reverse steps ≤72 h (3% wind + current), σ(t) from eddy diffusivity + 35% velocity uncertainty, 2σ origin envelope + most-likely window (from spill age); drift factor = exp(−z²/2) against envelope; layers `drift_envelope`/`drift_likely`/`drift_path` on map; PDF explains. Algorithm version **corr-1.1.0**.
- Tested: iteration_8 — 15/15 backend, all frontend flows pass.

## Implemented (iteration 9)
- **Petroleum asset search**: seeded gazetteer (~70: Indian basins/fields/ports, global fields, terminals, lanes, countries) + live EEZ zones; rapidfuzz search w/ name-substring boost (`GET /gazetteer/search`), admin CRUD; `AssetSearch` fly-to + footprint on Explorer and case map.
- **Historical spill archive**: 12 seeded precedents (`historical_spills`), `/archive` page (URL search), supervisor add/delete; `GET /cases/{id}/precedents` similarity (0.5 distance + 0.3 log-volume + 0.2 oil type) → Precedents drawer on Response tab.
- **Remediation playbook** (`playbook.py`, ADVISORY): volume by thickness class, coast distance via global-land-mask, depth class, sea state, drift → tactical boom/skimmer coords at down-drift edge; Tier 1/2/3 with dispersant/ISB/bioremediation suitability rules; Response tab + PDF section 9.
- **Prosecution export**: supervisor+ ZIP (PDF, case/spill/scene/AIS/results/reviews/audit/feedback/playbook JSON, attachments, MANIFEST.json SHA-256 + content hash), ledger `prosecution_exports`, audit; public `GET /verify/{hash}`, `POST /verify` (re-hash every file, detect tampering/repackaging), `/verify` page.
- Tested: iteration_9 — 28/29 backend (fuzzy ranking fixed after), all UI flows pass (testing agent fixed missing hasRole import in CaseDetail).

## Implemented (iteration 10)
- **Indian maritime territories**: Marine Regions import generalised to layers `eez` / `eez_24nm` / `eez_12nm` → zones IND-EEZ (eez), IND-CZ (contiguous), IND-TS (territorial); 12/24 NM bands keep inner rings; priority territorial < contiguous < eez; `zone_label` on jurisdictions. Case map: distinct styles (solid orange TS, dashed amber CZ, dotted blue EEZ) with per-kind toggles; Zones page labels + layer checkboxes + "India · all 3 zones" preset. Detection details show zone name (case chip, "also" chips); candidates tagged with `zone`/`zones` from closest AIS fix (`resolve_point_zones`).
- Tested: iteration_10 — 10/10 backend, all UI flows pass.

## Implemented (iteration 11 — code-quality pass)
- Login demo passwords removed from bundle → `REACT_APP_DEMO_PASSWORDS="analyst:…,supervisor:…"` in gitignored `frontend/.env` (quoted, `#` safe); buttons pre-fill email only when unset.
- Backend test credentials moved to `backend/tests/.env.test` (gitignored) via `tests/conftest.py` + `TEST_*_PASSWORD` env vars.
- Frontend: flat `eslint.config.js` (react + react-hooks) + `yarn lint`; 0 errors / 0 app warnings. Loaders wrapped in `useCallback` (CaseTimeline, DetectorFeedback, Archive, VesselProfile), context values memoised (AuthContext, LiveFeed), index keys → stable keys (Jobs, CsvUpload, CaseTimeline, CandidatesTable, DetectorPrecision), Recharts `minWidth/minHeight` fix, dead imports removed. pyflakes: no undefined names.
- Skipped by user decision: httpOnly-cookie auth, big refactors (run_correlation/build_pdf/build_playbook/CaseMap), `random`→`secrets` (deterministic seeded mock), lazy imports.
- Verified: 26/26 backend (iter 2 + 10 suites), login/dashboard/vessel-profile smoke screenshot.

## Implemented (iteration 11b — second review pass)
- Empty catch blocks → `console.warn` with context (LiveFeed ×2, AuthContext); EventSource cleanup nullifies ref.
- `CaseMap.jsx`: all inline `style`/`pathOptions` hoisted to module constants or pure helper fns; `colorFor`/`selectHandler`/`zoneFilter` in `useCallback`. `ZoneRules.jsx`: `activeZones`/`activeRules` via `useMemo`.
- Type hints on `db.py`, `jobs.py`, `gapfill.py`, `correlation_env.py`.
- Complexity trims (behaviour byte-identical vs HEAD, verified by running old/new side-by-side): `csv_ingest._row_to_position`, `marine_regions._fetch_or_fail/_zone_doc/_store_zone`, `detector._dark_mask/_contour_to_spot`, `gapfill._dead_reckon`.
- Tested: iteration_11 — backend 3/3 + 99/101 regression (2 known flaky: non-idempotent CSV dedup fixture; login lockout under parallel runs — passes alone), all UI flows pass, single SSE connection across navigation.
- Known cosmetic: "<span> cannot be a child of <option>" console warning (pre-existing, source not in app code).

## Backlog (prioritized)
- P1: Resend + aisstream keys; U-Net SAR segmentation; OpenDrift forward drift; socio-economic vulnerability (Overpass POIs); WhatsApp citizen reports; i18n (Hindi/Tamil/Marathi); outbound port-authority webhooks (HMAC); ErrorBoundary around CaseDetail; exponential lockout backoff.
- P2: Additional met/ocean providers, replay testing harness, observability/metrics, SAR segmentation model once labeled data exists, separate worker process (Celery/Redis).

## Known limitations
- Mock detector is a placeholder (MOCKED by design). Drift model is a simple 3%-wind + current linear back-projection. No encryption/RBAC yet.
