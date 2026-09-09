# Quickstart

```bash
cp .env.example .env
docker compose up --build
```

The stack starts MongoDB, Redis, FastAPI, a worker, and the frontend. Backend is on port 8000 and frontend on port 3000.

No AISStream or Resend key is required for demo mode. For production, configure live credentials, managed MongoDB/Redis, and a validated SAR model.
