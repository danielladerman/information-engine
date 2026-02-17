"""Track API costs per model, per run, cumulative."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

# Approximate pricing per 1M tokens (early 2026)
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "tavily-research-pro": {"per_call": 0.10},
    "tavily-research-mini": {"per_call": 0.05},
    "tavily-search-advanced": {"per_call": 0.02},
    "tavily-search-basic": {"per_call": 0.01},
    "tavily-extract": {"per_call": 0.01},
}


def estimate_cost(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    """Estimate USD cost for a given API call."""
    pricing = MODEL_PRICING.get(model)
    if pricing and "per_call" in pricing:
        return pricing["per_call"]
    if pricing:
        input_cost = (input_tokens / 1_000_000) * pricing.get("input", 3.00)
        output_cost = (output_tokens / 1_000_000) * pricing.get("output", 15.00)
        return round(input_cost + output_cost, 6)
    # Default to Sonnet pricing
    input_cost = (input_tokens / 1_000_000) * 3.00
    output_cost = (output_tokens / 1_000_000) * 15.00
    return round(input_cost + output_cost, 6)


def record_cost(
    db: sqlite3.Connection,
    operation: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Record an API cost to the database. Returns estimated cost."""
    cost = estimate_cost(model, input_tokens, output_tokens)
    db.execute(
        """INSERT INTO api_costs (operation, model, input_tokens, output_tokens, estimated_cost_usd, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (operation, model, input_tokens, output_tokens, cost, datetime.now(UTC).isoformat()),
    )
    db.commit()
    return cost


def get_daily_cost(db: sqlite3.Connection, date: str | None = None) -> float:
    """Get total estimated cost for a given date (default: today)."""
    if date is None:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
    row = db.execute(
        "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_costs WHERE DATE(recorded_at) = ?",
        (date,),
    ).fetchone()
    return row[0] if row else 0.0


def get_monthly_cost(db: sqlite3.Connection, month: str | None = None) -> float:
    """Get total estimated cost for a given month (default: current). Format: YYYY-MM."""
    if month is None:
        month = datetime.now(UTC).strftime("%Y-%m")
    row = db.execute(
        "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM api_costs WHERE STRFTIME('%Y-%m', recorded_at) = ?",
        (month,),
    ).fetchone()
    return row[0] if row else 0.0


def get_cost_breakdown(db: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Get cost breakdown by operation for the last N days."""
    rows = db.execute(
        """SELECT operation, model, COUNT(*) as calls,
                  SUM(input_tokens) as total_input,
                  SUM(output_tokens) as total_output,
                  SUM(estimated_cost_usd) as total_cost
           FROM api_costs
           WHERE recorded_at >= DATETIME('now', ?)
           GROUP BY operation, model
           ORDER BY total_cost DESC""",
        (f"-{days} days",),
    ).fetchall()
    return [
        {
            "operation": r[0],
            "model": r[1],
            "calls": r[2],
            "total_input_tokens": r[3] or 0,
            "total_output_tokens": r[4] or 0,
            "total_cost": r[5] or 0,
        }
        for r in rows
    ]
