"""Claude synthesis — converts raw research into structured playbook entries."""

from __future__ import annotations

import json
import sqlite3

import anthropic

from .config import Config
from .cost_tracker import record_cost
from .logger import get_logger
from .prompts import SYNTHESIS_SYSTEM_PROMPT, ASK_SYSTEM_PROMPT, build_synthesis_prompt, build_ask_prompt
from .schemas import PlaybookOutput, AskResponse, Source

logger = get_logger()


def synthesize_playbook(
    db: sqlite3.Connection,
    config: Config,
    topic: str,
    research_content: str,
    research_sources: list[dict],
    deep_dive_content: str | None = None,
) -> tuple[PlaybookOutput, float]:
    """Use Claude to synthesize research into a structured playbook.

    Returns (PlaybookOutput, cost_usd).
    """
    client = anthropic.Anthropic(api_key=config.api_keys.anthropic)

    # Build source context from Tavily research sources
    sources_text = ""
    if research_sources:
        for s in research_sources:
            url = s.get("url", "") if isinstance(s, dict) else str(s)
            title = s.get("title", "") if isinstance(s, dict) else ""
            sources_text += f"\n- [{title}]({url})" if title else f"\n- {url}"

    full_research = research_content
    if sources_text:
        full_research += f"\n\n## Sources\n{sources_text}"

    user_prompt = build_synthesis_prompt(topic, full_research, deep_dive_content)

    # Use tool_use to get structured output
    tools = [_playbook_tool_schema()]

    response = client.messages.create(
        model=config.models.synthesis,
        max_tokens=4096,
        system=SYNTHESIS_SYSTEM_PROMPT,
        tools=tools,
        tool_choice={"type": "tool", "name": "create_playbook"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Track cost
    cost = record_cost(
        db, "claude_synthesis", config.models.synthesis,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    # Extract structured output from tool use
    playbook = _parse_tool_response(response, research_sources)

    return playbook, cost


def ask_knowledge_base(
    db: sqlite3.Connection,
    config: Config,
    question: str,
    knowledge_context: str,
) -> tuple[AskResponse, float]:
    """Use Claude to answer a question from the existing knowledge base.

    Returns (AskResponse, cost_usd).
    """
    client = anthropic.Anthropic(api_key=config.api_keys.anthropic)

    user_prompt = build_ask_prompt(question, knowledge_context)

    tools = [_ask_tool_schema()]

    response = client.messages.create(
        model=config.models.ask,
        max_tokens=4096,
        system=ASK_SYSTEM_PROMPT,
        tools=tools,
        tool_choice={"type": "tool", "name": "answer_question"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    cost = record_cost(
        db, "claude_ask", config.models.ask,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    ask_response = _parse_ask_response(response)

    return ask_response, cost


def _playbook_tool_schema() -> dict:
    """Tool schema for structured playbook output."""
    return {
        "name": "create_playbook",
        "description": "Create a structured playbook entry from research findings",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Clear, descriptive title for this knowledge entry",
                },
                "domain": {
                    "type": "string",
                    "enum": ["marketing", "growth", "psychology", "operations",
                             "pricing", "voice", "industry", "sales", "leadership"],
                    "description": "Knowledge domain category",
                },
                "summary": {
                    "type": "string",
                    "description": "2-3 paragraph synthesis of findings, actionable and specific",
                },
                "key_insights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "5-10 key insight bullet points",
                },
                "action_items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-7 concrete, specific action items",
                },
                "relevance_score": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Relevance to AI consulting business for SMBs (0-1)",
                },
            },
            "required": ["title", "domain", "summary", "key_insights", "action_items", "relevance_score"],
        },
    }


def _ask_tool_schema() -> dict:
    """Tool schema for structured ask response."""
    return {
        "name": "answer_question",
        "description": "Answer a question based on the knowledge base",
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "Direct answer to the question",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Confidence based on available knowledge (0-1)",
                },
                "related_playbook_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs of playbooks that informed this answer",
                },
                "knowledge_gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topics to research for a more complete answer",
                },
            },
            "required": ["answer", "confidence"],
        },
    }


def _parse_tool_response(response, research_sources: list[dict]) -> PlaybookOutput:
    """Parse Claude's tool_use response into a PlaybookOutput."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "create_playbook":
            data = block.input
            # Build sources from Tavily research sources
            sources = []
            for s in (research_sources or []):
                if isinstance(s, dict):
                    sources.append(Source(
                        url=s.get("url", ""),
                        title=s.get("title", ""),
                        snippet=s.get("content", s.get("snippet", "")),
                    ))
                elif isinstance(s, str):
                    sources.append(Source(url=s))

            return PlaybookOutput(
                title=data["title"],
                domain=data["domain"],
                summary=data["summary"],
                key_insights=_ensure_list(data.get("key_insights", [])),
                action_items=_ensure_list(data.get("action_items", [])),
                sources=sources,
                relevance_score=data.get("relevance_score", 0.5),
            )

    raise ValueError("No tool_use block found in Claude response")


def _parse_ask_response(response) -> AskResponse:
    """Parse Claude's tool_use response into an AskResponse."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "answer_question":
            data = block.input
            return AskResponse(
                answer=data["answer"],
                confidence=data.get("confidence", 0.5),
                related_playbook_ids=_ensure_list(data.get("related_playbook_ids", [])),
                knowledge_gaps=_ensure_list(data.get("knowledge_gaps", [])),
            )

    raise ValueError("No tool_use block found in Claude response")


def _ensure_list(value) -> list:
    """Ensure a value is a list. Handles cases where Claude returns a JSON string instead."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        # Strip any XML-like tags Claude might add
        import re
        value = re.sub(r'</?parameter>', '', value).strip()
        # Try parsing as JSON array
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
        # Try splitting by newlines if it looks like a list
        lines = [line.strip().lstrip("- ").strip('"').strip("'")
                 for line in value.split("\n") if line.strip()]
        return lines if lines else [value]
    return [value] if value else []
