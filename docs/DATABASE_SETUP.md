# Database setup and operations

This guide explains how ChemTerm's PostgreSQL database is provisioned, migrated,
seeded, accessed, verified, backed up, and changed.

## 1. What the database contains

The database is the authoritative terminology store. It contains:

- language-independent concepts;
- multilingual terms attached to those concepts;
- concept types and semantic relations;
- external identifiers and reference URLs;
- lightweight patent-family and publication evidence;
- review decisions and pipeline-run provenance;
- optional concept embeddings for semantic retrieval.

Patent documents, passages, and complete patent text are processing inputs. They are
not stored as authoritative database entities. Multilingual labels are connected by
sharing a `concept_id`; there is deliberately no pairwise translation table.

The deployed schema is controlled by Alembic migrations. SQLAlchemy models describe
the schema used by application code, and Pydantic models validate data at the
application boundary:

| Responsibility | Location |
|---|---|
| Historical and deployable DDL | `migrations/versions/` |
| SQLAlchemy models and constraints | `src/chemterm/models.py` |
| Application validation contracts | `src/chemterm/schemas.py` |
| Controlled vocabulary seeds | `src/chemterm/seed.py` |
| Detailed table/field reference | `docs/SCHEMA.md` |

## 2. Technology

- PostgreSQL 16
- SQLAlchemy 2 and the Psycopg 3 driver
- Alembic migrations
- `pg_trgm` for fuzzy term lookup
- `pgvector` for concept embeddings and cosine search
- Pydantic Settings for environment-based configuration

The Docker setup uses `pgvector/pgvector:pg16`, which contains the server-side
`vector` extension. Migration `0001` enables both required extensions:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;
```

Creating extensions requires a sufficiently privileged PostgreSQL role. In Docker,
the configured initial role can do this. In the WSL setup, extensions are created
once by the `postgres` superuser before normal migrations run as `chemterm`.

## 3. Configuration

Settings are loaded by `src/chemterm/config.py` from process environment variables
and, when present, `.env`. All application settings use the `CHEMTERM_` prefix.
Docker Compose also reads `POSTGRES_PASSWORD` and `POSTGRES_PORT`.

Copying the template is optional because local defaults are provided:

```powershell
Copy-Item .env.example .env
```

The database-related values are:

```dotenv
CHEMTERM_DATABASE_URL=postgresql+psycopg://chemterm:chemterm_dev@127.0.0.1:5432/chemterm
CHEMTERM_SQL_ECHO=false
POSTGRES_PASSWORD=chemterm_dev
POSTGRES_PORT=5432
```

`CHEMTERM_DATABASE_URL` is used by both the application and Alembic. It must be a
SQLAlchemy Psycopg URL, not a plain `postgres://` URL. Set
`CHEMTERM_SQL_ECHO=true` temporarily to log SQL during development.

Do not use the example password in a shared or production environment. Do not commit
a populated `.env`.

## 4. Fresh setup with Docker Compose

Docker is the default development path on Windows.

Requirements:

- Docker Desktop with Compose;
- Python 3.12 or newer;
- `uv`.

From the repository root:

```powershell
docker compose up -d postgres
docker compose ps
uv sync
uv run alembic upgrade head
uv run python -m chemterm.seed
```

The Compose service creates:

| Item | Default |
|---|---|
| Container database | `chemterm` |
| Container role | `chemterm` |
| Password | `chemterm_dev` |
| Host port | `5432` |
| Persistent volume | `chemterm-postgres` |

The health check uses `pg_isready`. `docker compose ps` should report the service as
healthy before migrations are applied.

Stop PostgreSQL without deleting data:

```powershell
docker compose stop postgres
```

Restart it later:

```powershell
docker compose up -d postgres
```

If port 5432 is already occupied, choose another host port:

```powershell
$env:POSTGRES_PORT = "5433"
$env:CHEMTERM_DATABASE_URL = "postgresql+psycopg://chemterm:chemterm_dev@127.0.0.1:5433/chemterm"
docker compose up -d postgres
uv run alembic upgrade head
```

Keep the port in `POSTGRES_PORT` and the URL synchronized.

## 5. Fresh setup in WSL2

Use this path when PostgreSQL should run directly in Ubuntu rather than Docker. The
commands below target Ubuntu 22.04 and PostgreSQL 16.

Install PostgreSQL and pgvector once:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl postgresql-common
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt jammy-pgdg main" |
  sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-client-16 postgresql-16-pgvector
```

Create the development role, database, and extensions once:

```bash
sudo pg_ctlcluster 16 main start
sudo -u postgres psql -c \
  "CREATE ROLE chemterm LOGIN PASSWORD 'chemterm_dev'"
sudo -u postgres createdb --owner=chemterm chemterm
sudo -u postgres psql -d chemterm -c \
  "CREATE EXTENSION IF NOT EXISTS pg_trgm"
sudo -u postgres psql -d chemterm -c \
  "CREATE EXTENSION IF NOT EXISTS vector"
