# ChemTerm

ChemTerm is evidence-backed multilingual chemical terminology infrastructure. It stores language-neutral concepts, multilingual labels, classifications, external identifiers, and lightweight patent references.

Patent documents are processed as inputs and are not stored in the authoritative terminology database.

## Local setup

Requirements:

- Python 3.12+
- `uv`

Choose one database option. Docker is the portable default; native PostgreSQL in
WSL2 is an alternative for Windows development.

### Option A: Docker Compose

Requires Docker Desktop with Compose.

Start PostgreSQL 16 with `pg_trgm` and `pgvector`:

```powershell
docker compose up -d postgres
```

Install dependencies, create the schema, and seed controlled vocabularies:

```powershell
uv sync
uv run alembic upgrade head
uv run python -m chemterm.seed
```

Stop the database without deleting its volume:

```powershell
docker compose stop postgres
```

### Option B: PostgreSQL in WSL2

This keeps PostgreSQL local without Docker. The following installation commands are
run once in an Ubuntu WSL shell. They add PostgreSQL's official package repository
because Ubuntu 22.04 does not include the required pgvector package.

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

Create the development role and database once:

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

Extension creation must run as PostgreSQL's `postgres` superuser. Normal migrations
and application operations use the restricted `chemterm` role.

From the repository path inside WSL, create a separate Linux environment and build
the schema:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export UV_PROJECT_ENVIRONMENT=.venv-wsl
export CHEMTERM_DATABASE_URL="postgresql+psycopg://chemterm:chemterm_dev@127.0.0.1:5432/chemterm"
~/.local/bin/uv sync
~/.local/bin/uv run alembic upgrade head
~/.local/bin/uv run python -m chemterm.seed
```

On this workstation, Windows-to-WSL PostgreSQL forwarding does not complete database
connections reliably. Run database-dependent commands from the WSL repository path.
The `.venv-wsl` environment is separate from the Windows `.venv` and is ignored by
Git.

Daily WSL database operations:

```bash
sudo pg_ctlcluster 16 main start
pg_lsclusters
sudo pg_ctlcluster 16 main stop
```

Back up and restore:

```bash
PGPASSWORD=chemterm_dev pg_dump -h 127.0.0.1 -U chemterm -Fc chemterm > chemterm.dump
PGPASSWORD=chemterm_dev pg_restore -h 127.0.0.1 -U chemterm \
  --dbname=chemterm --clean --if-exists chemterm.dump
```

Do not use the example development password in a shared or production environment.

### Optional model runtimes

To generate local BGE-M3 concept embeddings:

```powershell
uv sync --extra embeddings
```

Concept resolution searches exact labels and controlled identifiers first, then
trigram and semantic candidates. The LLM receives only the retrieved concept cards
plus the active type/identifier definitions loaded from the database; it cannot
invent or search arbitrary concept IDs.

Run tests and lint:

```powershell
uv run pytest
uv run ruff check .
```

Run the deterministic and technical-phrase baseline:

```powershell
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --output reports/sample-candidates.jsonl
```

The CSV adapter discovers both `title_<language>` and `abstract_<language>` columns.
When both are present, local extractors still process each section independently,
while LLM refinement sends the title and abstract together in one request. Section
markers and offset projection keep every accepted span attached to its original
title or abstract.

Enable ChEMU BioBERT for patent reaction entities:

```powershell
uv sync --extra ner
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --chemu `
  --output reports/sample-ner-candidates.jsonl
```

ChEMU is trained on organic-synthesis patent passages and is licensed CC BY-NC 3.0.
Use it only where non-commercial research terms are acceptable. The adapter maps
reaction roles, conditions, yields, and labels into ChemTerm's controlled contracts.

ChemDataExtractor 2 officially supports Python 3.9–3.11, so keep it in an isolated
Python 3.11 environment:

```powershell
uv venv .venv-cde --python 3.11
uv pip install --python .venv-cde\Scripts\python.exe -r requirements-cde.txt
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --cde-python .venv-cde\Scripts\python.exe `
  --output reports/sample-cde-candidates.jsonl
```

On WSL, use `.venv-cde/bin/python` instead. The persistent JSON-lines worker keeps
ChemDataExtractor isolated while preserving exact character offsets. Keep the
`transformers<5` constraint from `requirements-cde.txt`; ChemDataExtractor 2.4's
tagging stack is not compatible with Transformers 5.

Run both NER systems, deterministic rules, reconciliation, and LLM refinement:

```powershell
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --chemu `
  --cde-python .venv-cde\Scripts\python.exe `
  --llm `
  --pair-languages de fr `
  --output reports/sample-combined.jsonl
```

All extractors run independently. Exact duplicate spans are reconciled before the
LLM, retaining component models, labels, roles, and confidence values. Repeated
occurrences remain separate evidence mentions.

Multilingual pairing also groups the parallel title and abstract into one request
per target language. A mapped span is projected back to the exact target section
and its section-local original offsets.

Target labels are additionally classified as translated, unchanged, or
language-neutral. An unchanged form is retained as a label in the target language;
a missing target (`NOT_PRESENT`) does not create a label.

Enable schema-constrained LLM refinement after configuring
`CHEMTERM_LLM_API_KEY` and `CHEMTERM_LLM_MODEL`:

```powershell
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --llm `
  --output reports/sample-refined-candidates.jsonl
```

Map the known English candidates directly to exact spans in parallel-language
titles—without machine translation:

```powershell
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --llm `
  --pair-languages de fr `
  --output reports/sample-multilingual-mappings.jsonl
```

Find auditable external references for the unique refined English concepts:

```powershell
uv run chemterm-enrich reports/sample-multilingual-mappings.jsonl `
  --source-csv data/chemistry-patents-4-language-sample-preview.csv `
  --output reports/sample-external-references.jsonl
```

The report queries PubChem, Wikidata plus its English Wikipedia sitelink, and IATE.
Each match includes the external ID, canonical URL, match type, confidence, and
review flag. Source publication and patent-family identifiers are retained beside
the matches. Only non-review matches are persisted by default when using
`ExternalReferenceRepository`.

Configuration is loaded from environment variables prefixed with `CHEMTERM_`. See `.env.example`.

## Documentation

- `docs/PLAN.md` — project architecture and roadmap
- `docs/PROJECT_WORKFLOW.md` — short step-by-step overview of the complete pipeline
- `docs/SCHEMA.md` — terminology schema and English extraction design
- `docs/DATABASE_SETUP.md` — database provisioning, migrations, seeding, operations, and backups
- `docs/deep-research-terms.md` — supporting research
