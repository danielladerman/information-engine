"""Configuration loader — reads config.yaml and .env, exposes typed settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass
class ResearchConfig:
    tavily_model: str = "mini"
    deep_follow_up_queries: int = 6
    tavily_search_depth: str = "advanced"
    max_results_per_query: int = 5
    extract_chunks_per_source: int = 3
    extract_score_threshold: float = 0.5


@dataclass
class BusinessContext:
    description: str = "AI transformation consulting for SMBs (5-100 employees)"
    target_industries: list[str] = field(default_factory=lambda: [
        "Professional Services", "E-commerce", "Local Services",
        "B2B SaaS", "Healthcare", "Legal", "Agencies",
    ])
    scoring_note: str = "Score higher for insights directly applicable to selling and delivering AI consulting to small businesses"


@dataclass
class NotionConfig:
    auto_create_db: bool = True
    knowledge_base_id: str = ""
    parent_page_id: str = ""
    min_relevance_for_sync: float = 0.5


@dataclass
class ModelsConfig:
    synthesis: str = "claude-sonnet-4-5-20250929"
    ask: str = "claude-sonnet-4-5-20250929"


@dataclass
class APIKeys:
    anthropic: str = ""
    tavily: str = ""
    notion: str = ""


@dataclass
class Config:
    research: ResearchConfig = field(default_factory=ResearchConfig)
    business_context: BusinessContext = field(default_factory=BusinessContext)
    notion: NotionConfig = field(default_factory=NotionConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    api_keys: APIKeys = field(default_factory=APIKeys)
    domains: list[str] = field(default_factory=lambda: [
        "marketing", "growth", "psychology", "operations",
        "pricing", "voice", "industry", "sales", "leadership",
    ])
    database_path: str = "information_engine.db"
    log_level: str = "INFO"
    log_file: str = "logs/information_engine.log"


def _dict_to_dataclass(cls, data: dict[str, Any]):
    """Convert a dict to a dataclass, ignoring unknown keys."""
    if not data:
        return cls()
    valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_keys}
    return cls(**filtered)


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from YAML file and environment variables."""
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")

    if config_path is None:
        config_path = project_root / "config.yaml"
    config_path = Path(config_path)

    raw: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    config = Config(
        research=_dict_to_dataclass(ResearchConfig, raw.get("research", {})),
        business_context=_dict_to_dataclass(BusinessContext, raw.get("business_context", {})),
        notion=_dict_to_dataclass(NotionConfig, raw.get("notion", {})),
        models=_dict_to_dataclass(ModelsConfig, raw.get("models", {})),
        domains=raw.get("domains", [
            "marketing", "growth", "psychology", "operations",
            "pricing", "voice", "industry", "sales", "leadership",
        ]),
        database_path=raw.get("database", {}).get("path", "information_engine.db"),
        log_level=raw.get("logging", {}).get("level", "INFO"),
        log_file=raw.get("logging", {}).get("file", "logs/information_engine.log"),
    )

    config.api_keys = APIKeys(
        anthropic=os.getenv("ANTHROPIC_API_KEY", ""),
        tavily=os.getenv("TAVILY_API_KEY", ""),
        notion=os.getenv("NOTION_API_KEY", ""),
    )

    return config
