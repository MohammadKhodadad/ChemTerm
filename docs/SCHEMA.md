# ChemTerm Terminology Schema

## 1. Scope

ChemTerm stores multilingual chemical terminology. Patent documents are processing inputs, not database entities.

The database does **not** store:

- complete patent documents;
- document structures or parsed sections;
- every sentence or extracted mention;
- permanent term-to-term translation edges;
- transient model working data; only versioned concept-search embeddings are retained.

It stores:

- language-neutral concepts;
- multilingual terms attached to concepts;
- concept and term classifications;
- external identifiers;
- typed relationships between concepts;
- lightweight patent references supporting the terminology;
- extraction confidence and review history.

This keeps the product small while preserving enough provenance to audit where a term came from.

## 2. Terminology model

### 2.1 Concept

A concept is a language-independent meaning. English is the initial pivot language, but the concept ID is not English-specific.

```text
Concept C001
  English definition: "Acetylsalicylic acid medicinal substance"
  Type: COMPOUND
  External ID: CHEBI:15365

  Terms:
    en  acetylsalicylic acid  [preferred, systematic]
    en  aspirin               [common]
    en  ASA                   [abbreviation]
    de  Acetylsalicylsäure    [preferred]
    fr  acide acétylsalicylique [preferred]
```

Terms are labels for the concept, not separate meanings.

### 2.2 Translation

Accepted translations do not need pairwise edges. They are obtained through the shared concept:

```text
"aspirin" [en] -> Concept C001 <- "Acetylsalicylsäure" [de]
```

Candidate pairs produced during extraction are temporary pipeline data. Once validated, both terms are attached to the concept and the candidate pair can be discarded.

### 2.3 Evidence

Patent content is processed temporarily. The database retains only a lightweight reference:

```text
family_id
publication_number
language
source locator
source URL
optional short excerpt
text origin
extraction method
confidence
```

An evidence set groups terms discovered in corresponding publications from one patent family. This records why multilingual terms were attached to the same concept without storing the patents themselves.

## 3. Implemented PostgreSQL tables

### `concept`

Language-independent meaning.

| Field | Purpose |
|---|---|
| `id` | Internal UUID |
| `english_definition` | Optional English description |
| `status` | Proposed, accepted, rejected, deprecated, or merged |
| `created_by_run_id` | Extraction/import lineage |
| `superseded_by_id` | Merge/deprecation target |
| timestamps | Audit fields |

The preferred English label is selected from `term` using `language = 'en'` and `is_preferred = true`. It is not duplicated on the concept.

### `concept_type`

Hierarchical semantic classification.

| Field | Purpose |
|---|---|
| `id` | Type UUID |
| `code` | Stable machine code |
| `label` | Display label |
| `description` | Annotation definition |
| `parent_id` | Parent type |
| `active` | Lifecycle control |

Initial groups include:

```text
CHEMICAL_ENTITY
├── ELEMENT
├── COMPOUND
│   ├── SALT
│   ├── SOLVATE
│   └── HYDRATE
├── POLYMER
├── CHEMICAL_CLASS
├── FUNCTIONAL_GROUP
└── MARKUSH_CLASS

MATERIAL
MIXTURE_OR_COMPOSITION

PROCESS
├── CHEMICAL_REACTION
├── SYNTHESIS_PROCESS
├── SEPARATION_PROCESS
└── MANUFACTURING_PROCESS

PROPERTY
├── CHEMICAL_PROPERTY
├── PHYSICAL_PROPERTY
└── PERFORMANCE_PROPERTY

MEASUREMENT
EQUIPMENT
APPLICATION
OTHER_TECHNICAL_CONCEPT
```

### `concept_type_assignment`

Allows a concept to have multiple types with separate confidence.

Example: a polymer can be both `POLYMER` and `MATERIAL`.

### `term`

A language-specific label.

| Field | Purpose |
|---|---|
| `id` | Term UUID |
| `concept_id` | Shared meaning |
| `text` | Display text |
| `normalized_text` | Search/deduplication form |
| `language` | BCP 47 language code |
| `script` | Optional ISO 15924 script |
| `term_form_id` | Systematic name, abbreviation, etc. |
| `is_preferred` | Preferred label for this concept/language |
| `status` | Proposed, accepted, rejected, or deprecated |
| `confidence` | Calibrated term-to-concept confidence |
| `created_by_run_id` | Lineage |

Constraints:

- a concept cannot have duplicate normalized terms in one language;
- a concept has at most one preferred term per language;
- identical text can belong to different concepts when meanings differ.

### `term_form`

Initial linguistic forms:

