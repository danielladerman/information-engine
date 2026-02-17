"""Notion sync — auto-creates Knowledge Base database and pushes playbooks."""

from __future__ import annotations

import json
import sqlite3

from notion_client import Client as NotionClient

from ..config import Config
from ..database import get_unsynced_playbooks, record_notion_sync
from ..logger import get_logger

logger = get_logger()


class NotionSync:
    """Manages syncing playbooks to a Notion Knowledge Base database."""

    def __init__(self, db: sqlite3.Connection, config: Config):
        self.db = db
        self.config = config
        self.client = NotionClient(auth=config.api_keys.notion)
        self._db_id: str | None = config.notion.knowledge_base_id or None

    def ensure_database(self) -> str:
        """Ensure the Knowledge Base database exists in Notion. Creates if needed."""
        if self._db_id:
            return self._db_id

        if not self.config.notion.auto_create_db:
            raise RuntimeError(
                "No knowledge_base_id configured and auto_create_db is disabled. "
                "Set notion.knowledge_base_id in config.yaml or enable auto_create_db."
            )

        # Search for existing database
        results = self.client.search(query="Knowledge Base")
        for result in results.get("results", []):
            if result.get("object") in ("database", "data_source") and result.get("title"):
                title_parts = result["title"]
                title_text = "".join(t.get("plain_text", "") for t in title_parts)
                if title_text == "Knowledge Base":
                    self._db_id = result["id"]
                    logger.info(f"Found existing Knowledge Base: {self._db_id}")
                    return self._db_id

        # Create new database
        logger.info("Creating Knowledge Base database in Notion...")
        parent = {}
        if self.config.notion.parent_page_id:
            parent = {"type": "page_id", "page_id": self.config.notion.parent_page_id}
        else:
            # Create as a standalone page in the workspace
            parent = {"type": "page_id", "page_id": self._get_workspace_page()}

        new_db = self.client.databases.create(
            parent=parent,
            title=[{"type": "text", "text": {"content": "Knowledge Base"}}],
            properties={
                "Name": {"title": {}},
                "Domain": {
                    "select": {
                        "options": [
                            {"name": d, "color": c}
                            for d, c in zip(
                                ["marketing", "growth", "psychology", "operations",
                                 "pricing", "voice", "industry", "sales", "leadership"],
                                ["blue", "green", "purple", "orange",
                                 "yellow", "pink", "red", "gray", "brown"],
                            )
                        ]
                    }
                },
                "Topic": {"rich_text": {}},
                "Relevance": {"number": {"format": "percent"}},
                "Mode": {
                    "select": {
                        "options": [
                            {"name": "standard", "color": "blue"},
                            {"name": "deep", "color": "green"},
                        ]
                    }
                },
                "Date": {"date": {}},
            },
        )

        self._db_id = new_db["id"]
        logger.info(f"Created Knowledge Base: {self._db_id}")
        return self._db_id

    def sync_playbooks(self) -> dict:
        """Sync unsynced playbooks to Notion. Returns stats."""
        db_id = self.ensure_database()
        min_relevance = self.config.notion.min_relevance_for_sync
        playbooks = get_unsynced_playbooks(self.db, min_relevance)

        if not playbooks:
            return {"synced": 0, "skipped": 0}

        synced = 0
        skipped = 0

        for pb in playbooks:
            try:
                page = self._create_playbook_page(db_id, pb)
                record_notion_sync(self.db, pb["id"], page["id"])
                synced += 1
                logger.info(f"  Synced: {pb['title']}")
            except Exception as e:
                skipped += 1
                logger.warning(f"  Failed to sync '{pb['title']}': {e}")

        return {"synced": synced, "skipped": skipped}

    def _create_playbook_page(self, db_id: str, playbook: dict) -> dict:
        """Create a Notion page for a playbook."""
        # Build page content blocks
        children = []

        # Summary
        children.append(_heading_block("Summary"))
        children.extend(_paragraph_blocks(playbook["summary"]))

        # Key Insights
        insights = playbook.get("key_insights", [])
        if isinstance(insights, str):
            insights = json.loads(insights)
        if insights:
            children.append(_heading_block("Key Insights"))
            for insight in insights:
                children.append(_bulleted_list_block(insight))

        # Action Items
        actions = playbook.get("action_items", [])
        if isinstance(actions, str):
            actions = json.loads(actions)
        if actions:
            children.append(_heading_block("Action Items"))
            for action in actions:
                children.append(_to_do_block(action))

        # Sources
        sources = playbook.get("sources", [])
        if isinstance(sources, str):
            sources = json.loads(sources)
        if sources:
            children.append(_heading_block("Sources"))
            for source in sources:
                url = source.get("url", "") if isinstance(source, dict) else str(source)
                title = source.get("title", url) if isinstance(source, dict) else url
                children.append(_bulleted_list_block(f"{title}: {url}"))

        page = self.client.pages.create(
            parent={"database_id": db_id},
            properties={
                "Name": {"title": [{"text": {"content": playbook["title"][:100]}}]},
                "Domain": {"select": {"name": playbook["domain"]}},
                "Topic": {"rich_text": [{"text": {"content": playbook["topic"][:200]}}]},
                "Relevance": {"number": playbook["relevance_score"]},
                "Mode": {"select": {"name": playbook.get("mode", "standard")}},
                "Date": {"date": {"start": playbook["created_at"][:10]}},
            },
            children=children[:100],  # Notion limit
        )

        return page

    def _get_workspace_page(self) -> str:
        """Find or create a parent page for the Knowledge Base."""
        # Search for an existing "Information Engine" page
        results = self.client.search(
            query="Information Engine",
            filter={"property": "object", "value": "page"},
        )
        for result in results.get("results", []):
            props = result.get("properties", {})
            title_prop = props.get("title", {})
            if title_prop and isinstance(title_prop, dict):
                title_items = title_prop.get("title", [])
            else:
                title_items = result.get("properties", {}).get("title", {}).get("title", [])
            title_text = "".join(t.get("plain_text", "") for t in title_items) if title_items else ""
            if "Information Engine" in title_text:
                return result["id"]

        # Create a new parent page
        page = self.client.pages.create(
            parent={"workspace": True},
            properties={
                "title": [{"text": {"content": "Information Engine"}}],
            },
        )
        logger.info(f"Created 'Information Engine' parent page: {page['id']}")
        return page["id"]


# --- Notion block helpers ---

def _heading_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _paragraph_blocks(text: str) -> list[dict]:
    """Split long text into paragraph blocks (Notion limit: 2000 chars per block)."""
    blocks = []
    for chunk in _chunk_text(text, 2000):
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
            },
        })
    return blocks


def _bulleted_list_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
        },
    }


def _to_do_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "rich_text": [{"type": "text", "text": {"content": text[:2000]}}],
            "checked": False,
        },
    }


def _chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks of max_len, preferring paragraph breaks."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to break at paragraph
        idx = text.rfind("\n\n", 0, max_len)
        if idx == -1:
            idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            idx = text.rfind(" ", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip()

    return chunks
