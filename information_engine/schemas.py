"""Pydantic models for structured output from synthesis and research."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Source(BaseModel):
    """A source used in the research."""

    url: str = Field(description="URL of the source")
    title: str = Field(default="", description="Title of the source page")
    snippet: str = Field(default="", description="Relevant excerpt from the source")


class PlaybookOutput(BaseModel):
    """Structured output from Claude synthesis."""

    title: str = Field(description="Clear, descriptive title for this knowledge entry")
    domain: str = Field(
        description="Knowledge domain: marketing, growth, psychology, operations, "
        "pricing, voice, industry, sales, or leadership"
    )
    summary: str = Field(
        description="2-3 paragraph synthesis of the findings. "
        "Should be actionable and specific, not generic."
    )
    key_insights: list[str] = Field(
        description="5-10 bullet-point insights — the most important takeaways"
    )
    action_items: list[str] = Field(
        description="3-7 concrete, specific action items you can execute based on these findings"
    )
    sources: list[Source] = Field(
        default_factory=list,
        description="Sources used, with URLs and relevant snippets"
    )
    relevance_score: float = Field(
        ge=0.0, le=1.0,
        description="How relevant this is to an AI consulting business targeting SMBs (0-1)"
    )


class AskResponse(BaseModel):
    """Structured output from the 'ask' feature."""

    answer: str = Field(description="Direct answer to the question based on existing knowledge")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How confident the answer is based on available knowledge (0-1)"
    )
    related_playbook_ids: list[int] = Field(
        default_factory=list,
        description="IDs of playbooks that informed this answer"
    )
    knowledge_gaps: list[str] = Field(
        default_factory=list,
        description="Topics you should research to get a more complete answer"
    )
