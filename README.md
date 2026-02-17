# Information Engine

> On-demand business intelligence. Research any topic, get a structured playbook with actionable insights, stored forever and synced to Notion.

## What It Does

```
You: info-engine research "how to price AI consulting services"
     │
     ▼
  1. RESEARCH — Tavily Research API scours the web
  2. SYNTHESIZE — Claude reads everything, scores relevance
     to your business, extracts insights + action items
  3. STORE — SQLite (full-text search) + Notion sync
     │
     ▼
Output: Structured playbook you can search, browse, and act on
```

Every playbook gets a **relevance score** weighted toward AI consulting for SMBs — so you always know what matters most.

## Quick Start

```bash
# Install
cd information-engine
pip install -e .

# Set up API keys in .env
cp .env.example .env
# Add: ANTHROPIC_API_KEY, TAVILY_API_KEY, NOTION_API_KEY

# Initialize the database
info-engine init

# Research a topic
info-engine research "how to price AI consulting services"

# Deep research (more sources, follow-up searches, content extraction)
info-engine research "cognitive biases in B2B sales" --deep

# Sync to Notion
info-engine sync
```

## Commands

| Command | What It Does |
|---------|-------------|
| `info-engine research "topic"` | Research a topic → structured playbook |
| `info-engine research "topic" --deep` | Deep mode: Research API + follow-up searches + content extraction |
| `info-engine browse` | List all playbooks (most recent first) |
| `info-engine browse --domain marketing` | Filter by domain |
| `info-engine browse --search "pricing"` | Full-text search across all playbooks |
| `info-engine view 3` | View a full playbook with insights, actions, sources |
| `info-engine ask "what do we know about lead gen?"` | Ask a question against your knowledge base |
| `info-engine sync` | Push new playbooks to Notion Knowledge Base |
| `info-engine status` | Overview: playbook count, domains, costs |
| `info-engine costs` | Detailed API cost breakdown |

## Research Modes

**Standard** (`info-engine research "topic"`):
1. Tavily Research API (`mini` model, ~30s) — web-scale research with citations
2. Claude synthesis — structured playbook with relevance scoring

**Deep** (`info-engine research "topic" --deep`):
1. Tavily Research API (`pro` model) — multi-agent deep research
2. Tavily Search (`advanced`) — 6 follow-up queries from different angles
3. Tavily Extract — full content from top-scoring URLs
4. Claude synthesis with all combined results — richer, more detailed playbook

## Knowledge Domains

Playbooks are auto-categorized into: `marketing`, `growth`, `psychology`, `operations`, `pricing`, `voice`, `industry`, `sales`, `leadership`

## Architecture

```
information_engine/
├── cli.py              # Typer CLI — all commands
├── config.py           # YAML + .env config loader
├── database.py         # SQLite schema + FTS5 full-text search
├── researcher.py       # Research pipeline (Tavily Research + deep dive)
├── synthesizer.py      # Claude synthesis via tool_use
├── schemas.py          # Pydantic models (PlaybookOutput, AskResponse)
├── prompts.py          # System prompts for synthesis + ask
├── cost_tracker.py     # API cost tracking
├── logger.py           # Rich logging
└── sync/
    └── notion_sync.py  # Auto-create KB database + push playbooks
```

## Notion Integration

Playbooks sync to a **Knowledge Base** database in Notion under [AI Transformation HQ](https://www.notion.so/309a28b07c4d8144bed0f05ac5cec892). Each playbook becomes a full Notion page with:
- Properties: Name, Domain, Topic, Relevance score, Mode, Date
- Content blocks: Summary, Key Insights (bullets), Action Items (checkboxes), Sources

## How It Connects

Part of the [Second Brain](https://github.com/danielladerman/secondbrain) ecosystem:
- **Information Engine** (this) → builds knowledge that feeds content creation and sharpens outreach targeting
- **[Outreach Engine](https://github.com/danielladerman/outreach-engine)** → finds prospects showing buying signals
- **[Content Engine](https://github.com/danielladerman/content-engine)** → creates LinkedIn + Instagram content from insights

## Stack

- **Research:** [Tavily](https://tavily.com/) (Research API, Search API, Extract API)
- **Synthesis:** [Claude](https://anthropic.com/) (Sonnet 4.5) via tool_use for structured output
- **Storage:** SQLite with FTS5 full-text search
- **Sync:** Notion API
- **CLI:** Typer + Rich
