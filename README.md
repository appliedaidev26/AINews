# AI News

Curated AI/ML news aggregator for engineering leaders and practitioners.
Fetches from Hacker News, Reddit, Arxiv, and RSS feeds daily, deduplicates,
and enriches each article with Gemini-generated summaries and relevancy scores.

**Production:** https://ai-news-8ef10.web.app
**API:** https://ainews-api-zz7suegwma-uc.a.run.app
**Admin:** https://ai-news-8ef10.web.app/admin

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript + Vite + Tailwind |
| API | Python / FastAPI on Cloud Run |
| Database | PostgreSQL 15 (Cloud SQL in prod / Docker locally) |
| AI enrichment | Gemini 2.5 Flash (OpenAI gpt-4o-mini fallback) |
| Deduplication | sentence-transformers all-MiniLM-L6-v2 |
| Auth | Firebase Authentication |
| Hosting | Firebase Hosting (frontend) + Cloud Run (API) |
| Scheduler | Cloud Scheduler → `POST /admin/ingest` daily at 11:00 UTC |

---

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker Desktop

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |
| `ADMIN_API_KEY` | any strong random string |
| `FIREBASE_PROJECT_ID` | Firebase console → Project Settings |
| `GOOGLE_APPLICATION_CREDENTIALS` | Firebase console → Service Accounts → Generate key |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | https://www.reddit.com/prefs/apps |

### 2. Start the database

```bash
docker compose up db -d
```

Postgres is now available at `localhost:5432` (user/password/db: `ainews`).

### 3. Create a virtualenv and install backend dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 4. Run the API server

