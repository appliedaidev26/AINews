"""AI enrichment using Gemini API."""
import asyncio
import json
import logging
import ssl
import socket
import time
from datetime import date
from typing import Optional

from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception, before_sleep_log,
)
import google.api_core.exceptions
from requests.exceptions import SSLError as RequestsSSLError, ConnectionError as RequestsConnectionError
from sqlalchemy.orm import Session
from sqlalchemy import select, update, or_

from backend.config import settings
from backend.db import sync_engine
from backend.db.models import Article

logger = logging.getLogger(__name__)

# Module-level rate semaphore shared across concurrent enrich_articles() calls
_rate_sem: Optional[asyncio.Semaphore] = None

def _get_rate_sem() -> asyncio.Semaphore:
    global _rate_sem
    if _rate_sem is None:
        _rate_sem = asyncio.Semaphore(5)
    return _rate_sem

ENRICHMENT_PROMPT = """You are a sharp, no-nonsense AI/ML analyst writing for smart technical readers. Your style is BowTied Bull — confident, contrarian, direct. You cut through hype and tell readers what actually matters. Dry humor welcome. No corporate-speak, no breathless enthusiasm. Assume the reader is technically competent.

Analyze this article and return a JSON object:

Article Title: {title}
Source: {source}
Content/Abstract: {content}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "summary": "A 300-500 word no-BS summary. Open with the key insight — what this actually means, not what the authors claim. Short punchy paragraphs (2-3 sentences max). Use **bold** for critical points. Be contrarian where warranted — if the paper oversells, say so. If it's genuinely important, explain why most people will miss that. End with 'what this means for you' — practical implications, not vague optimism.",
  "summary_bullets": [
    "Punchy bullet 1 — the actual signal, not the noise",
    "Bullet 2",
    "Bullet 3",
    "Bullet 4",
    "Bullet 5"
  ],
  "annotations": [
    "Most insightful or surprising verbatim quote or claim from the article",
    "Second notable quote (omit if no strong quotes available)"
  ],
  "why_it_matters": "1-2 sentences — cut through the noise. Why should a busy technical leader actually care? Be specific and concrete, not hand-wavy.",
  "practical_takeaway": "One sentence — what to actually DO with this information. Direct, specific, no fluff (e.g. 'If you're running RAG pipelines, swap out X for Y — the benchmarks aren't even close' or 'Skip this one unless you're in computer vision')",
  "category": "Research | Tools & Libraries | Industry News | Policy & Ethics | Tutorials",
  "tags": ["tag1", "tag2", "tag3"],
  "audience_scores": {{
    "engineering_leader": 0.8,
    "ml_engineer": 0.9,
    "data_scientist": 0.7,
    "software_engineer": 0.5,
    "researcher": 0.6
  }}
}}

Rules:
- summary: 300-500 words. Short paragraphs (2-3 sentences). Use **bold** for key insights. Be direct — open with what matters, not throat-clearing. Contrarian where honest. NO bullet points in the summary — save those for summary_bullets. Use \\n\\n between paragraphs.
- summary_bullets: exactly 5 punchy bullets, each 10-20 words, cut-the-noise style
- annotations: 1-3 verbatim or near-verbatim quotes; empty list if none available
- category: pick exactly one of the 5 options
- tags: 3-7 specific, lowercase tags (e.g. "llms", "fine-tuning", "rag", "computer-vision", "open-source")
- practical_takeaway: one concrete action sentence, 10-25 words, direct and specific
- audience_scores: all 5 roles, values 0.0-1.0 reflecting relevance to each role
"""


class GeminiFatalError(Exception):
    """Raised for errors that should abort all enrichment immediately."""
    pass


def _get_gemini_client():
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key, transport="rest")
        return genai
    except ImportError:
        logger.error("google-generativeai not installed")
        return None


def _get_openai_client():
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=settings.openai_api_key)
    except ImportError:
        logger.error("openai not installed")
        return None


def _classify_error(exc: Exception) -> str:
    """
    Classify a Gemini API exception.
    Returns: "quota" | "model_not_found" | "auth" | "transient" | "unknown"
    """
    if isinstance(exc, google.api_core.exceptions.NotFound):
        return "model_not_found"
    if isinstance(exc, (google.api_core.exceptions.PermissionDenied,
                        google.api_core.exceptions.Unauthenticated)):
        return "auth"
    if isinstance(exc, google.api_core.exceptions.ResourceExhausted):
        return "quota"
    if isinstance(exc, (google.api_core.exceptions.ServiceUnavailable,
                        google.api_core.exceptions.InternalServerError)):
        return "transient"
    # Also catch gRPC-level resource exhausted by message content
    msg = str(exc).lower()
    if "resource_exhausted" in msg or "quota" in msg or "429" in msg:
        return "quota"
    if "not found" in msg or "404" in msg:
        return "model_not_found"
    if "api_key_invalid" in msg or "api key expired" in msg:
        return "auth"
    return "unknown"


