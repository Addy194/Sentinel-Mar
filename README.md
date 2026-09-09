# Sentinel-Mar

Sentinel-Mar is a marine intelligence prototype for detecting and investigating possible oil-spill events using Sentinel-1 SAR imagery, AIS vessel tracks, drift modelling, and explainable correlation.

## Demo-first, reproducible setup

```bash
cp .env.example .env
docker compose up --build
```

The demo is designed to run without paid external keys. AIS replay and email notifications use explicit demo adapters when live credentials are absent.

## Important model disclosure

The bundled `sar_spill_pixel_v1` artifact is a **prototype trained on synthetic SAR-like data for demo/integration validation**; it is not a field-validated oil-spill model. Outputs are labelled **ML candidates requiring analyst review**. Real deployment requires training and validation on representative Sentinel-1 oil-spill and look-alike datasets.

## Architecture

- React frontend for map/case review
- FastAPI backend
- MongoDB for persistent case/state storage
- Redis-backed durable job queue with retry/lease semantics
- Sentinel-1 STAC asset ingestion with VV/VH support and preview fallback
- SAR candidate detector with versioned model metadata
- AIS live integration plus deterministic demo replay
- Drift and vessel/spill correlation engines
- Demo email outbox plus optional Resend integration

See `docs/ARCHITECTURE.md`, `docs/QUICKSTART.md`, `docs/DEMO.md`, and `docs/MODEL_CARD.md`.

## Environment

Copy `.env.example` to `.env`. Never commit real API keys or production credentials.
