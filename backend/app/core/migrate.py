"""Apply `backend/migrations/*.sql` in filename order, once each.

uv run python -m app.core.migrate
"""

import asyncio
from pathlib import Path

from psycopg import AsyncConnection

from app.core.config import get_settings

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


async def migrate() -> list[str]:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("RIO_HEALTH_DATABASE_URL is not set")
    applied: list[str] = []
    async with await AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(f"SET search_path TO {settings.db_schema}, public")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur = await conn.execute("SELECT name FROM schema_migrations")
        done = {row[0] for row in await cur.fetchall()}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            await conn.execute(path.read_text())
            await conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        await conn.commit()
    return applied


if __name__ == "__main__":
    names = asyncio.run(migrate())
    print("applied:", ", ".join(names) if names else "nothing new")
