# AI News

A curated AI/ML news aggregator tailored towards engineering leaders, ML engineers, and data scientists.

## Quick Start (Local Dev)

### Prerequisites
- Docker & Docker Compose
- Python 3.12+
- Node.js 20+
- A [Gemini API key](https://aistudio.google.com/app/apikey)

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY (and optional REDDIT_CLIENT_ID/SECRET)
```

### 2. Start the stack

```bash
docker compose up
```

- **API:** http://localhost:8000
- **Frontend:** http://localhost:5173
- **API docs:** http://localhost:8000/docs

### 3. Run the ingestion pipeline

```bash
# Install backend deps (first time)
pip install -r backend/requirements.txt

# Fetch and enrich today's articles
python -m backend.ingestion.pipeline
```

Or target a specific date:

```bash
python -m backend.ingestion.pipeline 2026-02-21
```

### 4. Frontend dev (without Docker)

```bash
cd frontend
npm install
npm run dev
```

---

## Project Structure

```
ainews/
├── backend/
│   ├── ingestion/          # HN, Reddit, Arxiv, RSS sources + pipeline orchestrator
│   ├── processing/         # Dedup (embeddings), Gemini enrichment, relevancy ranker
│   ├── api/                # FastAPI routes: /articles, /digest, /profile
│   ├── db/                 # SQLAlchemy models, Alembic migrations
│   └── scheduler.py        # Cloud Run Job entry point
├── frontend/
│   └── src/
│       ├── components/     # ArticleCard, ArticleDetail, OnboardingFlow, CategoryFilter
│       ├── pages/          # Feed, Article, Onboarding
│       └── hooks/          # useUserProfile (localStorage + API)
├── docs/
│   └── requirements-final.md
├── docker-compose.yml
├── Dockerfile.api
└── cloudbuild.yaml
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/articles` | List articles (params: `digest_date`, `category`, `page`) |
| GET | `/articles/{id}` | Article detail with related articles |
| GET | `/digest/today` | Today's digest |
| GET | `/digest/{date}` | Digest for a specific date |
| POST | `/profile` | Save onboarding profile |
| GET | `/profile/feed` | Personalized feed for `session_id` |
| GET | `/health` | Health check |

---

## Data Sources

| Source | Method | Filter |
|---|---|---|
| Hacker News | Algolia API | Score ≥ 50, AI/ML keywords |
| Reddit | PRAW | r/MachineLearning, r/LocalLLaMA, r/datascience, r/artificial, r/singularity |
| Arxiv | arxiv library | cs.AI, cs.LG, cs.CL, cs.CV, stat.ML |
| RSS Blogs | feedparser | OpenAI, Anthropic, DeepMind, HuggingFace, Google AI, Meta AI, The Gradient, Import AI, Simon Willison |

---

## Environment Variables

See `.env.example` for the full list. Required:

- `GEMINI_API_KEY` — from [Google AI Studio](https://aistudio.google.com/app/apikey)
- `DATABASE_URL` — PostgreSQL connection (default: local Docker)

Optional:
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — for Reddit ingestion

---

## GCP Deployment

See `cloudbuild.yaml`. Requires:
1. Artifact Registry repo named `ainews`
2. Cloud Run service named `ainews-api`
3. Firebase Hosting project configured
4. Cloud Scheduler job pointing to the Cloud Run Job (`python -m backend.scheduler`)

---

## Verification Checklist

1. `python -m backend.ingestion.pipeline` — check articles fetched per source
2. Enricher on 5 articles — Gemini returns bullets, why_it_matters, tags
3. Ingest same story from HN + RSS — only one article in DB
4. Two profiles (ML Engineer / Engineering Leader) — feed order differs
5. `uvicorn backend.api.main:app` — `/digest/today`, `/articles/{id}`, `/profile/feed` respond
6. `npm run dev` — onboarding flow, feed sort, detail page render correctly
7. `docker compose up` — full stack runs end-to-end
