# Nevo Backend 2.0

Nevo Backend 2.0 is the clean-room backend for Nevo's next platform architecture.
It starts with a PostgreSQL-first, Zero-Tag learner profile model: the database
stores functional learning observations and never stores clinical or diagnostic
labels.

## Runtime

- Python 3.12+
- PostgreSQL 16+
- SQLAlchemy 2
- Alembic
- FastAPI

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Start PostgreSQL:

```powershell
docker compose up -d db
```

Run migrations:

```powershell
alembic upgrade head
```

Run the test suite:

```powershell
pytest
ruff check .
```

PostgreSQL integration tests run when `TEST_DATABASE_URL` is available. They are
also executed in CI against a disposable PostgreSQL service.

## Architecture decisions

- [ADR 0001: Zero-Tag learner profile schema](docs/adr/0001-zero-tag-learner-profile-schema.md)
- [SCRUM-15 implementation contract](docs/jira/SCRUM-15.md)