def _call_openai(prompt: str) -> dict:
    """Call OpenAI gpt-4o-mini as enrichment provider."""
    client = _get_openai_client()
    if not client:
        raise GeminiFatalError("OpenAI client unavailable — check OPENAI_API_KEY")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return json.loads(resp.choices[0].message.content)


def _probe_gemini() -> None:
    """
    Make a minimal test call to verify the API key and model are working.
    Raises GeminiFatalError with a clear message on any non-transient failure.
    """
    genai = _get_gemini_client()
    if not genai:
        raise GeminiFatalError("google-generativeai package is not installed")

    try:
        model = genai.GenerativeModel(settings.gemini_model)
        # Use generate_content (not count_tokens) so we detect generation quota exhaustion.
        # count_tokens uses a different endpoint that doesn't consume RPD/RPM quota.
        model.generate_content(
            "hi",
            generation_config=genai.GenerationConfig(max_output_tokens=1),
        )
        logger.info(f"Gemini probe OK — using model '{settings.gemini_model}'")
    except Exception as exc:
        kind = _classify_error(exc)
        if kind == "model_not_found":
            raise GeminiFatalError(
                f"Model '{settings.gemini_model}' not found for this API key. "
                f"Check GEMINI_MODEL in your .env. "
                f"Available models can be listed with: "
                f"python -c \"import google.generativeai as g; g.configure(api_key='KEY'); "
                f"[print(m.name) for m in g.list_models()]\""
            ) from exc
        if kind == "auth":
            raise GeminiFatalError(
                f"Invalid or unauthorized API key. Check GEMINI_API_KEY in your .env."
            ) from exc
        if kind == "quota":
            raise GeminiFatalError(
                f"Gemini API quota exhausted. "
                f"Free-tier resets at midnight UTC. "
                f"Check usage at https://ai.dev/rate-limit"
            ) from exc
        # Transient / unknown — don't block enrichment, log a warning
        logger.warning(f"Gemini probe returned a transient error (will attempt enrichment anyway): {exc}")


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors that warrant a retry in _call_gemini."""
    if isinstance(exc, (google.api_core.exceptions.ResourceExhausted,
                        google.api_core.exceptions.ServiceUnavailable)):
        return True
    if isinstance(exc, (ssl.SSLError, socket.error, ConnectionError,
                        RequestsSSLError, RequestsConnectionError)):
        return True
    # GeminiFatalError must NOT be retried
    if isinstance(exc, GeminiFatalError):
        return False
    # Catch-all: SSL/EOF/connection-reset surfaced through gRPC or httpx
    msg = str(exc).lower()
    if "ssl" in msg or "eof" in msg:
        return True
    if "connection" in msg and "reset" in msg:
        return True
    return False


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=10, max=60),
    retry=retry_if_exception(_is_retryable),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _call_gemini(prompt: str) -> dict:
    genai = _get_gemini_client()
    if not genai:
        raise GeminiFatalError("Gemini client unavailable")

    try:
        model = genai.GenerativeModel(settings.gemini_model)
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        kind = _classify_error(exc)
        if kind in ("model_not_found", "auth"):
            raise GeminiFatalError(str(exc)) from exc
        raise  # let tenacity handle transient/quota errors

    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _enrich_one(article: Article, session: Session, use_openai: bool = False) -> bool:
    """
    Enrich a single article via Gemini or OpenAI.
    Returns True on success.
    Raises GeminiFatalError if the error should stop all enrichment.
    """
    prompt = ENRICHMENT_PROMPT.format(
        title=article.title,
        source=article.source_name,
        content=article.title[:2000],
    )

    try:
        result = _call_openai(prompt) if use_openai else _call_gemini(prompt)
    except GeminiFatalError:
        raise  # propagate up to abort the whole run
    except Exception as exc:
        logger.error(f"Enrichment failed for article {article.id} (will skip): {exc}")
        article.is_enriched = -1
        session.commit()
        return False

    article.summary = result.get("summary", "")
    article.summary_bullets = result.get("summary_bullets", [])
    article.annotations = result.get("annotations", [])
    article.why_it_matters = result.get("why_it_matters", "")
    article.practical_takeaway = result.get("practical_takeaway", "")
    article.category = result.get("category", "Industry News")
    tags = result.get("tags", [])
    article.tags = [t.lower().strip() for t in tags if isinstance(t, str)]
    article.audience_scores = result.get("audience_scores", {})
    article.is_enriched = 1

    session.commit()
    return True


async def enrich_articles(
    saved_ids: list[int],
    force_provider: str = "auto",
    run_id=None,
    target_date: Optional[date] = None,
    date_idx: int = 0,
    dates_total: int = 1,
    running_totals: Optional[dict] = None,
) -> int:
    """
    Enrich articles by ID using staggered concurrent requests.
    Returns count of successfully enriched articles.

    force_provider: "auto" (default) | "gemini" | "openai"
      - "gemini": probe Gemini; if unavailable, return 0 (no fallback)
      - "openai": use OpenAI directly
      - "auto": probe Gemini, fall back to OpenAI if unavailable
    """
    if not saved_ids:
        return 0

    if running_totals is None:
        running_totals = {"fetched": 0, "new": 0, "saved": 0, "enriched": 0}

    # Determine which provider to use
    use_openai = False

    if force_provider == "gemini":
        try:
            _probe_gemini()
            logger.info("Enrichment provider: Gemini (forced)")
        except GeminiFatalError as exc:
            logger.error(f"Gemini unavailable ({exc}) — aborting (force_provider='gemini', no fallback)")
            return 0
    elif force_provider == "openai":
        logger.info("Enrichment provider: OpenAI (forced)")
        use_openai = True
    else:  # "auto"
        if settings.gemini_api_key:
            try:
                _probe_gemini()
                logger.info("Enrichment provider: Gemini")
            except GeminiFatalError as exc:
                logger.warning(f"Gemini unavailable ({exc})")
                if settings.openai_api_key:
                    logger.info("Enrichment provider: OpenAI (Gemini fallback)")
                    use_openai = True
                else:
                    logger.error("No working enrichment provider available — aborting")
                    return 0
        elif settings.openai_api_key:
            logger.info("Enrichment provider: OpenAI")
            use_openai = True
        else:
            logger.warning("No API keys set (GEMINI_API_KEY or OPENAI_API_KEY) — skipping enrichment")
            return 0

    # Re-enrich any pending articles left from a prior crash for this date
    pending_ids: list[int] = []
    if target_date is not None:
        with Session(sync_engine) as s:
            pending_ids = list(s.scalars(
                select(Article.id).where(
                    Article.is_enriched == 0,
                    Article.id.notin_(saved_ids),
                    Article.digest_date == target_date,
                )
            ).all())
        if pending_ids:
            logger.info(f"[{target_date}] Found {len(pending_ids)} pending articles from prior run — re-enriching")

    all_ids = saved_ids + pending_ids

    # Stagger interval: 1s at 60 RPM paid tier; 4s at 15 RPM free tier
    rate_interval = 60.0 / settings.enrichment_rate_rpm

    lock = asyncio.Lock()
    enriched_count = 0
    abort_flag = asyncio.Event()

    sem = _get_rate_sem()

    async def _track(article_id: int) -> bool:
        nonlocal enriched_count
        if abort_flag.is_set():
            return False

        async with sem:
            if abort_flag.is_set():
                return False

            def _work():
                with Session(sync_engine) as s:
                    article = s.get(Article, article_id)
                    if article is None:
                        return False
                    try:
                        return _enrich_one(article, s, use_openai=use_openai)
                    except GeminiFatalError:
                        raise

            try:
                ok = await asyncio.to_thread(_work)
            except GeminiFatalError as exc:
                logger.error(f"Fatal enrichment error — aborting all remaining slots: {exc}")
                abort_flag.set()
                return False
            except Exception as exc:
                logger.error(f"Unexpected error enriching article {article_id}: {exc}")
                return False

            await asyncio.sleep(rate_interval)

        if ok:
            async with lock:
                enriched_count += 1
                _update_progress_enriching(
                    run_id, target_date, date_idx, dates_total,
                    running_totals, enriched_count, len(all_ids),
                )
            logger.info(f"Enriched article {article_id} ({enriched_count}/{len(all_ids)})")
        return bool(ok)

    results = await asyncio.gather(
        *[_track(aid) for aid in all_ids],
        return_exceptions=True,
    )

    enriched_ids = [
        aid for aid, res in zip(all_ids, results)
        if res is True
    ]

    # Compute related articles once, after all enrichment for this date is done
    with Session(sync_engine) as s:
        _compute_related(s, enriched_ids)

    return len(enriched_ids)


async def enrich_failed_articles(
    date_from: date,
    date_to: date,
    run_id: int,
) -> int:
    """Query all is_enriched=-1 articles in the date range and re-enrich them."""
    with Session(sync_engine) as s:
        failed_ids = list(s.scalars(
            select(Article.id).where(
                Article.is_enriched == -1,
                Article.digest_date >= date_from,
                Article.digest_date <= date_to,
            )
        ).all())

    if not failed_ids:
        logger.info(f"retry_failed: no failed articles in {date_from}–{date_to}")
        return 0

    logger.info(f"retry_failed: re-enriching {len(failed_ids)} articles ({date_from}–{date_to})")
    # Reset to pending so _enrich_one can overwrite them
    with Session(sync_engine) as s:
        s.execute(
            update(Article)
            .where(Article.id.in_(failed_ids))
            .values(is_enriched=0)
        )
        s.commit()

    return await enrich_articles(
        saved_ids=failed_ids,
        run_id=run_id,
        running_totals={"fetched": 0, "new": 0, "saved": 0, "enriched": 0},
    )


async def enrich_pending_articles(
    run_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> int:
    """Query all is_enriched IS NULL or = 0 articles and enrich them."""
    with Session(sync_engine) as s:
        stmt = select(Article.id).where(
            or_(Article.is_enriched.is_(None), Article.is_enriched == 0)
        )
        if date_from:
            stmt = stmt.where(Article.digest_date >= date_from)
        if date_to:
            stmt = stmt.where(Article.digest_date <= date_to)
        pending_ids = list(s.scalars(stmt).all())

    if not pending_ids:
        logger.info("enrich_pending: no pending articles found")
        return 0

    logger.info(f"enrich_pending: enriching {len(pending_ids)} articles")
    return await enrich_articles(
        saved_ids=pending_ids,
        run_id=run_id,
        running_totals={"fetched": 0, "new": 0, "saved": 0, "enriched": 0},
    )


def _update_progress_enriching(
    run_id, target_date, date_idx, dates_total, running_totals, enriched_so_far, total_to_enrich
):
    """Helper to push enrichment progress without importing pipeline (avoids circular import)."""
    if run_id is None:
        return
    from sqlalchemy.orm import Session as _Session
    from sqlalchemy import update as sa_update
    from backend.db import sync_engine as _engine
    from backend.db.models import PipelineRun
    with _Session(_engine) as session:
        session.execute(
            sa_update(PipelineRun).where(PipelineRun.id == run_id).values(
                progress={
                    "stage": "enriching",
                    "current_date": str(target_date) if target_date else None,
                    "dates_completed": date_idx,
                    "dates_total": dates_total,
                    "fetched": running_totals.get("fetched", 0),
                    "new": running_totals.get("new", 0),
                    "saved": running_totals.get("saved", 0),
                    "enriched": running_totals.get("enriched", 0) + enriched_so_far,
                    "total_to_enrich": total_to_enrich,
                }
            )
        )
        session.commit()


def _compute_related(session: Session, article_ids: list[int]) -> None:
    """For each article, compute top 3 related articles by tag/category overlap."""
    from datetime import date, timedelta

    if not article_ids:
        return

    cutoff = date.today() - timedelta(days=30)
    recent = session.execute(
        select(Article).where(
            Article.digest_date >= cutoff,
            Article.is_enriched == 1,
        )
    ).scalars().all()

    recent_by_id = {a.id: a for a in recent}

    for article_id in article_ids:
        article = recent_by_id.get(article_id)
        if not article or not article.tags:
            continue

        scores = []
        art_tags = set(article.tags or [])
        for other in recent:
            if other.id == article.id:
                continue
            other_tags = set(other.tags or [])
            tag_sim = len(art_tags & other_tags) / max(len(art_tags | other_tags), 1)
            cat_bonus = 0.3 if other.category == article.category else 0.0
            scores.append((other.id, tag_sim + cat_bonus))

        scores.sort(key=lambda x: x[1], reverse=True)
        article.related_article_ids = [s[0] for s in scores[:3]]

    session.commit()
