# AI News Site — Finalized Requirements & Implementation Plan

**Version:** 1.0
**Date:** 2026-02-21
**Status:** In Development

---

## 1. Product Overview

A curated AI/ML news aggregator for engineering leaders, ML engineers, data scientists, and software engineers. The site ingests articles daily from multiple sources, uses Gemini to summarize and enrich content, and delivers a personalized daily digest. Users complete a brief interest onboarding; articles are ranked by a personal relevancy score.

**Target audience:** Engineering leaders, ML engineers, data scientists, software engineers, AI researchers
**Business model:** Audience growth first; commercialize in Phase 4 (premium tier, API access, team digests)
**Hosting:** Google Cloud Platform

---

## 2. MVP Scope (Phase 1)

### 2.1 Core Capabilities

| # | Capability | Notes |
|---|---|---|
| 1 | Daily ingestion from multiple sources | HN, Reddit, Arxiv, RSS blogs |
| 2 | Semantic deduplication | Same story from multiple outlets → one article |
| 3 | AI enrichment via Gemini | Bullets, category, "why it matters", tags, audience scores, quotes |
| 4 | User interest onboarding | Single-page, < 30 sec, anonymous (localStorage) |
| 5 | Personalized feed | Sorted by relevancy score (profiled) or recency (anonymous) |
| 6 | Category filtering | Filter feed by Research, Tools, Industry News, etc. |
| 7 | Article detail page | Bullets, attributed source, quotes, why it matters, related articles |
| 8 | Related articles | Top 3 by tag/category overlap, from last 30 days |

### 2.2 Out of Scope for Phase 1

- User accounts / authentication (Firebase Auth — Phase 2)
- Email digest (Phase 2)
- Full-text search (Phase 2)
- Bookmarks, alerts, RSS output (Phase 3)
- Premium tier / API access (Phase 4)

---

## 3. Data Sources

| Source | Method | Subreddits / Categories | Filter |
|---|---|---|---|
| Hacker News | Algolia Search API | N/A | Score ≥ 50, AI/ML keywords in title or URL |
| Reddit | PRAW (official API) | r/MachineLearning, r/LocalLLaMA, r/datascience, r/artificial, r/singularity | Score ≥ 50 |
| Arxiv | `arxiv` Python library | cs.AI, cs.LG, cs.CL, cs.CV, stat.ML | Keyword match in title + abstract |
| RSS Blogs | `feedparser` | OpenAI, Anthropic, DeepMind, HuggingFace, Google AI, Meta AI, The Gradient, Import AI, Towards Data Science, Simon Willison | Latest 20 per feed |

**Volume estimate:** ~150–300 raw articles/day → ~80–150 after dedup and relevance filtering.

---

## 4. Architecture

```
Sources (HN, Reddit, Arxiv, RSS blogs)
       │
       ▼
 [Ingestion Pipeline]         ← Python, daily via Cloud Scheduler → Cloud Run Job
       │
       ▼
 [Semantic Deduplication]     ← sentence-transformers (all-MiniLM-L6-v2), cosine ≥ 0.85
       │
       ▼
 [AI Enrichment — Gemini]     ← gemini-1.5-flash (flash-pro fallback for complex)
   • 5–7 bullet-point summary
   • Category classification
   • "Why it matters" (1–2 sentences)
   • Tags (3–7)
   • Audience relevancy scores (per role)
   • Notable verbatim quotes (1–3)
       │
       ▼
 [Cloud SQL — PostgreSQL 15]  ← Articles, user profiles, relevancy scores
       │
       ▼
 [FastAPI on Cloud Run]       ← REST API + relevancy scoring
       │
       ▼
 [React Frontend]             ← Firebase Hosting (global CDN)
   Feed (sorted by relevancy) + Detail page + Onboarding
```

---

## 5. Project Structure

