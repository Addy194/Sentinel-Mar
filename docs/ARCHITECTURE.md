# Sentinel-Mar Architecture

React UI → FastAPI → MongoDB

                 ↘ Redis → worker processes

Sentinel-1 STAC → VV/VH candidate detector → analyst review
AIS live/replay → correlation ← drift model

Jobs are persisted in MongoDB and claimed by workers with leases and retries. Demo adapters are explicit so missing external credentials do not masquerade as live integrations.