- `SYSTEMATIC_NAME`
- `COMMON_NAME`
- `TRIVIAL_NAME`
- `TRADE_NAME`
- `ABBREVIATION`
- `ACRONYM`
- `MOLECULAR_FORMULA`
- `LINE_NOTATION`
- `REGISTRY_IDENTIFIER`
- `MULTIWORD_TECHNICAL_TERM`
- `PATENT_DEFINED_LABEL`
- `SPELLING_VARIANT`
- `OTHER_TERM_FORM`

### `identifier_namespace`

Controlled identifier definitions used by import validation, retrieval, and the LLM
resolver. Each namespace has a stable code, label, description, optional value
pattern, lifecycle status, and identity strength:

- `authoritative`: structure- or ontology-derived identity signal, such as InChIKey;
- `strong`: high-value registry/structure signal requiring normal validation;
- `supporting`: useful retrieval evidence that cannot establish identity alone.

Seeded namespaces are ChEBI, PubChem CID, InChI, InChIKey, canonical and isomeric
SMILES, molecular formula, Wikidata, and CAS RN. CAS data use and redistribution
must respect applicable licensing.

### `concept_identifier`

Optional mapping to an external authority:

- ChEBI;
- PubChem CID;
- Wikidata;
- InChIKey;
- other approved namespaces.

Mappings reference `identifier_namespace` and have a type (`exact`, `close`, `broad`,
`narrow`, or `related`), confidence, and source URI. Free-form namespace names are
not accepted.

### `concept_embedding`

Versioned semantic-search representation of a concept:

- one row per concept, model name, and model version;
- deterministic text assembled from preferred label, English aliases, type codes,
  controlled identifiers, and definition;
- SHA-256 content hash for idempotent refresh;
- 1024-dimensional normalized vector;
- HNSW cosine index through PostgreSQL `pgvector`.

Embeddings are retrieval signals only. They are excluded from release artifacts by
default and never establish concept identity.

### `evidence_set`

A patent-family observation supporting one or more terms.

| Field | Purpose |
|---|---|
| `family_id` | Patent family reference |
| `extraction_method` | NER/rules/LLM/manual pipeline |
| `confidence` | Calibrated overall confidence |
| `status` | Proposed, accepted, rejected, or needs expert |
| `pipeline_run_id` | Producing run |
| `score_components` | Named component scores |

### `term_evidence`

Connects a term to a minimal patent reference inside an evidence set.

| Field | Purpose |
|---|---|
| `term_id` | Supported term |
| `family_id` | Patent family |
| `publication_number` | Exact publication |
| `source_language` | Publication language |
| `source_locator` | Paragraph, claim, or other locator |
| `source_uri` | Source link |
| `evidence_excerpt` | Optional short excerpt |
| `text_origin` | Original, official translation, machine translation, or unknown |
| `confidence` | Evidence confidence |

The excerpt is optional so restricted patent text can be excluded while keeping reproducible references.

### `relation_type` and `concept_relation`

These represent relationships between meanings, not translations:

- broader/narrower;
- related-to;
- part-of;
- salt-of;
- solvate-of;
- hydrate-of;
- isomer-of;
- polymer-of;
- derivative-of;
- has-functional-group.

### `pipeline_run`

Stores code revision, pipeline version, model versions, configuration, timing, and status.

### `review_decision`

Append-only human decisions on evidence sets:

- accepted;
- rejected;
- needs expert.

## 4. Why there is no permanent term-pair table

During extraction, the pipeline may propose:

```text
"aspirin" [en] <-> "Acetylsalicylsäure" [de]
```

This is a candidate used for scoring and review. After acceptance:

1. find or create the concept;
2. attach both terms to that concept;
3. add their patent references to one evidence set;
4. discard or archive the temporary candidate.

Queries for translations join terms through `concept_id`. This avoids quadratic term-to-term edges as languages and synonyms grow.

## 5. English terminology extraction

English extraction has two complementary tracks.

### 5.1 Chemical entity extraction

Use:

- ChemDataExtractor 2, through an isolated Python 3.11 worker, for broad
  organic/inorganic chemical mentions;
- `mpkato/chemu-biobert-ner` for reaction-heavy patent passages, with its labels
  mapped to controlled ChemTerm types and context roles;
- optional HunFlair2 for biomedical/pharmaceutical subsets;
- high-precision deterministic rules for formulas, InChI, InChIKey, checksum-valid
  CAS registry numbers, explicitly labelled SMILES, pH, quantities/ranges,
  abbreviations, and patent labels.

### 5.2 Complex terminology extraction

Chemical NER alone will miss phrases such as:

- “crosslinkable fluoropolymer composition”;
- “supported metallocene catalyst system”;
- “oxygen-scavenging multilayer barrier film”;
- “low-solvent coating process”.

Add:

- scientific noun-phrase extraction;
- patent-specific phrase patterns;
- nested multi-word term candidates;
- C-value/NC-value or equivalent termhood scoring;
- domain frequency versus general English;
- recurrence across independent patent families.

Before LLM refinement, exact duplicate spans from independent extractors are
reconciled. The result retains all contributing extractor names, raw labels, roles,
and component confidences, removes redundant parent types, and flags incompatible
top-level type evidence for review. Nested spans and repeated occurrences are not
collapsed.

### 5.3 LLM refinement

The LLM receives:

- an English source passage;
- NER, rule, dictionary, and phrase candidates;
- allowed concept types and term forms;
- optional retrieved ChEBI/PubChem candidates.

It may:

- accept/reject a candidate;
- correct boundaries using exact source text;
- choose types and term forms;
- retain meaningful nested terms;
- mark ambiguity;
- rank concept candidates.

It must not:

- invent absent terms;
- create unsupported chemical identifiers;
- collapse salts, hydrates, stereoisomers, polymers, mixtures, or classes;
- turn uncertain results into accepted terminology.

Output must use a strict Pydantic/JSON contract with exact source offsets. LLM confidence is only one feature and must be calibrated against reviewed examples.

### 5.4 Concept attachment

For each accepted English candidate:

1. normalize the lexical form;
2. search existing English terms by exact normalized form and trigram similarity;
3. retrieve possible concepts using controlled identifiers and semantic embeddings;
4. build bounded concept cards for the highest-ranked candidates;
5. load active type and identifier definitions from the database;
6. ask the constrained resolver for same, new, related-not-same, or ambiguous;
7. reject any response that references a concept outside the candidate set;
8. attach it to a compatible concept or create a proposed concept;
9. select one preferred English term;
10. store minimal evidence;
11. keep the result proposed until thresholds are validated.

The resolver receives explicit type definitions, parent relationships, identifier
semantics and identity strength, candidate aliases, and non-merge rules. Similar
strings, vector proximity, and shared molecular formulas are never sufficient by
themselves. Parent compounds, salts, hydrates, solvates, stereoisomers, polymorphs,
classes, mixtures, materials, and processes remain distinct unless evidence proves
identity under the concept model.

The same process later attaches target-language terms to the concept.

### 5.5 Parallel-language mapping

Target terms are located directly in existing parallel patent text; documents are not machine-translated.

For each English candidate, the mapper receives the English text, known English term/type, target language, and exact target text. It must return one of:

- exact equivalent;
- contextual equivalent;
- broader;
- narrower;
- related;
- no match;
- ambiguous.

Matched decisions require an exact contiguous target substring and character offsets. The pipeline validates the substring mechanically and maps normalized offsets back to the original text. Generated translations, corrected spellings absent from the source, missing source decisions, and duplicate decisions fail closed.

Accepted target terms attach to the existing concept. Candidate pairs remain temporary extraction data.

## 6. Running the database

Two supported local options are documented in `README.md`:

- Docker Compose with the `pgvector/pgvector:pg16` image;
- native PostgreSQL 16 and pgvector inside Ubuntu WSL2.

Both options provide PostgreSQL 16 on port 5432 and require the `pg_trgm` and
`vector` extensions. Under Docker, the bootstrap role can create the extensions.
Under WSL, create them once with the PostgreSQL `postgres` superuser before running
Alembic as the restricted `chemterm` role.

The repeatable application-level initialization is:

```powershell
uv sync
uv run alembic upgrade head
uv run python -m chemterm.seed
```

For WSL, run the equivalent commands from the repository path inside Ubuntu with
`UV_PROJECT_ENVIRONMENT=.venv-wsl`. This keeps Linux packages separate from the
Windows `.venv`. On workstations where Windows-to-WSL forwarding is unreliable,
database-dependent commands must run inside WSL.

The development connection is:

```text
postgresql+psycopg://chemterm:chemterm_dev@127.0.0.1:5432/chemterm
```

Override it with `CHEMTERM_DATABASE_URL`. The password is for local development
only and must be replaced outside an isolated workstation. Startup, shutdown,
status, backup, restore, and one-time WSL installation commands are maintained in
`README.md`.

## 7. Initial implementation boundary

The first database iteration is complete when it can:

1. create a concept with a preferred English term;
2. attach English synonyms and multilingual terms;
3. assign one or more concept types;
4. add ChEBI/PubChem identifiers;
5. group multilingual patent references as evidence;
6. record confidence and review decisions;
7. query all labels for a concept;
8. query possible translations through `concept_id`;
9. run migrations and type seeding repeatedly without data loss.

Patent retrieval, passage alignment, NER outputs, and LLM candidate pairs belong to the extraction pipeline and temporary working files—not the authoritative terminology database.
