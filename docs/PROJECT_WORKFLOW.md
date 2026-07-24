# ChemTerm project workflow

ChemTerm builds a multilingual, evidence-backed chemical terminology database from
parallel patent texts. The central rule is **concept first**: one language-independent
concept can have many terms in many languages, with every accepted term linked to
source evidence.

## End-to-end flow

```text
Patent metadata and multilingual text
  -> validated input records
  -> normalized text with reversible offsets
  -> English term candidates
  -> candidate reconciliation
  -> constrained LLM refinement
  -> concept resolution and external references
  -> target-language term mapping
  -> PostgreSQL persistence and expert review
  -> versioned dataset release
```

## Step by step

### 1. Set up the terminology database

Run PostgreSQL 16 with `pg_trgm` and `pgvector`, apply Alembic migrations, and seed
the controlled concept types, term forms, relation types, and identifier namespaces.
The database stores terminology and lightweight patent references, not full patent
documents.

**Status:** implemented. See `docs/DATABASE_SETUP.md`.

### 2. Ingest patent records

Convert source files into a common `PatentInput` contract containing publication
number, family identifier, languages, source metadata, titles, abstracts, and other
text units. The current CSV adapter discovers columns such as `title_en`,
`abstract_en`, `title_de`, and `abstract_de`.

**Status:** implemented for CSV input.

### 3. Normalize text safely

Normalize Unicode, whitespace, punctuation, identifiers, formulas, and
chemistry-specific spacing while preserving a map back to the original character
offsets. This allows every extracted term to be grounded in the exact source text.

**Status:** implemented.

### 4. Extract English candidates

Run several independent candidate generators:

- deterministic rules for formulas, identifiers, quantities, pH, and patent labels;
- nested technical-phrase extraction;
- ChemDataExtractor 2 for broad chemical mentions;
- ChEMU BioBERT for reaction-oriented patent entities.

Long phrases may produce smaller nested candidates, but only independently useful
terms should survive refinement.

**Status:** implemented.

### 5. Reconcile candidate evidence

Merge identical spans from different extractors, retain every contributing model and
confidence, reduce redundant parent types, and flag incompatible type evidence.
Meaningful nested spans and repeated occurrences remain separate.

**Status:** core exact-span reconciliation implemented.

### 6. Refine candidates with a constrained LLM

Give the LLM the source passage, baseline candidates, and controlled taxonomy. It
may accept, reject, correct boundaries, classify, or add missed terms. Every returned
term must match an exact source span; invented text is rejected. Titles and abstracts
are grouped into one request while offsets remain attached to their original section.

**Status:** implemented.

### 7. Resolve English concepts

Search existing concepts before creating a new one using:

- exact normalized terms;
- controlled external identifiers;
- PostgreSQL trigram similarity;
- optional BGE-M3 semantic embeddings;
- bounded LLM decisions over retrieved candidates.

The resolver distinguishes the same concept from related, broader, narrower, salt,
solvate, stereochemical, formulation, and class/instance differences.

**Status:** retrieval and bounded resolution implemented; full concept creation and
persistence are still pending.

### 8. Add external references

Look up compatible concepts in PubChem, Wikidata, English Wikipedia, and IATE.
Store the authority ID, canonical URL, mapping type, confidence, and review status.
Homonyms and ambiguous IATE entries are not automatically accepted.

**Status:** lookup, reporting, and accepted-reference repository support implemented.

### 9. Map target-language terms

For each English concept candidate, inspect the parallel title and abstract in each
target language. The LLM selects an exact native-language source span without using
machine translation. Mappings are classified as exact, broader, narrower, related,
ambiguous, or no match.

The target form is also marked as translated, unchanged, language-neutral, unknown,
or not present. An unchanged spelling is still a valid target-language term when it
appears in that language's source text.

**Status:** implemented.

### 10. Persist terminology and evidence

Create or reuse concepts, attach multilingual terms, external identifiers, concept
types, patent-family evidence, publication locators, pipeline provenance, and review
state in one idempotent transaction.

**Status:** database schema and selected repositories exist; complete extraction-to-
database persistence is the next major implementation step. Current CLIs primarily
write JSONL reports.

### 11. Review and evaluate

Send ambiguous, conflicting, or high-impact decisions to expert review. Measure
exact-span precision/recall, type accuracy, concept deduplication, multilingual
mapping quality, external-reference precision, calibration, runtime, and LLM cost.

**Status:** contracts and safeguards exist; a complete review application and
held-out evaluation suite remain planned.

### 12. Publish a release

Export accepted concepts, terms, types, identifiers, evidence, and relations as
versioned Parquet/JSONL artifacts with a release manifest. Exclude restricted patent
text unless redistribution is explicitly allowed.

**Status:** planned.

## Current command sequence

```powershell
# Database
docker compose up -d postgres
uv sync
uv run alembic upgrade head
uv run python -m chemterm.seed

# Full extraction and multilingual mapping
uv run chemterm-extract data/chemistry-patents-4-language-sample-preview.csv `
  --chemu `
  --cde-python .venv-cde\Scripts\python.exe `
  --llm `
  --pair-languages de fr `
  --output reports/sample-combined.jsonl

# External authority lookup
uv run chemterm-enrich reports/sample-combined.jsonl `
  --source-csv data/chemistry-patents-4-language-sample-preview.csv `
  --output reports/sample-external-references.jsonl

# Quality checks
uv run ruff check .
uv run pytest
```

## Main outputs

- language-independent concepts;
- multilingual preferred terms and synonyms;
- controlled concept types and semantic relations;
- PubChem, Wikidata, Wikipedia, IATE, and structure identifiers;
- patent publication/family provenance with exact offsets;
- confidence, review state, and reproducible pipeline metadata.

For architecture and implementation detail, see `docs/PLAN.md`. For database fields,
see `docs/SCHEMA.md`.

