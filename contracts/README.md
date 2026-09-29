# Contracts

What every branch builds against. Frozen on `main`.

| File | What it is | Source of truth |
|---|---|---|
| `backend/app/contracts.py` | Pydantic models | **Yes**, edit only here |
| `contracts/schema.json` | JSON Schema of those models | Generated: `cd backend && uv run python -m scripts.export_schema` |
| `frontend/src/contracts.gen.ts` | TypeScript types | Generated: `cd frontend && npm run gen:contracts` |
| `contracts/fixtures/*.json` | Mock payloads | Generated: `cd backend && uv run python -m scripts.make_fixtures` |
| `contracts/API.md` | HTTP routes, error codes, order rules | Yes |
| `backend/migrations/001_init.sql` | Database tables | Yes |
| `backend/app/{catalog,parser,forecast}/__init__.py` | Function signatures between modules | Yes (the signatures, not the bodies) |
| `backend/pyproject.toml`, `backend/uv.lock` | Python dependencies | Yes |

## Rules

1. A feature branch never edits a file in the table above, apart from replacing the
   function bodies it owns.
2. If you need a change, stop and report what you need and why. It lands on `main` as
   `chore/contracts-vN` and every branch rebases.
3. After any change, regenerate everything and run
   `cd backend && uv run pytest tests/test_contracts.py` and `cd frontend && npm run gen:contracts -- --check`.
