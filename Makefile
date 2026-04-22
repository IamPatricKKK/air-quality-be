# air-quality-be — common commands

# ─── Server ─────────────────────────────────────
.PHONY: dev start

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

start:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

# ─── Alembic Migrations ────────────────────────
.PHONY: migration-up migration-down migration-create migration-pending migration-history

migration-up:
	alembic upgrade head

migration-down:
	alembic downgrade -1

migration-create:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

migration-pending:
	alembic heads

migration-history:
	alembic history --verbose

# ─── Dependencies ──────────────────────────────
.PHONY: install install-dev

install:
	pip install -r requirements.txt

install-dev:
	pip install -e ".[dev]"