```bash
venv/bin/python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Tables are created automatically on first startup.

### 5. Run the frontend dev server

```bash
cd frontend
npm install
npm run dev
```

Frontend is at http://localhost:5173. Requests to `/api/*` are proxied to `localhost:8000` — no CORS config needed.

### 6. Run the ingestion pipeline

```bash
# Today's articles
venv/bin/python -m backend.ingestion.pipeline

# Specific date
venv/bin/python -m backend.ingestion.pipeline 2026-02-20
```

Or trigger via the admin dashboard at http://localhost:5173/admin.

### 7. Run the scheduler locally

The scheduler is the CLI entry point for the pipeline (used by Cloud Scheduler in production):

```bash
# Today
venv/bin/python -m backend.scheduler

# Specific date
venv/bin/python -m backend.scheduler 2026-02-20
```

### Running everything with Docker Compose

To run all services together instead of the steps above:

```bash
docker compose up
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Frontend | http://localhost:5173 |
| Postgres | localhost:5432 |

`backend/` and `frontend/src/` are volume-mounted so code changes reload automatically.

---

## Production

### Infrastructure

| Component | GCP Service | Name |
|---|---|---|
| Frontend | Firebase Hosting | `ai-news-8ef10` |
| API | Cloud Run | `ainews-api` (us-central1) |
| Database | Cloud SQL PostgreSQL 15 | `ainews-db` (us-central1) |
| Container registry | Artifact Registry | `us-central1-docker.pkg.dev/ai-news-8ef10/ainews` |
| Scheduler | Cloud Scheduler | `ainews-daily-ingest` |

### Deploy the API

```bash
# Build for linux/amd64 (required for Cloud Run) and push
docker buildx build --platform linux/amd64 \
  -f Dockerfile.api \
  -t us-central1-docker.pkg.dev/ai-news-8ef10/ainews/api:latest \
  --push .

# Deploy to Cloud Run
gcloud run deploy ainews-api \
  --image us-central1-docker.pkg.dev/ai-news-8ef10/ainews/api:latest \
  --project ai-news-8ef10 \
  --region us-central1 \
  --quiet
```

### Deploy the frontend

```bash
# Ensure the production API URL is set
grep VITE_API_URL frontend/.env.local || \
  echo "VITE_API_URL=https://ainews-api-zz7suegwma-uc.a.run.app" >> frontend/.env.local

cd frontend && npm run build && cd ..
firebase deploy --only hosting --project ai-news-8ef10
```

### Trigger the pipeline manually

```bash
# Via curl
curl -X POST https://ainews-api-zz7suegwma-uc.a.run.app/admin/ingest \
  -H "X-Admin-Key: <ADMIN_API_KEY>"

# Specific date
curl -X POST "https://ainews-api-zz7suegwma-uc.a.run.app/admin/ingest?target_date=2026-02-20" \
  -H "X-Admin-Key: <ADMIN_API_KEY>"
```

Or use the admin dashboard: https://ai-news-8ef10.web.app/admin

### Cloud Scheduler

The pipeline runs automatically at **11:00 UTC (6 AM EST)** every day.

```bash
# Inspect the job
gcloud scheduler jobs describe ainews-daily-ingest \
  --project ai-news-8ef10 --location us-central1

# Run it immediately
gcloud scheduler jobs run ainews-daily-ingest \
  --project ai-news-8ef10 --location us-central1

# Change the schedule
gcloud scheduler jobs update http ainews-daily-ingest \
  --project ai-news-8ef10 --location us-central1 \
  --schedule "0 12 * * *"
```

### Database migrations

`create_all()` runs on every API startup and creates any missing tables. Additive column changes are applied via `IF NOT EXISTS` statements in `backend/db/__init__.py`. There is no migration framework.

---

## Project Structure

```
ainews/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI app, CORS, lifespan (create_tables)
│   │   └── routes/
│   │       ├── articles.py      # GET /articles, GET /articles/{id}
│   │       ├── digest.py        # GET /digest/today, GET /digest/{date}
│   │       ├── profile.py       # POST /profile, GET /profile/feed
│   │       └── admin.py         # POST /admin/ingest, GET /admin/runs, POST /admin/runs/{id}/cancel
│   ├── db/
│   │   ├── __init__.py          # Async/sync engines, get_db(), create_tables()
│   │   └── models.py            # Article, UserProfile, UserArticleScore, PipelineRun
│   ├── ingestion/
│   │   ├── pipeline.py          # Orchestrator: fetch → filter → dedup → save → enrich
│   │   └── sources/
│   │       ├── hackernews.py    # Algolia API, score ≥ 50, AI/ML keyword filter
│   │       ├── reddit.py        # PRAW, 5 subreddits
│   │       ├── arxiv_source.py  # 5 categories (cs.AI, cs.LG, cs.CL, cs.CV, stat.ML)
│   │       └── rss_feeds.py     # 10 feeds (OpenAI, Anthropic, DeepMind, HuggingFace, etc.)
│   ├── processing/
│   │   ├── dedup.py             # Semantic dedup via sentence-transformers (threshold: 0.85)
│   │   ├── enricher.py          # Gemini prompt, per-article enrichment, OpenAI fallback
│   │   └── ranker.py            # Relevancy score: tags 45%, role 35%, engagement 20%
│   ├── scheduler.py             # CLI entry point for pipeline (Cloud Scheduler target)
│   ├── config.py                # Pydantic settings, all env vars
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/               # Feed, Article, Onboarding, Login, Admin
│       ├── components/          # ArticleCard, ArticleDetail, Sidebar, ProtectedRoute
│       ├── hooks/               # useAuth, useUserProfile
│       └── lib/api.ts           # Typed API client + adminApi
├── Dockerfile.api
├── docker-compose.yml
├── firebase.json
└── .env.example
```

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/articles` | — | List articles (`digest_date`, `category`, `tags`, `source_type`, `page`) |
| GET | `/articles/{id}` | — | Article detail with related articles |
| GET | `/digest/today` | — | Today's digest grouped by category |
| GET | `/digest/{date}` | — | Digest for a specific ISO date |
| POST | `/profile` | Firebase | Save onboarding profile, triggers async score compute |
| GET | `/profile/feed` | Firebase | Personalized feed ranked by relevancy |
| POST | `/admin/ingest` | Admin key | Trigger pipeline; returns `run_id` |
| GET | `/admin/runs` | Admin key | Pipeline run history (last 50) |
| GET | `/admin/runs/{id}` | Admin key | Single run with live progress |
| POST | `/admin/runs/{id}/cancel` | Admin key | Cancel an in-progress run |
| GET | `/health` | — | Health check |

---

## Data Sources

| Source | Method | Filter |
|---|---|---|
| Hacker News | Algolia API | Score ≥ 50, AI/ML keywords |
| Reddit | PRAW | r/MachineLearning, r/LocalLLaMA, r/datascience, r/artificial, r/singularity |
| Arxiv | arxiv library | cs.AI, cs.LG, cs.CL, cs.CV, stat.ML |
| RSS | feedparser | OpenAI, Anthropic, DeepMind, HuggingFace, Google AI, Meta AI, The Gradient, Import AI, Simon Willison |
