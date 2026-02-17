"""Research pipeline — orchestrates Tavily Research + optional deep dive + Claude synthesis."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from tavily import TavilyClient

from .config import Config
from .cost_tracker import record_cost
from .database import (
    complete_research_session,
    insert_playbook,
    start_research_session,
)
from .logger import get_logger
from .synthesizer import synthesize_playbook

logger = get_logger()


def run_research(db, config: Config, topic: str, deep: bool = False) -> dict:
    """Execute the full research pipeline on a topic.

    Standard mode:
        1. Tavily Research API (pro) → raw report
        2. Claude synthesis → structured playbook

    Deep mode:
        1. Tavily Research API (pro) → raw report
        2. Tavily Search (advanced) → follow-up queries from multiple angles
        3. Tavily Extract → deep content from top URLs
        4. Claude synthesis with all combined results
    """
    session_id = start_research_session(db, topic, mode="deep" if deep else "standard")
    total_cost = 0.0

    try:
        client = TavilyClient(api_key=config.api_keys.tavily)

        # --- Step 1: Tavily Research API ---
        # Use pro model for deep mode, configured model for standard
        tavily_model = "pro" if deep else config.research.tavily_model
        logger.info(f"Researching: {topic}")
        logger.info(f"Mode: {'deep' if deep else 'standard'} | Tavily model: {tavily_model}")

        research_result = _run_tavily_research(client, config, topic, model_override=tavily_model)
        total_cost += record_cost(
            db, "tavily_research", f"tavily-research-{tavily_model}",
        )

        research_content = research_result.get("content", "")
        research_sources = research_result.get("sources", [])
        tavily_request_id = research_result.get("request_id", "")

        logger.info(f"Research complete: {len(research_sources)} sources found")

        # --- Step 2 (deep mode): Follow-up searches + extraction ---
        deep_dive_content = None
        search_queries_used = []
        urls_extracted = []

        if deep:
            deep_dive_content, search_queries_used, urls_extracted, deep_cost = _run_deep_dive(
                db, client, config, topic, research_content
            )
            total_cost += deep_cost

        # --- Step 3: Claude synthesis ---
        logger.info("Synthesizing into playbook...")
        playbook, synthesis_cost = synthesize_playbook(
            db, config, topic, research_content, research_sources, deep_dive_content
        )
        total_cost += synthesis_cost

        # --- Step 4: Store ---
        playbook_id = insert_playbook(
            db,
            topic=topic,
            domain=playbook.domain,
            title=playbook.title,
            summary=playbook.summary,
            key_insights=playbook.key_insights,
            action_items=playbook.action_items,
            sources=[s.model_dump() for s in playbook.sources],
            relevance_score=playbook.relevance_score,
            research_data={"content": research_content, "sources": research_sources},
            deep_dive_data={"content": deep_dive_content} if deep_dive_content else None,
            mode="deep" if deep else "standard",
        )

        complete_research_session(
            db, session_id,
            playbook_id=playbook_id,
            tavily_research_id=tavily_request_id,
            search_queries=search_queries_used,
            urls_extracted=urls_extracted,
            cost_usd=total_cost,
        )

        return {
            "playbook_id": playbook_id,
            "title": playbook.title,
            "domain": playbook.domain,
            "relevance_score": playbook.relevance_score,
            "sources_count": len(playbook.sources),
            "insights_count": len(playbook.key_insights),
            "action_items_count": len(playbook.action_items),
            "cost_usd": total_cost,
            "mode": "deep" if deep else "standard",
        }

    except Exception as e:
        complete_research_session(db, session_id, cost_usd=total_cost, status="failed")
        logger.error(f"Research failed: {e}")
        raise


def _run_tavily_research(client: TavilyClient, config: Config, topic: str, model_override: str | None = None) -> dict:
    """Run Tavily Research API and poll until complete."""
    model = model_override or config.research.tavily_model
    result = client.research(
        input=topic,
        model=model,
    )

    # Research API is async — returns a request_id, then we poll
    if isinstance(result, dict) and result.get("status") in ("pending", "running", "in_progress"):
        request_id = result["request_id"]
        logger.info(f"Research in progress (ID: {request_id})... polling")
        max_polls = 60  # 5 min max
        for _ in range(max_polls):
            time.sleep(5)
            response = client.get_research(request_id)
            status = response.get("status", "unknown")
            if status == "completed":
                logger.info("Research completed")
                return _normalize_research_result(response, request_id)
            elif status == "failed":
                raise RuntimeError(f"Tavily research failed: {response.get('error', 'Unknown')}")
            logger.info(f"Still researching... ({status})")
        raise RuntimeError("Tavily research timed out after 5 minutes")

    # Some SDK versions may return completed results directly
    return _normalize_research_result(result, result.get("request_id", "") if isinstance(result, dict) else "")


def _normalize_research_result(result, request_id: str) -> dict:
    """Normalize Tavily Research API response into a consistent format."""
    if isinstance(result, str):
        # Some SDK versions return content as a plain string
        return {"content": result, "sources": _extract_urls_from_text(result), "request_id": request_id}

    if not isinstance(result, dict):
        return {"content": str(result), "sources": [], "request_id": request_id}

    content = result.get("content", result.get("output", ""))
    sources = result.get("sources", result.get("citations", []))
    rid = result.get("request_id", request_id)

    # If sources is empty but content has URLs, try to extract them
    if not sources and content:
        sources = _extract_urls_from_text(content)

    return {"content": content, "sources": sources, "request_id": rid}


def _extract_urls_from_text(text: str) -> list[dict]:
    """Extract URLs from text content (citations often appear as inline URLs)."""
    import re
    urls = re.findall(r'https?://[^\s\)\]]+', text)
    seen = set()
    sources = []
    for url in urls:
        url = url.rstrip(".,;:")
        if url not in seen:
            seen.add(url)
            sources.append({"url": url, "title": "", "snippet": ""})
    return sources


def _run_deep_dive(
    db, client: TavilyClient, config: Config, topic: str, research_content: str
) -> tuple[str, list[str], list[str], float]:
    """Run follow-up searches and extract top sources for deeper content."""
    cost = 0.0

    # Generate follow-up search queries from different angles
    queries = _generate_follow_up_queries(topic, config.research.deep_follow_up_queries)
    logger.info(f"Deep dive: running {len(queries)} follow-up searches")

    # Run searches
    all_results = []
    for query in queries:
        try:
            search_result = client.search(
                query=query,
                search_depth=config.research.tavily_search_depth,
                max_results=config.research.max_results_per_query,
            )
            cost += record_cost(
                db, "tavily_search", f"tavily-search-{config.research.tavily_search_depth}",
            )
            results = search_result.get("results", [])
            all_results.extend(results)
            logger.info(f"  Search: '{query[:60]}...' → {len(results)} results")
        except Exception as e:
            logger.warning(f"  Search failed for '{query[:40]}...': {e}")

    # Filter by score and deduplicate by URL
    seen_urls = set()
    top_urls = []
    for r in sorted(all_results, key=lambda x: x.get("score", 0), reverse=True):
        url = r.get("url", "")
        if url and url not in seen_urls and r.get("score", 0) >= config.research.extract_score_threshold:
            seen_urls.add(url)
            top_urls.append(url)
            if len(top_urls) >= 10:
                break

    # Extract content from top URLs
    extracted_content = ""
    urls_extracted = []
    if top_urls:
        logger.info(f"Deep dive: extracting content from {len(top_urls)} top URLs")
        try:
            extract_result = client.extract(
                urls=top_urls,
                query=topic,
                chunks_per_source=config.research.extract_chunks_per_source,
            )
            cost += record_cost(db, "tavily_extract", "tavily-extract")

            for item in extract_result.get("results", []):
                url = item.get("url", "")
                content = item.get("raw_content", "")
                if content:
                    extracted_content += f"\n\n--- Source: {url} ---\n{content}"
                    urls_extracted.append(url)

            failed = extract_result.get("failed_results", [])
            if failed:
                logger.warning(f"  {len(failed)} URLs failed extraction")

        except Exception as e:
            logger.warning(f"Extract failed: {e}")

    # Combine search snippets + extracted content
    search_snippets = ""
    for r in all_results[:20]:
        title = r.get("title", "")
        content = r.get("content", "")
        url = r.get("url", "")
        if content:
            search_snippets += f"\n\n### {title}\nSource: {url}\n{content}"

    deep_content = f"## Follow-up Search Results\n{search_snippets}"
    if extracted_content:
        deep_content += f"\n\n## Extracted Deep Content\n{extracted_content}"

    return deep_content, queries, urls_extracted, cost


def _generate_follow_up_queries(topic: str, num_queries: int) -> list[str]:
    """Generate diverse follow-up search queries for deep mode.

    These cover different angles of the topic to get comprehensive coverage.
    """
    # Base query variations
    angles = [
        f"{topic} best practices 2026",
        f"{topic} case studies examples",
        f"{topic} common mistakes to avoid",
        f"{topic} step by step guide",
        f"{topic} expert advice strategies",
        f"{topic} data statistics research",
        f"{topic} tools and frameworks",
        f"{topic} for consulting business",
    ]
    return angles[:num_queries]
