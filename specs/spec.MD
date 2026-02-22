Plan to implement                                                                                                                           │
│                                                                                                                                             │
│ AI News Site - Architecture & Implementation Plan                                                                                           │
│                                                                                                                                             │
│ Context                                                                                                                                     │
│                                                                                                                                             │
│ Build a curated AI/ML news aggregator targeted at engineering leaders, data scientists, ML engineers, and software engineers. The site      │
│ aggregates from multiple sources, uses Gemini to summarize and enrich content, and presents it as a daily digest web app. Users complete a  │
│ brief interest onboarding; articles are ranked by personal relevancy score. Start simple for audience growth; commercialize later. Hosted   │
│ on Google Cloud.                                                                                                                            │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ MVP Scope (Phase 1)                                                                                                                         │
│                                                                                                                                             │
│ Core Capabilities                                                                                                                           │
│                                                                                                                                             │
│ 1. Ingest articles daily from multiple sources                                                                                              │
│ 2. Deduplicate semantically (same story, multiple outlets)                                                                                  │
│ 3. Use Gemini API to: produce bullet-point summaries, classify, generate "why it matters", assign tags                                      │
│ 4. User onboarding captures interest profile → relevancy score per article per user                                                         │
│ 5. Article feed sorted by relevancy score (personal) or recency (default for anonymous)                                                     │
│ 6. Detail page: attributed source link, bullet summary, "Why it matters" section                                                            │
│ 7. Clean, flat design — no depth effects, minimal chrome                                                                                    │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Architecture                                                                                                                                │
│                                                                                                                                             │
│ Sources (HN, Reddit, Arxiv, RSS blogs)                                                                                                      │
│        │                                                                                                                                    │
│        ▼                                                                                                                                    │
│  [Ingestion Pipeline]     ← Python, daily via Cloud Scheduler → Cloud Run Job                                                               │
│        │                                                                                                                                    │
│        ▼                                                                                                                                    │
│  [Deduplication]          ← Embedding similarity (Vertex AI Embeddings or local model)                                                      │
│        │                                                                                                                                    │
│        ▼                                                                                                                                    │
│  [AI Enrichment]          ← Gemini API (gemini-1.5-flash or gemini-1.5-pro)                                                                 │
│    • Bullet-point summary (5-7 bullets)                                                                                                     │
│    • Category                                                                                                                               │
│    • "Why it matters" (1-2 sentences per role)                                                                                              │
│    • Tags                                                                                                                                   │
│        │                                                                                                                                    │
│        ▼                                                                                                                                    │
│  [Cloud SQL (PostgreSQL)]  ← Articles, categories, tags, user interest profiles                                                             │
│        │                                                                                                                                    │
│        ▼                                                                                                                                    │
│  [FastAPI on Cloud Run]    ← REST API + relevancy scoring                                                                                   │
│        │                                                                                                                                    │
│        ▼                                                                                                                                    │
│  [React frontend]         ← Feed (sorted by relevancy) + Detail page                                                                        │
│    hosted on Firebase Hosting or Cloud Run                                                                                                  │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Data Sources                                                                                                                                │
│                                                                                                                                             │
│ Source: Hacker News                                                                                                                         │
│ Method: Algolia Search API                                                                                                                  │
│ Key Content: Top/new stories, filter by score (≥50) & AI/ML keywords                                                                        │
│ ────────────────────────────────────────                                                                                                    │
│ Source: Reddit                                                                                                                              │
│ Method: PRAW (official API)                                                                                                                 │
│ Key Content: r/MachineLearning, r/LocalLLaMA, r/datascience, r/artificial, r/singularity                                                    │
│ ────────────────────────────────────────                                                                                                    │
│ Source: Arxiv                                                                                                                               │
│ Method: arxiv Python library                                                                                                                │
│ Key Content: cs.AI, cs.LG, cs.CL, cs.CV, stat.ML — filter by citation signals                                                               │
│ ────────────────────────────────────────                                                                                                    │
│ Source: RSS Blogs                                                                                                                           │
│ Method: feedparser                                                                                                                          │
│ Key Content: OpenAI, Anthropic, DeepMind, HuggingFace, Google AI, Meta AI, The Gradient, Import AI, Towards Data Science, Simon Willison    │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Article Detail Page Structure                                                                                                               │
│                                                                                                                                             │
│ ┌─────────────────────────────────────────────────────┐                                                                                     │
│ │  [Category Badge]  [Source: HackerNews]  [Date]      │                                                                                    │
│ │                                                       │                                                                                   │
│ │  Article Title                                        │                                                                                   │
│ │  ─────────────────────────────────────────────────  │                                                                                     │
│ │  Original source: [blog.openai.com/...] ← attributed │                                                                                    │
│ │  Author: Jane Doe  |  [Read full article →]          │                                                                                    │
│ │                                                       │                                                                                   │
│ │  Summary                                              │                                                                                   │
│ │  • Key point 1                                        │                                                                                   │
│ │  • Key point 2                                        │                                                                                   │
│ │  • Key point 3                                        │                                                                                   │
│ │  • Key point 4                                        │                                                                                   │
│ │  • Key point 5                                        │                                                                                   │
│ │                                                       │                                                                                   │
│ │  Notable Quotes                            ← AI annotations                                                                               │
│ │  ─────────────────────────────────────────────────  │                                                                                     │
│ │  ❝ "Quote pulled verbatim from article" ❞            │                                                                                    │
│ │  ❝ "Second notable quote or key claim"   ❞            │                                                                                   │
│ │                                                       │                                                                                   │
│ │  Why it Matters                                       │                                                                                   │
│ │  ─────────────────────────────────────────────────  │                                                                                     │
│ │  [1-2 sentence explanation tailored to audience]      │                                                                                   │
│ │                                                       │                                                                                   │
│ │  Tags: [LLMs] [Fine-tuning] [Open Source]            │                                                                                    │
│ │                                                       │                                                                                   │
│ │  Related Articles                                     │                                                                                   │
│ │  ─────────────────────────────────────────────────  │                                                                                     │
│ │  • [Related article title 1]  [Category]             │                                                                                    │
│ │  • [Related article title 2]  [Category]             │                                                                                    │
│ │  • [Related article title 3]  [Category]             │                                                                                    │
│ └─────────────────────────────────────────────────────┘                                                                                     │
│                                                                                                                                             │
│ Notable Quotes: Gemini extracts 1-3 verbatim quotes from the original article that are particularly insightful, surprising, or quotable.    │
│ Stored as annotations jsonb on the article row.                                                                                             │
│                                                                                                                                             │
│ Related Articles: Top 3 articles by cosine similarity of tag overlap + category match, from the last 30 days. Computed at enrichment time   │
│ and stored as related_article_ids int[].                                                                                                    │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ User Onboarding & Relevancy                                                                                                                 │
│                                                                                                                                             │
│ Onboarding Flow (single page, < 30 sec)                                                                                                     │
│                                                                                                                                             │
│ All inputs on one screen — user answers and lands immediately in their personalized feed.                                                   │
│                                                                                                                                             │
│ ┌─────────────────────────────────────────────────────┐                                                                                     │
│ │  Personalize your feed                               │                                                                                    │
│ │                                                       │                                                                                   │
│ │  I am a...  [role dropdown or pill select]           │                                                                                    │
│ │  ○ Engineering Leader   ○ ML Engineer                 │                                                                                   │
│ │  ○ Data Scientist       ○ Software Engineer           │                                                                                   │
│ │  ○ Researcher                                         │                                                                                   │
│ │                                                       │                                                                                   │
│ │  I care about... (pick any)                           │                                                                                   │
│ │  [LLMs] [Computer Vision] [MLOps] [Policy & Ethics]  │                                                                                    │
│ │  [Open Source] [Research Papers] [Industry News]      │                                                                                   │
│ │  [Tutorials] [Robotics]                               │                                                                                   │
│ │                                                       │                                                                                   │
│ │  My focus is...                                       │                                                                                   │
│ │  ○ Keeping up with the field                          │                                                                                   │
│ │  ○ Hands-on practitioner                              │                                                                                   │
│ │  ○ Leading a team building AI                         │                                                                                   │
│ │                                                       │                                                                                   │
│ │              [Take me to my feed →]                   │                                                                                   │
│ └─────────────────────────────────────────────────────┘                                                                                     │
│                                                                                                                                             │
│ Data stored in: localStorage (anonymous) → database (if they register later)                                                                │
│                                                                                                                                             │
│ Relevancy Scoring Algorithm                                                                                                                 │
│                                                                                                                                             │
│ def relevancy_score(article, user_profile):                                                                                                 │
│     # Base signals                                                                                                                          │
│     tag_overlap = len(set(article.tags) & set(user_profile.interests)) / max(len(article.tags), 1)                                          │
│     role_score = article.audience_scores[user_profile.role]  # 0-1, from Gemini enrichment                                                  │
│     engagement = normalize(article.engagement_signal)        # HN score, upvotes, etc.                                                      │
│                                                                                                                                             │
│     # Weighted combination                                                                                                                  │
│     score = (tag_overlap * 0.45) + (role_score * 0.35) + (engagement * 0.20)                                                                │
│     return round(score, 3)                                                                                                                  │
│                                                                                                                                             │
│ Articles in the feed are sorted by relevancy_score (logged-in / profiled users) or engagement_signal (anonymous).                           │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ AI Enrichment Schema (Gemini output per article)                                                                                            │
│                                                                                                                                             │
│ {                                                                                                                                           │
│   "summary_bullets": [                                                                                                                      │
│     "Bullet 1 — key finding or announcement",                                                                                               │
│     "Bullet 2",                                                                                                                             │
│     "Bullet 3",                                                                                                                             │
│     "Bullet 4",                                                                                                                             │
│     "Bullet 5"                                                                                                                              │
│   ],                                                                                                                                        │
│   "annotations": [                                                                                                                          │
│     "Verbatim quote 1 — most insightful or surprising",                                                                                     │
│     "Verbatim quote 2"                                                                                                                      │
│   ],                                                                                                                                        │
│   "why_it_matters": "1-2 sentences explaining impact for ML engineers and eng leaders",                                                     │
│   "category": "Research | Tools & Libraries | Industry News | Policy & Ethics | Tutorials",                                                 │
│   "tags": ["LLMs", "Fine-tuning", "RAG", "MLOps", "Open Source", ...],                                                                      │
│   "audience_scores": {                                                                                                                      │
│     "engineering_leader": 0.8,                                                                                                              │
│     "ml_engineer": 0.9,                                                                                                                     │
│     "data_scientist": 0.7,                                                                                                                  │
│     "software_engineer": 0.5                                                                                                                │
│   }                                                                                                                                         │
│ }                                                                                                                                           │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Database Schema (Cloud SQL / PostgreSQL)                                                                                                    │
│                                                                                                                                             │
│ articles — id, title, original_url, source_name, source_type, author, published_at, ingested_at, summary_bullets jsonb, annotations jsonb,  │
│ why_it_matters text, category, tags text[], audience_scores jsonb, engagement_signal int, related_article_ids int[], dedup_hash,            │
│ digest_date date                                                                                                                            │
│                                                                                                                                             │
│ user_profiles — id, session_id (for anon), role, interests text[], experience_level, created_at                                             │
│                                                                                                                                             │
│ user_article_scores — user_id, article_id, relevancy_score (computed on login or profile update)                                            │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Project Structure                                                                                                                           │
│                                                                                                                                             │
│ ainews/                                                                                                                                     │
│ ├── backend/                                                                                                                                │
│ │   ├── ingestion/                                                                                                                          │
│ │   │   ├── sources/                                                                                                                        │
│ │   │   │   ├── hackernews.py                                                                                                               │
│ │   │   │   ├── reddit.py                                                                                                                   │
│ │   │   │   ├── arxiv_source.py                                                                                                             │
│ │   │   │   └── rss_feeds.py                                                                                                                │
│ │   │   └── pipeline.py           # orchestrates all sources → normalize → dedup → enrich                                                   │
│ │   ├── processing/                                                                                                                         │
│ │   │   ├── dedup.py              # embedding similarity, cosine threshold                                                                  │
│ │   │   ├── enricher.py           # Gemini API: bullets, why, category, tags, scores                                                        │
│ │   │   └── ranker.py             # compute relevancy per user profile                                                                      │
│ │   ├── api/                                                                                                                                │
│ │   │   ├── main.py               # FastAPI app                                                                                             │
│ │   │   └── routes/                                                                                                                         │
│ │   │       ├── articles.py       # GET /articles, GET /articles/{id}                                                                       │
│ │   │       ├── digest.py         # GET /digest/today, GET /digest/{date}                                                                   │
│ │   │       └── profile.py        # POST /profile (save onboarding), GET /profile/feed                                                      │
│ │   ├── db/                                                                                                                                 │
│ │   │   ├── models.py                                                                                                                       │
│ │   │   └── migrations/                                                                                                                     │
│ │   ├── scheduler.py              # entry point for Cloud Scheduler → Cloud Run Job                                                         │
│ │   └── config.py                                                                                                                           │
│ ├── frontend/                                                                                                                               │
│ │   ├── src/                                                                                                                                │
│ │   │   ├── components/                                                                                                                     │
│ │   │   │   ├── ArticleCard.tsx    # flat card: title, bullets preview, tags, relevancy indicator                                           │
│ │   │   │   ├── ArticleDetail.tsx  # full detail: attribution, bullets, annotations, why it matters, related                                │
│ │   │   │   ├── CategoryFilter.tsx                                                                                                          │
│ │   │   │   ├── OnboardingFlow.tsx # single-page interest capture                                                                           │
│ │   │   │   └── RelevancyBadge.tsx # visual signal of match strength                                                                        │
│ │   │   ├── pages/                                                                                                                          │
│ │   │   │   ├── Feed.tsx           # main feed, sorted by relevancy or recency                                                              │
│ │   │   │   ├── Article.tsx        # detail page                                                                                            │
│ │   │   │   └── Onboarding.tsx                                                                                                              │
│ │   │   ├── hooks/                                                                                                                          │
│ │   │   │   └── useUserProfile.ts  # read/write profile from localStorage + API                                                             │
│ │   │   └── App.tsx                                                                                                                         │
│ │   └── package.json                                                                                                                        │
│ ├── cloudbuild.yaml                # CI/CD to Cloud Run                                                                                     │
│ ├── docker-compose.yml             # local dev                                                                                              │
│ ├── .env.example                                                                                                                            │
│ └── README.md                                                                                                                               │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ UI Design Principles (Flat Layout)                                                                                                          │
│                                                                                                                                             │
│ - No shadows, no cards with depth — use thin 1px borders or background-color contrast only                                                  │
│ - Typography-first: large, readable headlines; clear font size hierarchy                                                                    │
│ - Whitespace: generous padding, articles breathe                                                                                            │
│ - Color: neutral base (white/gray-50), one accent color for links/badges                                                                    │
│ - Source attribution: always visible, linked, never hidden                                                                                  │
│ - Relevancy: subtle indicator (e.g. thin colored left border or small dot) — not intrusive                                                  │
│                                                                                                                                             │
│ Inspiration: Hacker News simplicity + Ars Technica readability                                                                              │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Google Cloud Infrastructure                                                                                                                 │
│                                                                                                                                             │
│ ┌────────────────────┬───────────────────────────────────────────────┐                                                                      │
│ │     Component      │                  GCP Service                  │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Backend API        │ Cloud Run (auto-scales, pay per request)      │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Ingestion job      │ Cloud Run Job triggered by Cloud Scheduler    │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Database           │ Cloud SQL (PostgreSQL 15)                     │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Frontend           │ Firebase Hosting (global CDN, free tier)      │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ AI enrichment      │ Gemini API via google-generativeai Python SDK │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Secrets            │ Secret Manager (.env values)                  │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Logs               │ Cloud Logging (built-in with Cloud Run)       │                                                                      │
│ ├────────────────────┼───────────────────────────────────────────────┤                                                                      │
│ │ Container registry │ Artifact Registry                             │                                                                      │
│ └────────────────────┴───────────────────────────────────────────────┘                                                                      │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Tech Stack Summary                                                                                                                          │
│                                                                                                                                             │
│ ┌───────────────┬──────────────────────────────────────────────────────────────────────────────┐                                            │
│ │     Layer     │                                    Choice                                    │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ Ingestion     │ Python (httpx, praw, feedparser, arxiv)                                      │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ AI enrichment │ Gemini 1.5 Flash (speed + cost) with Flash Pro fallback for complex articles │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ Dedup         │ sentence-transformers (all-MiniLM) + cosine similarity                       │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ Database      │ Cloud SQL PostgreSQL                                                         │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ API           │ FastAPI on Cloud Run                                                         │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ Frontend      │ React + TypeScript + Vite + Tailwind (flat theme)                            │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ Hosting       │ Firebase Hosting (frontend) + Cloud Run (API)                                │                                            │
│ ├───────────────┼──────────────────────────────────────────────────────────────────────────────┤                                            │
│ │ Scheduling    │ Cloud Scheduler → Cloud Run Job                                              │                                            │
│ └───────────────┴──────────────────────────────────────────────────────────────────────────────┘                                            │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Roadmap (Post-MVP)                                                                                                                          │
│                                                                                                                                             │
│ ┌─────────┬────────────────────────────────────────────────────────────────────────────────────────────────────┐                            │
│ │  Phase  │                                              Features                                              │                            │
│ ├─────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤                            │
│ │ Phase 2 │ User accounts (Firebase Auth), persistent profiles, email digest (SendGrid), search (full-text PG) │                            │
│ ├─────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤                            │
│ │ Phase 3 │ RSS output, bookmarks, topic alerts, Slack bot                                                     │                            │
│ ├─────────┼────────────────────────────────────────────────────────────────────────────────────────────────────┤                            │
│ │ Phase 4 │ Premium tier: team digests, API access, advanced personalization                                   │                            │
│ └─────────┴────────────────────────────────────────────────────────────────────────────────────────────────────┘                            │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Verification Plan                                                                                                                           │
│                                                                                                                                             │
│ 1. Ingestion: python -m backend.ingestion.pipeline --date today → check articles fetched per source                                         │
│ 2. Enrichment: run enricher on 5 sample articles → verify Gemini returns bullet JSON, "why it matters", tags                                │
│ 3. Dedup: ingest same story via HN + blog RSS → confirm one article in DB                                                                   │
│ 4. Relevancy: create two test profiles (ML Engineer / Data Scientist) → verify feed order differs                                           │
│ 5. API: uvicorn backend.api.main:app → hit /profile/feed, /articles/{id}, /digest/today                                                     │
│ 6. Frontend: npm run dev → verify onboarding flow, feed sort, detail page layout (bullets + attribution + why)                              │
│ 7. Docker Compose: docker compose up → full local stack end-to-end                                                                          │
│ 8. GCP deploy: push to Cloud Run, verify Cloud Scheduler triggers job, Firebase Hosting serves frontend                                     │
│                                                                                                                                             │
│ ---                                                                                                                                         │
│ Open Questions to Resolve During Build                                                                                                      │
│                                                                                                                                             │
│ - Reddit API rate limits — may need aggressive caching or Pushshift alternative                                                             │
│ - Arxiv volume: 50+ papers/day → need minimum relevancy filter before enrichment to control Gemini API cost                                 │
│ - Anonymous vs. session-based profile: use localStorage UUID as session key before auth is added                                            │
╰