```
ainews/
├── backend/
│   ├── ingestion/
│   │   ├── sources/
│   │   │   ├── hackernews.py       # Algolia API, keyword filter, score ≥ 50
│   │   │   ├── reddit.py           # PRAW, 5 subreddits, score ≥ 50
│   │   │   ├── arxiv_source.py     # arxiv lib, 5 categories, relevance filter
│   │   │   └── rss_feeds.py        # feedparser, 10 RSS feeds
│   │   └── pipeline.py             # Orchestrates: fetch → dedup → save → enrich
│   ├── processing/
│   │   ├── dedup.py                # Embedding similarity, cosine threshold
│   │   ├── enricher.py             # Gemini API calls, related article computation
│   │   └── ranker.py               # Relevancy score per user profile
│   ├── api/
│   │   ├── main.py                 # FastAPI app, CORS, startup
│   │   └── routes/
│   │       ├── articles.py         # GET /articles, GET /articles/{id}
│   │       ├── digest.py           # GET /digest/today, GET /digest/{date}
│   │       └── profile.py          # POST /profile, GET /profile/feed
│   ├── db/
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── migrations/             # Alembic
│   │   └── __init__.py             # Engine, session factory
│   ├── scheduler.py                # Cloud Run Job entry point
│   └── config.py                   # Pydantic settings
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ArticleCard.tsx     # Feed card: title, bullet preview, tags, relevancy
│   │   │   ├── ArticleDetail.tsx   # Full detail: bullets, quotes, why, related
│   │   │   ├── CategoryFilter.tsx  # Horizontal pill filter bar
│   │   │   ├── OnboardingFlow.tsx  # Single-page interest capture
│   │   │   └── RelevancyBadge.tsx  # Visual relevancy indicator
│   │   ├── pages/
│   │   │   ├── Feed.tsx            # Main feed, sort by relevancy or recency
│   │   │   ├── Article.tsx         # Detail page (wraps ArticleDetail)
│   │   │   └── Onboarding.tsx      # Onboarding page
│   │   ├── hooks/
│   │   │   └── useUserProfile.ts   # Read/write profile: localStorage + API
│   │   ├── lib/
│   │   │   └── api.ts              # Typed API client
│   │   └── App.tsx                 # Router setup
│   ├── index.html
│   ├── tailwind.config.ts
│   ├── vite.config.ts
│   └── package.json
├── docs/
│   └── requirements-final.md       # This file
├── docker-compose.yml              # Local dev: API + DB + frontend
├── cloudbuild.yaml                 # CI/CD → Cloud Run
├── .env.example
└── README.md
```

---

## 6. Database Schema

### `articles`

| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| title | varchar(1000) | |
| original_url | varchar(2000) | Attributed source link |
| source_name | varchar(100) | e.g. "HackerNews", "Reddit/r/MachineLearning" |
| source_type | varchar(50) | `hn` \| `reddit` \| `arxiv` \| `rss` |
| author | varchar(200) | nullable |
| published_at | timestamptz | nullable |
| ingested_at | timestamptz | default now() |
| digest_date | date | indexed |
| summary_bullets | jsonb | list of strings |
| annotations | jsonb | list of verbatim quotes |
| why_it_matters | text | |
| category | varchar(100) | indexed |
| tags | text[] | GIN indexed |
| audience_scores | jsonb | `{role: float}` |
| related_article_ids | int[] | top 3 by similarity |
| engagement_signal | int | HN score, Reddit upvotes |
| dedup_hash | varchar(64) | unique, SHA-256 of URL |
| embedding | float[] | sentence-transformer vector |
| is_enriched | int | 0=pending, 1=done, -1=failed |

### `user_profiles`

| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| session_id | varchar(100) | unique; UUID from localStorage |
| role | varchar(50) | engineering_leader \| ml_engineer \| data_scientist \| software_engineer \| researcher |
| interests | text[] | selected interest tags |
| focus | varchar(100) | keeping_up \| practitioner \| team_leader |
| created_at | timestamptz | |
| updated_at | timestamptz | |

### `user_article_scores`

| Column | Type | Notes |
|---|---|---|
| id | serial PK | |
| user_id | int FK → user_profiles | cascade delete |
| article_id | int FK → articles | cascade delete |
| relevancy_score | float | 0.0–1.0 |
| computed_at | timestamptz | |

**Unique constraint:** `(user_id, article_id)`

---

## 7. AI Enrichment Schema (Gemini Output)

```json
{
  "summary_bullets": [
    "Bullet 1 — key finding or announcement",
    "Bullet 2",
    "Bullet 3",
    "Bullet 4",
    "Bullet 5"
  ],
  "annotations": [
    "Verbatim quote 1 — most insightful or surprising",
    "Verbatim quote 2"
  ],
  "why_it_matters": "1–2 sentences explaining impact for ML engineers and eng leaders.",
  "category": "Research | Tools & Libraries | Industry News | Policy & Ethics | Tutorials",
  "tags": ["llms", "fine-tuning", "rag", "open-source"],
  "audience_scores": {
    "engineering_leader": 0.8,
    "ml_engineer": 0.9,
    "data_scientist": 0.7,
    "software_engineer": 0.5,
    "researcher": 0.6
  }
}
```