```

Then initialize ChemTerm from the repository path inside WSL:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export UV_PROJECT_ENVIRONMENT=.venv-wsl
export CHEMTERM_DATABASE_URL="postgresql+psycopg://chemterm:chemterm_dev@127.0.0.1:5432/chemterm"
~/.local/bin/uv sync
~/.local/bin/uv run alembic upgrade head
~/.local/bin/uv run python -m chemterm.seed
```

Use the restricted `chemterm` role for migrations and application operations. Only
the one-time extension setup needs the `postgres` superuser.

On this workstation, database connections forwarded from Windows to WSL have not
been reliable. Run database-dependent commands from the WSL repository path and use
the separate `.venv-wsl` environment.

Daily WSL operations:

```bash
sudo pg_ctlcluster 16 main start
pg_lsclusters
sudo pg_ctlcluster 16 main stop
```

Do not run Docker PostgreSQL and WSL PostgreSQL on the same host port at the same
time.

## 6. Migration lifecycle

Alembic reads `CHEMTERM_DATABASE_URL` through `migrations/env.py` and compares
migrations against `Base.metadata`.

Current migration chain:

| Revision | Purpose |
|---|---|
| `0001` (`0001_terminology_schema.py`) | Extensions, terminology tables, indexes, and constraints |
| `0002` (`0002_target_form_status.py`) | Adds multilingual target-form status to term evidence |

Inspect and apply migrations:

```powershell
uv run alembic current
uv run alembic history
uv run alembic upgrade head
```

To create a schema change:

1. Update the SQLAlchemy model.
2. Ensure the local database is already at the current Alembic head.
3. Generate a migration.
4. Review every generated operation manually.
5. Apply it to a fresh or disposable database.
6. Run the test suite.

```powershell
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe the schema change"
uv run alembic upgrade head
uv run pytest
```

Never assume an autogenerated migration is safe. Check data conversions, nullability,
server defaults, indexes, constraint names, extension permissions, and downgrade
behavior. Production migrations should be backed up and rehearsed before deployment.

To undo only the newest revision in a disposable development database:

```powershell
uv run alembic downgrade -1
```

Downgrades can destroy data. Do not run them against a valuable database without
reviewing the migration and taking a tested backup.

## 7. Controlled vocabulary seeding

After migrations, run:

```powershell
uv run python -m chemterm.seed
```

The seed operation uses one transaction and inserts the controlled values required
by validation and concept resolution:

1. hierarchical concept types;
2. term forms;
3. concept relation types;
4. identifier namespaces such as ChEBI, PubChem, Wikidata, Wikipedia, and IATE.

It does not create concepts, terms, evidence, embeddings, or pipeline runs.

The command is intended to be idempotent. Existing concept-type labels and
descriptions are refreshed; missing controlled values are inserted. Run it after
every deployment containing seed-definition changes.

## 8. Schema map

ChemTerm currently has 14 authoritative tables.

```text
Controlled vocabularies
  concept_type ── parent_id ───────────────> concept_type
  term_form
  relation_type
  identifier_namespace

Core terminology
  pipeline_run ──< concept
  concept ───────< term
  concept ───────< concept_type_assignment >── concept_type
  concept ───────< concept_identifier >──────── identifier_namespace
  concept ───────< concept_embedding
  concept ───────< concept_relation >────────── relation_type
  concept ── superseded_by_id ────────────────> concept

Evidence and review
  pipeline_run ──< evidence_set
  evidence_set ──< term_evidence >───────────── term
  evidence_set ──< review_decision
  concept_relation ── optional evidence_set_id > evidence_set
```

The tables are grouped as follows:

| Group | Tables | Purpose |
|---|---|---|
| Controlled vocabulary | `concept_type`, `term_form`, `relation_type`, `identifier_namespace` | Stable allowed values and definitions |
| Concepts and labels | `concept`, `term`, `concept_type_assignment` | Language-independent identity and multilingual names |
| External resolution | `concept_identifier`, `concept_embedding` | Authority links and semantic retrieval |
| Semantics | `concept_relation` | Broader, narrower, related, chemical-form, and composition links |
| Evidence | `evidence_set`, `term_evidence` | Patent family/publication provenance and exact term evidence |
| Audit | `pipeline_run`, `review_decision` | Reproducibility and human decisions |

Important design rules:

- one preferred term is allowed per concept and language;
- external identifiers use a seeded namespace and preserve mapping type, confidence,
  and source URL;
- a molecular formula is supporting evidence, not sufficient proof of identity;
- embeddings and trigram scores retrieve candidates but do not establish identity;
- target-language forms distinguish translated, unchanged, language-neutral, and
  unknown evidence;
- `NOT_PRESENT` does not create term evidence;
- publication provenance is reached through
  `concept -> term -> term_evidence -> evidence_set`.

See `docs/SCHEMA.md` for field-level details and constraints.

## 9. Application connection and transactions

`src/chemterm/db.py` creates the shared SQLAlchemy engine:

```text
environment or .env
  -> config.get_settings()
  -> db.create_database_engine()
  -> engine and SessionLocal
  -> repository classes
```

The engine enables `pool_pre_ping`, which checks pooled connections before use.
`session_scope()` provides commit-on-success, rollback-on-error, and guaranteed
session closure:

```python
from chemterm.db import session_scope
from chemterm.resolution.repository import ConceptSearchRepository

with session_scope() as session:
    repository = ConceptSearchRepository(session)
    vocabulary = repository.vocabulary()
```

Application services receive repositories rather than issuing SQL directly.
Implemented database access currently includes:

- `ConceptSearchRepository`: controlled vocabulary loading, exact/fuzzy/vector
  concept retrieval, and embedding upserts;
- `ExternalReferenceRepository`: accepted external-reference upserts into
  `concept_identifier`.

The extraction and enrichment CLIs currently write JSONL reports. End-to-end
persistence of extracted concepts, terms, evidence sets, and review records remains
planned work; running `chemterm-extract` does not populate PostgreSQL.

## 10. Verification and smoke checks

Run code-level checks:

```powershell
uv run ruff check .
uv run pytest
```

The current tests validate model metadata, constraints, contracts, resolution logic,
and enrichment clients. They do not yet create a live PostgreSQL database, so also
perform database smoke checks after setup.

Docker:

```powershell
docker compose ps
uv run alembic current
docker compose exec postgres psql -U chemterm -d chemterm -c "\dx"
docker compose exec postgres psql -U chemterm -d chemterm -c "\dt"
docker compose exec postgres psql -U chemterm -d chemterm -c "SELECT count(*) FROM concept_type;"
```

WSL:

```bash
pg_isready -h 127.0.0.1 -p 5432 -U chemterm -d chemterm
~/.local/bin/uv run alembic current
PGPASSWORD=chemterm_dev psql -h 127.0.0.1 -U chemterm -d chemterm -c '\dx'
PGPASSWORD=chemterm_dev psql -h 127.0.0.1 -U chemterm -d chemterm -c '\dt'
```

Expected results:

- Alembic reports revision `0002` or the newer current head;
- `pg_trgm` and `vector` are installed;
- all 14 tables are present, plus Alembic's `alembic_version` table;
- seeded controlled tables contain rows.

## 11. Backup and restore

Back up WSL or any directly reachable PostgreSQL server:

```bash
PGPASSWORD=chemterm_dev pg_dump -h 127.0.0.1 -U chemterm -Fc chemterm > chemterm.dump
```

Restore into an existing database:

```bash
PGPASSWORD=chemterm_dev pg_restore -h 127.0.0.1 -U chemterm \
  --dbname=chemterm --clean --if-exists chemterm.dump
```

For Docker, create a custom-format dump inside the container and copy it out:

```powershell
docker compose exec postgres pg_dump -U chemterm -d chemterm `
  --format=custom --file=/tmp/chemterm.dump
$container = docker compose ps -q postgres
docker cp "${container}:/tmp/chemterm.dump" .\chemterm.dump
```

Restore it:

```powershell
$container = docker compose ps -q postgres
docker cp .\chemterm.dump "${container}:/tmp/chemterm.dump"
docker compose exec postgres pg_restore -U chemterm -d chemterm `
  --clean --if-exists /tmp/chemterm.dump
```

`--clean` drops database objects before recreating them. Test restores periodically;
an untested backup is not sufficient operational protection.

## 12. Resetting a development database

Stopping a container preserves the named volume. The following command does not:

```powershell
docker compose down -v
```

`docker compose down -v` permanently deletes the local Compose database volume.
Use it only when a complete development reset is intended. Recreate the database
afterward:

```powershell
docker compose up -d postgres
docker compose ps
uv run alembic upgrade head
uv run python -m chemterm.seed
```

For WSL, prefer dropping and recreating only the development database as the
`postgres` superuser, then recreate extensions before running migrations. Do not
copy development reset commands into a production procedure.

## 13. Production considerations

The repository currently documents local development, not a complete production
deployment. Before production use:

- use a managed secret rather than `.env` or the example password;
- use a restricted application role and a separate migration role;
- provision `pg_trgm` and `vector` explicitly;
- enable TLS and network access controls;
- define connection-pool limits and statement timeouts;
- automate backups, retention, restore tests, and monitoring;
- run migrations as a controlled deployment step;
- add live PostgreSQL integration and migration tests;
- establish retention/licensing rules for patent excerpts and external identifiers.

## 14. Relevant files

| File | Purpose |
|---|---|
| `compose.yaml` | Local PostgreSQL container, volume, port, and health check |
| `.env.example` | Local configuration template |
| `src/chemterm/config.py` | Runtime settings |
| `src/chemterm/db.py` | Engine and transaction-scoped sessions |
| `src/chemterm/models.py` | SQLAlchemy schema |
| `src/chemterm/schemas.py` | Pydantic persistence contracts |
| `src/chemterm/seed.py` | Controlled vocabulary initialization |
| `alembic.ini` | Alembic configuration |
| `migrations/env.py` | Alembic engine and metadata wiring |
| `migrations/versions/` | Ordered schema revisions |
| `src/chemterm/resolution/repository.py` | Concept search and embedding persistence |
| `src/chemterm/enrichment/repository.py` | External identifier persistence |
| `tests/test_schema.py` | Schema and contract invariants |

