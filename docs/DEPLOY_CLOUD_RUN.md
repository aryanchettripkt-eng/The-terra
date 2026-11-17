# Deploying the API to Google Cloud Run

The FastAPI backend (`Dockerfile` at the repo root) runs on Google Cloud Run's free tier.
The Next.js frontend in `web/` stays on Vercel; the database stays on Neon.

## Why Cloud Run

- The API is plain HTTP (no websockets), so a scale-to-zero host is fine. Cold starts are
  covered by the warm-up step in `.github/workflows/forecast_cron.yml`.
- The image carries the geospatial/ML stack (geopandas, rasterio, xgboost, ortools), which
  needs more headroom than 512 MB hosts give it. Cloud Run allows 1–2 GiB on the free tier.
- `POST /alerts/forecast/trigger` returns 202 and keeps working in a FastAPI background task.
  That only works when Cloud Run keeps the CPU on after the response, so the service must use
  **instance-based billing** ("CPU is always allocated"). See the settings table below.
- Neon is reached over Postgres port 5432, which Cloud Run allows outbound.

## Service settings

| Setting | Value |
| --- | --- |
| Source | GitHub repo, branch `main`, build type **Dockerfile** (path `/Dockerfile`) |
| Region | The one closest to the Neon database (e.g. `asia-southeast1` for Neon Singapore, `asia-south1` for Mumbai) |
| Authentication | Allow unauthenticated invocations (public API) |
| Billing | **Instance-based** (CPU always allocated) |
| Min instances | 0 |
| Max instances | 1 (keeps usage inside the free tier; the forecast run guard is in-memory) |
| Container port | 8000 (the image also honours `$PORT`) |
| Memory / CPU | 1 GiB / 1 vCPU (raise memory to 2 GiB if a forecast run is OOM-killed) |
| Request timeout | 300 s |

## Environment variables

Copy them from the old Render service (Render dashboard → the-dead-zone → Environment).
At minimum:

| Variable | Notes |
| --- | --- |
| `DATABASE_URL` | Neon **direct** (non-pooler) connection string |
| `DIRECT_DATABASE_URL` | Same as above |
| `DEMO_MODE` | as on Render |
| `ALLOWED_ORIGINS` | JSON list, e.g. `["https://<your-app>.vercel.app"]` |
| `SESSION_COOKIE_SECURE` | `true` |
| `SESSION_COOKIE_SAMESITE` | `none` (frontend and API are on different sites) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | if Google sign-in is used |
| `GROQ_API_KEY` | if the chat assistant is used |
| `FORECAST_SCHEDULER_ENABLED` | `false` — the GitHub Actions cron triggers forecasts instead, since the instance scales to zero |

Put real secrets (database URLs, client secret, API keys) in the
"Variables & Secrets" tab; Secret Manager's free tier covers a handful of secrets.

## After the first deploy

1. Copy the service URL (`https://<service>-<hash>.<region>.run.app`) and check
   `<URL>/health` returns 200.
2. Vercel → project → Settings → Environment Variables: set `NEXT_PUBLIC_API_BASE_URL`,
   `NEXT_PUBLIC_TILE_BASE_URL` and `BACKEND_INTERNAL_URL` to the URL, then redeploy.
3. GitHub → repo → Settings → Secrets and variables → Actions: set `SETU_API_URL` to the URL
   so the forecast cron hits the new host.
4. Google Cloud console → Billing → Budgets & alerts: add a small budget (e.g. $1) with email
   alerts, so any usage beyond the free tier is noticed.

## Free-tier notes

- Cloud Run (instance-based billing) includes 240,000 vCPU-seconds and 450,000 GiB-seconds per
  month. An instance stays up for up to ~15 minutes after its last request, so this covers
  roughly 60+ hours of awake time a month at 1 vCPU / 1 GiB.
- Built images live in Artifact Registry, which is free up to 0.5 GB. This image is larger, so
  expect a few cents a month unless a cleanup policy keeps only the latest image.