**Gemini model selection:**
- Default: `gemini-1.5-flash` (speed + cost)
- Fallback: `gemini-1.5-pro` for longer/complex articles

---

## 8. Relevancy Scoring Algorithm

```python
def relevancy_score(article, user_profile) -> float:
    tag_overlap = len(set(article.tags) & set(user_profile.interests)) / max(len(article.tags), 1)
    role_score  = article.audience_scores.get(user_profile.role, 0.5)
    engagement  = min(article.engagement_signal / 1000, 1.0)  # normalize to 0–1

    score = (tag_overlap * 0.45) + (role_score * 0.35) + (engagement * 0.20)
    return round(score, 3)
```

Feed sort order:
- **Profiled users:** `relevancy_score` descending
- **Anonymous users:** `engagement_signal` descending

---

## 9. API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/articles` | List articles; params: `date`, `category`, `page`, `per_page` |
| GET | `/articles/{id}` | Single article with related articles populated |
| GET | `/digest/today` | Today's digest (shorthand for `/digest/{today}`) |
| GET | `/digest/{date}` | Digest for specific date (YYYY-MM-DD) |
| POST | `/profile` | Save onboarding profile `{session_id, role, interests, focus}` |
| GET | `/profile/feed` | Personalized feed for `session_id`; computes + returns relevancy scores |

---

## 10. User Onboarding Flow

Single page, all inputs visible at once, < 30 seconds to complete.

```
┌─────────────────────────────────────────────────────┐
│  Personalize your feed                               │
│                                                       │
│  I am a...                                           │
│  ○ Engineering Leader   ○ ML Engineer                 │
│  ○ Data Scientist       ○ Software Engineer           │
│  ○ Researcher                                         │
│                                                       │
│  I care about... (pick any)                           │
│  [LLMs] [Computer Vision] [MLOps] [Policy & Ethics]  │
│  [Open Source] [Research Papers] [Industry News]      │
│  [Tutorials] [Robotics]                               │
│                                                       │
│  My focus is...                                       │
│  ○ Keeping up with the field                          │
│  ○ Hands-on practitioner                              │
│  ○ Leading a team building AI                         │
│                                                       │
│              [Take me to my feed →]                   │
└─────────────────────────────────────────────────────┘
```

**Storage:** localStorage UUID as `session_id` (anonymous) → database via `POST /profile`

---

## 11. Article Detail Page Layout

```
┌─────────────────────────────────────────────────────┐
│  [Category Badge]  [Source: HackerNews]  [Date]      │
│                                                       │
│  Article Title                                        │
│  ─────────────────────────────────────────────────  │
│  Original source: [blog.openai.com/...] ← attributed │
│  Author: Jane Doe  |  [Read full article →]          │
│                                                       │
│  Summary                                              │
│  • Key point 1                                        │
│  • Key point 2                                        │
│  • Key point 3                                        │
│  • Key point 4                                        │
│  • Key point 5                                        │
│                                                       │
│  Notable Quotes                                       │
│  ─────────────────────────────────────────────────  │
│  ❝ "Verbatim quote 1 from article" ❞                 │
│  ❝ "Verbatim quote 2 from article" ❞                 │
│                                                       │
│  Why it Matters                                       │
│  ─────────────────────────────────────────────────  │
│  1–2 sentence explanation tailored to audience.       │
│                                                       │
│  Tags: [LLMs] [Fine-tuning] [Open Source]            │
│                                                       │
│  Related Articles                                     │
│  ─────────────────────────────────────────────────  │
│  • [Related article title 1]  [Category]             │
│  • [Related article title 2]  [Category]             │
│  • [Related article title 3]  [Category]             │
└─────────────────────────────────────────────────────┘
```

---

## 12. UI Design Principles

- **No depth effects** — no box shadows, no gradients; use 1px borders or background-color contrast only
- **Typography-first** — large readable headlines, clear size hierarchy (xl titles, base body, sm meta)
- **Generous whitespace** — articles breathe; padding-x 6, padding-y 8 minimum
- **Color palette** — neutral base (white / gray-50), single accent (`indigo-600`) for links, badges, and active states
- **Source attribution** — always visible and linked, never hidden or de-emphasized
- **Relevancy indicator** — subtle left border or colored dot; not intrusive
- **Inspiration** — Hacker News simplicity + Ars Technica readability

---

