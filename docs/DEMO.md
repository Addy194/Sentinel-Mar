# Sentinel-Mar Demo

```bash
cp .env.example .env
docker compose up --build
```

Keep `AIS_MODE=demo` and `EMAIL_MODE=demo` for a credential-free demo. The UI/API should label replayed AIS as demo and email as demo outbox. Detection output is an **ML candidate requiring analyst review**.

The bundled SAR model is a synthetic-data prototype, not a field-validated operational oil-spill detector. State this clearly during judging.
