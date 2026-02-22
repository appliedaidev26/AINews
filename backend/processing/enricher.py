"""AI enrichment using Gemini API."""
import json
import logging
import time
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import google.api_core.exceptions
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.config import settings
from backend.db import sync_engine
from backend.db.models import Article

logger = logging.getLogger(__name__)

ENRICHMENT_PROMPT = """You are an expert AI/ML analyst. Analyze the following article and return a JSON object with exactly these fields:

Article Title: {title}
Source: {source}
Content/Abstract: {content}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "summary_bullets": [
    "Bullet 1 — key finding or announcement (start with action verb)",
    "Bullet 2",
    "Bullet 3",
    "Bullet 4",
    "Bullet 5"
  ],
  "annotations": [
    "Most insightful or surprising verbatim quote or claim from the article",
    "Second notable quote (omit if no strong quotes available)"
  ],
  "why_it_matters": "1-2 sentences explaining significance for ML engineers and engineering leaders",
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
- summary_bullets: exactly 5 bullets, each 10-20 words
- annotations: 1-3 verbatim or near-verbatim quotes; empty list if none available
- category: pick exactly one of the 5 options
- tags: 3-7 specific, lowercase tags (e.g. "llms", "fine-tuning", "rag", "computer-vision", "open-source")
- audience_scores: all 5 roles, values 0.0-1.0 reflecting how relevant this is to each role
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


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=10, max=60),
    retry=retry_if_exception_type(
        (google.api_core.exceptions.ResourceExhausted,
         google.api_core.exceptions.ServiceUnavailable)
    ),
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

    article.summary_bullets = result.get("summary_bullets", [])
    article.annotations = result.get("annotations", [])
    article.why_it_matters = result.get("why_it_matters", "")
    article.category = result.get("category", "Industry News")
    tags = result.get("tags", [])
    article.tags = [t.lower().strip() for t in tags if isinstance(t, str)]
    article.audience_scores = result.get("audience_scores", {})
    article.is_enriched = 1

    session.commit()
    return True


async def enrich_articles(saved_ids: list[int], force_provider: str = "auto", run_id=None, fetched=0, new=0, saved_count=0) -> int:
    """
    Enrich articles by ID. Returns count of successfully enriched articles.
    Aborts immediately if the API key, model, or quota is invalid.

    force_provider: "auto" (default) | "gemini" | "openai"
      - "gemini": probe Gemini; if unavailable, return 0 (no fallback)
      - "openai": use OpenAI directly
      - "auto": probe Gemini, fall back to OpenAI if unavailable
    """
    if not saved_ids:
        return 0

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

    enriched_count = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 3  # abort if this many articles fail in a row (quota exhausted, etc.)
    batch_size = settings.enrichment_batch_size

    with Session(sync_engine) as session:
        for i in range(0, len(saved_ids), batch_size):
            batch_ids = saved_ids[i : i + batch_size]
            articles = session.execute(
                select(Article).where(Article.id.in_(batch_ids))
            ).scalars().all()

            for article in articles:
                try:
                    success = _enrich_one(article, session, use_openai=use_openai)
                except GeminiFatalError as exc:
                    logger.error(f"Fatal Gemini error — stopping enrichment run: {exc}")
                    return enriched_count

                if success:
                    enriched_count += 1
                    consecutive_failures = 0
                    logger.info(f"Enriched article {article.id} ({enriched_count}/{len(saved_ids)})")
                    if run_id is not None:
                        from backend.ingestion.pipeline import _update_progress
                        _update_progress(run_id, {"stage": "enriching", "fetched": fetched, "new": new, "saved": saved_count, "enriched": enriched_count, "total_to_enrich": len(saved_ids)})
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            f"{consecutive_failures} consecutive enrichment failures — "
                            f"API key may be invalid, quota may be exhausted, or model unreachable. "
                            f"Stopping run. ({enriched_count} articles enriched before abort)"
                        )
                        return enriched_count

                time.sleep(10)  # stay under free-tier 15 RPM limit

            _compute_related(session, batch_ids)

    return enriched_count


def _compute_related(session: Session, article_ids: list[int]) -> None:
    """For each article, compute top 3 related articles by tag/category overlap."""
    from datetime import date, timedelta

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