## 13. Google Cloud Infrastructure

| Component | GCP Service | Notes |
|---|---|---|
| Backend API | Cloud Run | Auto-scales; pay per request |
| Ingestion job | Cloud Run Job | Triggered by Cloud Scheduler (daily, 2 AM UTC) |
| Database | Cloud SQL (PostgreSQL 15) | Private IP; connection via Cloud SQL Auth Proxy |
| Frontend | Firebase Hosting | Global CDN; free tier |
| AI enrichment | Gemini API | Via `google-generativeai` Python SDK |
| Secrets | Secret Manager | API keys, DB passwords |
| Logs | Cloud Logging | Built-in with Cloud Run |
| Container registry | Artifact Registry | `us-central1-docker.pkg.dev` |

---

## 14. Tech Stack

| Layer | Choice | Version |
|---|---|---|
| Ingestion | Python (httpx, praw, feedparser, arxiv) | Python 3.12 |
| AI enrichment | Gemini 1.5 Flash / Pro | google-generativeai 0.8 |
| Deduplication | sentence-transformers (all-MiniLM-L6-v2) | 3.3 |
| Database | PostgreSQL 15 via SQLAlchemy (async) | SQLAlchemy 2.0 |
| API | FastAPI + Uvicorn | 0.115 / 0.32 |
| Frontend | React + TypeScript + Vite + Tailwind CSS | React 18, Vite 6, Tailwind 4 |
| Hosting | Firebase Hosting (frontend) + Cloud Run (API) | — |
| Scheduling | Cloud Scheduler → Cloud Run Job | — |
| Local dev | Docker Compose | — |
| CI/CD | Cloud Build → Artifact Registry → Cloud Run | cloudbuild.yaml |

---

## 15. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | asyncpg connection string |
| `DATABASE_URL_SYNC` | Yes | psycopg2 connection string (ingestion pipeline) |
| `GEMINI_API_KEY` | Yes | Google AI Studio API key |
| `GEMINI_MODEL` | No | Default: `gemini-1.5-flash` |
| `REDDIT_CLIENT_ID` | No | Reddit OAuth app client ID |
| `REDDIT_CLIENT_SECRET` | No | Reddit OAuth app secret |
| `HN_MIN_SCORE` | No | Default: 50 |
| `ARXIV_MAX_RESULTS` | No | Default: 30 per category |
| `DEDUP_SIMILARITY_THRESHOLD` | No | Default: 0.85 |
| `CORS_ORIGINS` | No | Default: localhost dev ports |

---

## 16. Verification Checklist

1. **Ingestion:** `python -m backend.ingestion.pipeline` → articles fetched from each source, counts logged
2. **Enrichment:** Run enricher on 5 sample articles → Gemini returns valid JSON with all fields
3. **Deduplication:** Ingest same story via HN + RSS → only one article in DB
4. **Relevancy:** Create two profiles (ML Engineer / Engineering Leader) → feed order differs
5. **API:** `uvicorn backend.api.main:app` → `/profile/feed`, `/articles/{id}`, `/digest/today` respond correctly
6. **Frontend:** `npm run dev` → onboarding flow works, feed sorts, detail page renders bullets + attribution + quotes
7. **Docker Compose:** `docker compose up` → full local stack end-to-end, no manual steps
8. **GCP deploy:** Cloud Scheduler triggers ingestion job; Firebase Hosting serves frontend with correct API URL

---

## 17. Known Constraints & Risks

| Risk | Mitigation |
|---|---|
| Reddit API rate limits | Cap at 25 posts/subreddit/day; add retry with backoff |
| Arxiv volume (50+ papers/day) | Keyword relevance filter before enrichment; `ARXIV_MAX_RESULTS=30` cap per category |
| Gemini API cost | Use Flash by default; batch enrichment; skip already-enriched articles |
| Anonymous profile loss | UUID persisted in localStorage; migrate to DB on optional registration |
| Cold-start latency on Cloud Run | Minimum 1 instance for API; ingestion is a one-off job |

---

## 18. Roadmap

| Phase | Features |
|---|---|
| **Phase 1 (MVP)** | Ingestion, enrichment, dedup, onboarding, feed, detail page, Cloud Run + Firebase deploy |
| **Phase 2** | Firebase Auth, persistent user accounts, email digest (SendGrid), full-text search |
| **Phase 3** | RSS output, bookmarks, topic alerts, Slack bot |
| **Phase 4** | Premium tier: team digests, API access, advanced personalization |
