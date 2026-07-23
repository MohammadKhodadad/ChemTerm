# ChemTerm: Multilingual Chemical Terminology Plan

## 1. Purpose

ChemTerm will build a high-quality, multilingual terminology resource from parallel or comparable chemical patent documents. Its primary output is not merely a list of translated strings, but a provenance-rich set of chemical concepts, their language-specific terms, and the evidence connecting them.

The initial corpus will consist of paired patent publications discoverable through Google Patents. The system should support:

- identifying publications that describe the same invention in different languages;
- aligning their sections, paragraphs, claims, and sentences;
- extracting chemical terms and multi-word expressions;
- linking equivalent terms across languages;
- normalizing chemical entities where the evidence permits;
- scoring every proposed relation and preserving its source evidence;
- supporting expert review and reproducible dataset releases;
- optionally exposing the result as a terminology graph.

Patent documents are processing inputs, not database entities. The authoritative database stores concepts, terms, classifications, external identifiers, confidence, review history, and lightweight patent references. Full patent text and detailed parsing/alignment records remain temporary pipeline data.

## 2. Product definition

### 2.1 Architecture decision summary

The first production-quality implementation will use a **relational, evidence-first terminology model**, not a dedicated graph database.

- PostgreSQL is the authoritative working database.
- A `Concept` has the shared language-independent ID.
- A `Term` is a language-specific label with its own ID.
- English is the pivot language, while concept identity remains language-neutral.
- Accepted translations are terms sharing a concept; they do not require permanent term-pair edges.
- Patent-family and publication references provide lightweight evidence without storing documents.
- Candidate mentions, alignments, and term pairs are temporary pipeline data.
- Source readers are replaceable adapters behind a versioned `PatentInput` contract.
- English is the initial extraction language because chemistry-aware NER is strongest there.
- LLMs refine extraction and propose/rank multilingual mappings; they do not directly create authoritative records.
- Accepted data can later be exported as tables, SKOS/TBX/RDF, or a property graph.
- Versioned Parquet/JSONL snapshots can be published to a private or public Hugging Face dataset repository, subject to source licenses.

This model supports graph-like relationships without requiring Neo4j at the start. A graph database should be introduced only if real application queries demonstrate that PostgreSQL and exported RDF are insufficient.

### 2.2 Core unit

The core unit is a **concept assertion**:

> In a specific source context, term A in language X and term B in language Y are likely to denote the same chemical concept.

Each assertion must retain:

- source publication and source locator;
- optional short evidence excerpt where permitted;
- source and target language;
- extraction and alignment method;
- model, rules, and configuration versions;
- confidence score and score components;
- review status and reviewer decision;
- creation time and dataset release.

This evidence-first model prevents uncertain translations from silently becoming accepted terminology.

### 2.3 Terminology scope

The first version should distinguish at least:

- chemical substances and mixtures;
- systematic, common, trivial, and trade names;
- molecular formulae and line notations;
- material classes and functional groups;
- reactions and processes;
- chemical properties and measurement terms;
- abbreviations and expanded forms;
- broader patent terminology relevant to chemistry.

Named compounds should be separated from generic classes. For example, a specific molecule, a Markush expression, and a broad phrase such as "halogenated polymer" require different representations and matching rules.

Runtime scope policy version 1 is implemented in `chemterm.taxonomy`. It defines all
25 concept types with descriptions and explicit in-scope/out-of-scope rules. The
same catalog seeds PostgreSQL and builds the extraction prompt. Each LLM candidate
must be marked `IN_SCOPE`, `OUT_OF_SCOPE`, or `REVIEW`; out-of-scope candidates are
mechanically removed, and a successful empty refinement cannot fall back to baseline
noise. Accepted candidates may carry a source-aware proposed definition, but this is
not authoritative until reconciled with a curated vocabulary or expert review.

### 2.4 Non-goals for the first release

- inferring complete reaction mechanisms;
- resolving every Markush structure to enumerated molecules;
- treating machine-translated text as authoritative bilingual evidence;
- replacing expert chemical or legal review;
- building a universal chemistry ontology before validating extraction quality.

## 3. Guiding principles

1. **Provenance before scale**: no term or relation without traceable evidence.
2. **Concepts are separate from labels**: multilingual labels attach to concepts; strings alone are not concepts.
3. **Uncertainty is explicit**: retain probabilities, alternatives, and review state.
4. **Patent structure matters**: title, abstract, description, examples, and claims have different alignment behavior.
5. **Chemistry-aware matching is required**: generic multilingual embeddings are only one signal.
6. **Evaluation prevents self-confirming pipelines**: manually curated test sets remain independent of training data.
7. **Releases are reproducible**: raw input snapshots, code, models, configuration, and outputs are versioned.
8. **Start relational, export as a graph**: validate the data model before committing to a dedicated graph database.

## 4. Source strategy

Google Patents is useful for discovery and inspection, but the production ingestion path must use stable, permitted bulk sources or official publication feeds where possible. Before large-scale collection, document source terms, redistribution rights, rate limits, and retention requirements.

### 4.1 Candidate sources

- Google Patents Public Datasets / BigQuery, subject to current access and terms;
- EPO Open Patent Services and publication data;
- WIPO PATENTSCOPE data and PCT publications;
- national patent office bulk datasets;
- chemistry authority sources for normalization, subject to their licenses.

CAS Registry Numbers may appear in patents, but CAS data and mappings have licensing constraints. They must not be treated as an unrestricted canonical backbone without legal confirmation.

### 4.2 Document pairing

Patent publications should be paired using bibliographic evidence, not title similarity alone:

1. same publication with authoritative language variants, when available;
2. same PCT application or publication;
3. same INPADOC/simple patent family and shared priorities;
4. shared application identifiers plus dates and applicants;
5. semantic similarity as a fallback candidate signal only.

Store the pairing reason and confidence. Family members are often comparable rather than literal translations: claims may be amended, paragraphs reordered, and examples changed. The system must label each pair as `parallel`, `near_parallel`, or `comparable`.

### 4.3 Language integrity

For every text, retain:

- publication jurisdiction and number;
- publication date and kind code;
- declared and detected language;
- whether text is original, officially translated, or machine translated;
- patent family and priority identifiers;
- source URI, retrieval timestamp, and content checksum.

Machine translations can assist candidate generation but should never be mixed with original-language text without an explicit flag.

## 5. End-to-end pipeline

### Stage A: Ingestion and temporary processing

- retrieve publication metadata and content;
- retain source payloads only in a controlled processing cache when needed;
- compute checksums and assign internal document IDs;
- detect duplicates and changed upstream records;
- record source, license, retrieval, and parser versions.

Processing artifacts can use a temporary bronze/silver layout:

- **Bronze**: temporary source payloads, subject to retention policy;
- **Silver**: temporary parsed documents, candidates, and alignments;
- **Gold**: authoritative concepts, terms, evidence references, and release exports.

Only Gold records enter the terminology database.

### Stage B: Patent parsing and normalization

- preserve title, abstract, description, examples, tables, and claims;
- keep paragraph, claim, sentence, and character offsets;
- normalize Unicode and whitespace without destroying chemical notation;
- retain both original and normalized text;
- identify formulas, subscripts, superscripts, Greek letters, and OCR artifacts;
- perform language identification at document and passage level.

### Stage C: Document and passage alignment

Alignment should be hierarchical:

1. pair publications;
2. map structural sections;
3. align paragraphs or claims;
4. align sentences or sentence groups;
5. retain many-to-many alignments where necessary.

Candidate features can include:

- section type and relative position;
- numbers, units, formulae, and shared identifiers;
- chemical fingerprints or normalized structures;
- multilingual embeddings;
- length ratio and punctuation patterns;
- dictionary anchors;
- cross-encoder or reranker score.

Do not force every passage into a one-to-one alignment. Store unmatched passages and alignment alternatives.

### Stage D: Monolingual term extraction

The initial pipeline is English-first:

1. run chemistry-aware NER over English passages;
2. add high-precision dictionary, identifier, formula, abbreviation, and terminology rules;
3. use an LLM to review boundaries, classify mention types, and propose missed candidates;
4. validate LLM output against the source span and a strict typed schema;
5. retain the original outputs from every extractor instead of overwriting them.

The extractor ensemble should include:

- chemistry-aware named-entity recognition;
- noun-phrase and terminology patterns;
- abbreviation detection;
- dictionaries and ontology matching;
- chemical identifier, formula, and structure parsers;
- corpus statistics for domain specificity.

Preserve nested mentions. A long chemical name can contain valid functional-group and class mentions.

LLM refinement must be deterministic where the provider permits it, schema-constrained, versioned, and independently testable. A generated term is invalid unless it maps to an exact source span or is explicitly marked as a normalization suggestion.

### Stage E: Cross-lingual candidate generation

For each accepted English mention, inspect only the aligned passages in the target-language publication. Generate candidates using:

- co-occurrence and alignment consistency;
- multilingual embedding similarity;
- transliteration and normalized string similarity;
- abbreviation/expansion compatibility;
- shared formula, registry identifier, InChIKey, or structure;
- frequency and bidirectional translation consistency;
- contextual semantic similarity;
- ontology constraints and term-type compatibility.

The LLM receives the English mention, both aligned passages, a bounded candidate list, and optional retrieved chemistry records. It may rank candidates or return `no_match`; it must not invent target-language text that is absent from the evidence passage.

A target term can produce one of four outcomes:

1. attach a new language-specific term to an existing concept;
2. attach an existing term to an existing concept with new document evidence;
3. propose a new concept and its first terms;
4. remain unresolved for review.

### Stage F: Candidate reranking and calibration

A reranker combines the candidate signals and produces a calibrated probability. The training data must include difficult negatives:

- related but non-equivalent compounds;
- parent compound versus salt, hydrate, stereoisomer, or mixture;
- chemical class versus member;
- reactant versus product;
- abbreviation collisions;
- terms close in the same sentence but not translations.

Use publication-family splits during training and evaluation to prevent leakage. A patent family must never occur across train, validation, and test sets.

### Stage G: Concept resolution

Accepted term pairs are clustered cautiously into concepts. Automatic transitive closure is unsafe: if A resembles B and B resembles C, A and C are not necessarily equivalent.

Concept resolution should:

- normalize language-specific variants;
- attach known identifiers only with supporting evidence;
- distinguish exact equivalence from related, broader, and narrower relations;
- preserve stereochemistry, salt form, hydration state, and mixture distinctions;
- detect conflicting assertions;
- allow concepts to be split and merged through auditable operations.

### Stage H: Human review

Create a review queue prioritized by uncertainty, impact, and novelty. Reviewers should see:

- both source passages with highlighted terms;
- patent metadata and document-pair quality;
- proposed relation and alternatives;
- normalized structures or identifiers, when available;
- component scores and relevant model explanation;
- similar accepted and rejected examples.

Recommended states:

`proposed -> accepted | rejected | needs_expert | deprecated`

Every review action should be attributed and reversible.

High-confidence automatic acceptance should not be enabled until calibrated against an independent expert-reviewed benchmark. Until then, model output remains `proposed`.

### Stage I: Publication

Publish immutable, versioned releases with:

- terminology records;
- provenance and confidence;
- language and relation types;
- source-document references where redistribution permits;
- machine-readable JSONL and Parquet;
- TSV for simple interchange;
- RDF/SKOS-compatible graph export after the model stabilizes;
- dataset card, model cards, license notes, and quality metrics.

Hugging Face is a release and distribution layer, not the live database. Recommended release artifacts are:

```text
concepts.parquet
terms.parquet
concept_types.parquet
concept_identifiers.parquet
term_evidence.parquet
concept_relations.parquet
release_manifest.json
README.md
```

Patent full text should be excluded from public releases unless redistribution has been explicitly approved. Document identifiers, offsets, short evidence excerpts where permitted, and reproducible retrieval metadata can be released separately from restricted source text.

## 6. Data model

Use PostgreSQL as the system of record. The database is terminology-only; patent retrieval, parsing, mention detection, passage alignment, and candidate term pairing occur outside the authoritative schema.

### 6.1 Identity model

English is the extraction and display pivot, but the concept ID is language-neutral:

```text
Concept C001: acetylsalicylic acid substance
├── Term T001: "acetylsalicylic acid"       [en, preferred]
├── Term T002: "aspirin"                    [en, common]
├── Term T003: "Acetylsalicylsäure"         [de, preferred]
└── Term T004: "acide acétylsalicylique"    [fr, preferred]
```

Terms are labels for the concept, not meanings themselves. Accepted translations are queried through the common `concept_id`. Temporary term-pair candidates are discarded or archived after concept attachment.

### 6.2 Core tables

- `concept`: language-neutral meaning, optional English definition, and lifecycle;
- `concept_type`: hierarchical semantic types;
- `concept_type_assignment`: one or more classifications per concept;
- `term`: multilingual label, form, preferred status, confidence, and concept;
- `term_form`: systematic name, common name, abbreviation, trade name, and other forms;
- `concept_identifier`: ChEBI, PubChem, Wikidata, InChIKey, and approved mappings;
- `evidence_set`: a patent-family observation supporting multilingual terms;
- `term_evidence`: exact publication reference, language, locator, optional excerpt, and confidence;
- `relation_type`: controlled semantic and chemistry-specific relationships;
- `concept_relation`: broader, narrower, related, salt-of, hydrate-of, isomer-of, and similar links;
- `review_decision`: append-only human review of an evidence set;
- `pipeline_run`: code revision, model versions, configuration, and timestamps.

A `dataset_release` manifest/table can be added when the first external release pipeline is implemented.

### 6.3 Important constraints

- a concept has at most one preferred term per language;
- normalized terms are unique within a concept and language;
- identical text can belong to different concepts when meanings differ;
- confidence values remain in `[0,1]`;
- evidence retains family ID, exact publication, language, source locator, and text origin;
- scores are stored by component, not only as one opaque confidence number;
- accepted changes are append-only or versioned;
- train, validation, and test records are separated by patent family.

### 6.4 Graph projection

The relational model can be projected without changing the source of truth:

```text
(Term)-[:DENOTES]->(Concept)
(Concept)-[:HAS_IDENTIFIER]->(Identifier)
(Concept)-[:BROADER_THAN|RELATED_TO|SALT_OF]->(Concept)
(Term)-[:SUPPORTED_BY]->(PatentReference)
```

SKOS can guide preferred/alternative labels and semantic relations, while TBX can support terminology interchange. Chemistry-specific relations and evidence require a small application ontology. Avoid representing every fact as an untyped generic edge.

### 6.5 Capacity and local operation

One hundred thousand terms is a small workload for PostgreSQL. Terms, concepts, evidence references, and ordinary indexes should generally occupy hundreds of megabytes, not tens of gigabytes:

- keep PostgreSQL local during development;
- use a persistent Docker volume or native PostgreSQL installation;
- back up with regular logical dumps and test restoration;
- keep raw patents and embeddings outside the terminology database;
- move to a managed PostgreSQL instance when multiple users, remote services, uptime requirements, or sensitive access control make local hosting inadequate.

The executable schema and operational instructions are defined in `docs/SCHEMA.md`.

## 7. Quality and evaluation

### 7.1 Gold datasets

Build a stratified, expert-reviewed benchmark across:

- languages and language families;
- patent offices and years;
- abstracts, descriptions, examples, and claims;
- specific compounds, classes, processes, and properties;
- easy, ambiguous, and adversarial cases.

Annotation guidelines must define equivalence, acceptable variants, concept boundaries, and treatment of stereochemistry, salts, solvates, mixtures, Markush terms, and trade names. Measure inter-annotator agreement and adjudicate disagreements.

### 7.2 Metrics

Report metrics at each stage:

- document-pair precision;
- passage-alignment precision/recall or alignment error rate;
- mention extraction precision, recall, and F1;
- candidate recall at K;
- pair-ranking MAP, MRR, precision at K, and recall at K;
- probability calibration via Brier score and reliability curves;
- concept clustering pairwise F1 and cluster error analysis;
- accepted terminology precision by language, entity type, and confidence band;
- reviewer agreement and review throughput.

The primary release gate should favor precision. A professional glossary is damaged more by confident false equivalences than by temporarily missing terms.

### 7.3 Testing layers

- unit tests for parsing, normalization, and identifiers;
- schema and data-contract tests;
- golden-file tests for patent parsing;
- deterministic pipeline integration tests on a small corpus;
- model regression tests on frozen benchmarks;
- leakage and duplicate checks;
- performance and cost benchmarks;
- end-to-end reproducibility test for every release candidate.

## 8. Security, legal, and governance

- maintain a source and license register before ingestion;
- do not bypass provider access controls or scrape against applicable terms;
- separate source-derived text from redistributable annotations;
- use least-privilege credentials and managed secret storage;
- log access to restricted datasets;
- scan source documents as untrusted input;
- sanitize rendered markup and isolate parsers;
- define retention and deletion policies;
- record model and dataset lineage;
- document known biases, unsupported languages, and failure modes.

Patent documents are public records in many jurisdictions, but bulk access, database rights, translated text, and chemical authority data can still carry separate restrictions. Legal review is a project gate, not a final cleanup task.

## 9. Proposed technical architecture

The exact stack should be confirmed with a small vertical slice. A strong default is:

- Python 3.12+ for pipelines and ML;
- `uv` for dependency and environment management;
- Pydantic for typed contracts;
- PostgreSQL for authoritative terminology;
- temporary file/object storage for pipeline inputs when required;
- Parquet and DuckDB for analytical datasets;
- Prefect or Dagster only when orchestration complexity warrants it;
- PyTorch/Transformers for extraction and reranking;
- FastAPI for review and query APIs;
- OpenTelemetry and structured logs for observability;
- Docker for reproducible local and CI environments.

All stages should communicate through versioned data contracts, not in-memory assumptions. Pipeline tasks must be idempotent and restartable.

The operational data flow is:

```text
Patent discovery and retrieval
  -> family/publication validation
  -> structured document parsing
  -> cross-language passage alignment
  -> English chemistry NER
  -> rule and LLM refinement
  -> target-language candidate generation
  -> constrained LLM/cross-encoder reranking
  -> concept and identifier resolution
  -> proposed concept/term attachments with lightweight evidence
  -> expert review
  -> accepted concepts and multilingual terms
  -> Parquet / Hugging Face / SKOS / TBX / RDF exports
```

The current sample demonstrates English, German, and French title coverage. Dutch fields are not populated in the preview, so Dutch must not be counted as supported until source availability and passage-level quality are verified.

### 9.1 Replaceable input boundary

The input source is expected to change substantially. CSV column names, Google Patents exports, BigQuery records, Parquet datasets, APIs, and future full-text sources must not leak into extraction or persistence code.

Use a ports-and-adapters boundary:

```text
CSV / Parquet / API / BigQuery / other source
        |
        v
Source-specific InputAdapter
        |
        v
Versioned PatentInput contract
        |
        v
Normalization -> extraction -> mapping -> concept resolution
        |
        v
TerminologyRepository
        |
        v
PostgreSQL
```

The canonical in-memory input contract should contain only source-independent fields:

```text
PatentInput
  contract_version
  source_record_id
  family_id
  publication_number
  source_uri?
  text_units[]

TextUnit
  language
  text
  unit_type        # title, abstract, claim, paragraph, other
  locator
  text_origin      # original, official translation, machine translation, unknown
  metadata
```

`PatentInput` is transient and is never the authoritative database model.

The adapter contract should expose a stream/iterator so large sources do not need to fit in memory:

```python
class PatentInputAdapter(Protocol):
    def records(self) -> Iterator[PatentInput]: ...
```

Rules for the boundary:

1. the CSV reader is only the first adapter;
2. downstream stages accept `PatentInput`, never CSV rows or provider SDK objects;
3. adapters perform source-shape mapping, not NER, terminology extraction, or database writes;
4. text normalization is a separate stage and preserves original text;
5. source-specific metadata goes into a bounded metadata field and is not required by core algorithms;
6. malformed records produce typed validation errors and metrics rather than silent row loss;
7. adapter contract tests are reused for every source implementation;
8. adapter selection is configuration-driven;
9. contract changes require an explicit version and compatibility tests;
10. extraction and persistence tests use in-memory `PatentInput` fixtures, not real source files.

The first adapter will read the sample CSV. Future adapters can replace it without modifying extraction, concept resolution, or PostgreSQL code.

### 9.2 Replaceable output boundary

Extraction code must not issue SQL directly. It produces validated terminology candidates and calls a repository/service interface. PostgreSQL is one implementation of that interface.

```text
ExtractionResult
  -> TerminologyService
      -> concept lookup/create
      -> term lookup/create
      -> evidence recording
      -> review-state recording
```

This keeps model experiments independent from database transactions and makes unit tests fast.

## 10. Proposed repository layout

```text
ChemTerm/
├── docs/
│   ├── PLAN.md
│   ├── SCHEMA.md
│   ├── architecture/
│   ├── decisions/
│   ├── annotation-guidelines/
│   └── data-sources/
├── src/chemterm/
│   ├── contracts/
│   │   ├── input.py
│   │   └── extraction.py
│   ├── ingestion/
│   │   ├── base.py
│   │   └── csv_titles.py
│   ├── normalization/
│   ├── alignment/
│   ├── extraction/
│   ├── ranking/
│   ├── concepts/
│   ├── repositories/
│   ├── services/
│   ├── evaluation/
│   └── api/
├── pipelines/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── schemas/
├── configs/
├── scripts/
└── pyproject.toml
```

Architecture decisions should be recorded as short ADRs under `docs/decisions/`.

## 11. Delivery roadmap

### Phase 0: Definition and feasibility

Deliverables:

- target language shortlist and terminology scope;
- source/license register;
- patent pairing rules;
- annotation guidelines v0;
- 20-50 manually inspected multilingual document pairs;
- explicit acceptance criteria and baseline measurements.

Exit gate: reviewers agree that the selected pairs contain enough reliable cross-lingual evidence.

### Phase 1: Reproducible vertical slice

Deliver one end-to-end path for one language pair:

- ingest a small licensed corpus;
- parse and preserve patent structure;
- align passages;
- extract English chemical mentions;
- refine extraction using rules and schema-constrained LLM output;
- generate target-language candidates from aligned passages;
- rank candidates using lexical, embedding, chemical, and constrained LLM signals;
- store proposed concepts, multilingual terms, and lightweight evidence;
- export a reviewable dataset.

Exit gate: the complete output can be regenerated from a manifest and inspected term-by-term.

### Phase 2: Benchmark and baselines

- create the first adjudicated gold dataset;
- implement lexical, embedding, and chemistry-aware baselines;
- establish family-safe train/validation/test splits;
- publish per-stage metrics and error taxonomy.

Exit gate: quality gains are measurable against simple baselines.

### Phase 3: Review workflow and concept model

- implement expert review;
- add identifier-assisted normalization;
- introduce concept and relation management;
- calibrate thresholds for automatic acceptance and manual review.

Exit gate: accepted entries meet the agreed precision threshold and all decisions are auditable.

### Phase 4: Multilingual expansion

- add languages incrementally based on source quality and reviewer availability;
- evaluate each language independently;
- add language-specific tokenization, morphology, transliteration, and dictionaries;
- monitor quality drift and coverage.

Exit gate: every supported language has its own documented benchmark and release metrics.

### Phase 5: Production and graph publication

- harden orchestration, monitoring, retries, lineage, and access controls;
- publish versioned datasets and query APIs;
- expose graph/RDF exports;
- evaluate a graph database only if traversal or graph-query workloads justify it.

## 12. Step-by-step implementation plan

### Step 1: Terminology database foundation

Status: implemented.

- PostgreSQL models for concepts, terms, types, identifiers, evidence, relations, and reviews;
- Alembic migration;
- Pydantic terminology contracts;
- controlled-type seeding;
- local Docker Compose configuration;
- schema tests.

Exit gate: migrations compile, schema tests pass, and controlled values can be seeded idempotently.

### Step 2: Canonical input contracts

Status: implemented.

- implement versioned `PatentInput` and `TextUnit` Pydantic models;
- define `PatentInputAdapter` as a protocol;
- represent languages with BCP 47 tags;
- distinguish title, abstract, claim, paragraph, and other text units;
- represent text origin explicitly;
- define typed validation and rejection reasons;
- create in-memory fixtures independent of CSV.

Exit gate: downstream code can be written and tested without knowing where input data came from.

### Step 3: First CSV input adapter

Status: implemented.

- implement a streaming CSV adapter for the current sample shape;
- parse quoted commas correctly;
- preserve source text for the normalization stage, including HTML entities;
- derive available languages from non-empty title columns;
- preserve source values and row identifiers;
- flag the empty Dutch field rather than claiming Dutch support;
- discover arbitrary `title_<language>` columns, including Chinese, Japanese, and Russian;
- produce adapter metrics for accepted/rejected rows;
- add golden tests for all sample rows and malformed cases.

Exit gate: every valid sample row becomes one validated `PatentInput`; extraction code contains no CSV-specific logic.

### Step 4: Text normalization

Status: implemented.

- preserve original text;
- add Unicode and whitespace normalization with offset mapping;
- normalize safe punctuation/spacing variants;
- implement separate profiles for general terms, chemical names, formulas, identifiers, and patent labels;
- keep chemistry-sensitive case, stereochemistry, hyphens, and brackets;
- version normalization rules;
- test variants such as `C0:1` and `C0: 1` while keeping `Co` distinct from `CO`.
- preserve Chinese, Japanese, Cyrillic, and other scripts without transliteration.

Exit gate: equivalent formatting receives the same search key without collapsing chemically distinct expressions.

### Step 5: English candidate extraction baseline

Status: core baseline implemented; external NER selection and benchmarking remain pending.

- evaluate ChemDataExtractor or a compatible broad chemical NER model;
- evaluate a ChEMU model for reaction-oriented text;
- add formula, identifier, abbreviation, quantity, and patent-label rules;
- add scientific noun-phrase and multi-word terminology extraction;
- preserve nested candidates and extractor provenance;
- create a generic candidate contract shared by every extractor.

Implemented components:

- typed candidate, role, issue, and extraction-result contracts;
- deterministic formula, identifier, quantity, abbreviation, and patent-label rules;
- transparent nested technical-phrase extraction;
- lazy Hugging Face token-classification adapter with ChEMU label mapping;
- exact source-span validation and original-offset projection;
- replaceable extractor/refiner protocols and a JSONL CLI.

Exit gate: each English text unit produces exact-span candidates with source methods and provisional types.

### Step 6: Candidate reconciliation and relevance

- merge identical spans while preserving all evidence;
- retain meaningful nested terms;
- detect conflicting boundaries;
- filter generic patent boilerplate;
- classify candidates into concept types and term forms;
- compute transparent score components;
- abstain when a candidate is ambiguous.

Exit gate: the pipeline yields a stable, reviewable English candidate list rather than raw model output.

### Step 7: Constrained LLM refinement

Status: integration implemented ahead of schedule; quality evaluation remains pending.

- define a strict JSON/Pydantic response contract;
- version prompts and model parameters;
- ask the LLM to accept/reject, correct exact boundaries, classify, and flag ambiguity;
- prohibit invented text and unsupported identifiers;
- validate every returned span against source text;
- compare baseline versus LLM-refined quality and cost.

The integration uses a provider-isolated OpenAI-compatible JSON-schema client, exact-substring validation, fixed type/role enums, fail-closed issue reporting, and optional configuration. It is disabled by default and is not production-qualified until benchmarked.

Exit gate: LLM refinement measurably improves held-out exact-span/type metrics without unacceptable hallucination or instability.

### Step 8: English concept resolution and deduplication

Status: retrieval and bounded LLM decision infrastructure implemented; external
vocabulary lookup, persistence, calibration, and PostgreSQL integration evaluation
remain pending.

- normalize candidates using the appropriate profile;
- search existing English terms globally before creating concepts;
- retrieve ChEBI/PubChem/Wikidata candidates;
- distinguish salts, hydrates, stereoisomers, polymers, mixtures, and classes;
- reuse compatible concepts;
- create proposed concepts when unresolved;
- select one preferred English term per concept;
- make all create operations idempotent.

Implemented components:

- controlled identifier namespaces with explicit identity strength and definitions;
- exact normalized-label and exact-identifier retrieval;
- PostgreSQL `pg_trgm` fuzzy retrieval and `pgvector` HNSW semantic retrieval;
- stable, meaning-bearing concept representations with content hashes;
- replaceable embedding provider, initially configured for 1024-dimensional BGE-M3;
- bounded candidate cards containing labels, aliases, types, identifiers, definition,
  and independent retrieval signals;
- live loading of active concept types and identifier definitions from PostgreSQL for
  every LLM resolution call;
- explicit same/new/related/ambiguous outcomes and controlled reason codes;
- chemistry-specific non-merge rules for salts, solvates, stereochemistry, classes,
  formulations, and formula-only matches;
- fail-closed rejection of invented concept IDs and unsafe ambiguous decisions.

The LLM does not define the ontology. `concept_type` and `identifier_namespace` are
the authoritative controlled vocabularies; `chemterm.seed` initializes them, and
`ConceptSearchRepository.vocabulary()` serializes their active definitions into each
resolution request. Retrieval narrows the candidate set, while the LLM may only
choose among supplied IDs or propose a new/ambiguous outcome.

Exit gate: rerunning the same input does not create duplicate concepts or terms.

### Step 9: Target-language term mapping

Status: core parallel-text LLM path implemented; quality evaluation and non-LLM candidate generators remain pending.

- select aligned target-language text units from the same input record/family;
- generate target spans through dictionaries, lexical alignment, and multilingual embeddings;
- use constrained LLM/cross-encoder ranking over text-present candidates;
- support `no_match`;
- perform reverse and type-compatibility checks;
- attach accepted target terms to the English-derived concept;
- keep candidate pairs temporary.

Implemented components:

- strict mapping relations for exact, contextual, broader, narrower, related, no-match, and ambiguous decisions;
- one LLM call per English/target-language text pair;
- direct use of existing parallel texts with an explicit prohibition on machine translation;
- exact target-substring and character-offset validation;
- complete one-decision-per-English-candidate coverage checks;
- original-offset projection through HTML/Unicode normalization;
- native-script support for Chinese, Japanese, Cyrillic, and other scripts;
- per-language failure isolation and fail-closed issue reporting;
- CLI support through `--pair-languages`.

Exit gate: German/French terms are connected through concepts with traceable evidence and measured precision.

### Step 10: Persistence service

- define a `TerminologyRepository` protocol;
- implement PostgreSQL repository transactions;
- provide atomic find-or-create operations for concepts and terms;
- record evidence sets and exact publication references;
- handle concurrent duplicate creation safely;
- keep SQLAlchemy models out of extraction code;
- add PostgreSQL integration tests.

Exit gate: extraction results can be persisted safely, idempotently, and independently from source adapters.

### Step 11: Evaluation and review

- annotate a family-held-out benchmark;
- report extraction, typing, normalization, and multilingual mapping separately;
- calibrate confidence scores;
- implement proposed/accepted/rejected/needs-expert review states;
- record expert decisions and error categories;
- establish release thresholds per language and concept type.

Exit gate: quality claims are based on independent reviewed data rather than pipeline self-agreement.

### Step 12: Orchestration and release

- compose stages through configuration rather than hard-coded imports;
- support restartable batch runs and manifests;
- add structured logging, metrics, and failure reports;
- export terminology-only Parquet/JSONL;
- create a Hugging Face dataset card;
- test backup/restore and release reproducibility;
- add new input adapters only after adapter contract tests pass.

Exit gate: a fixed manifest reproduces a versioned terminology release end to end.

## 13. Decisions required before implementation

These decisions materially affect architecture and evaluation:

1. **First language pair**: choose based on available original-language patent families and expert reviewers.
2. **Patent scope**: broad chemistry or a narrower domain such as coatings, catalysts, polymers, or agrochemicals.
3. **Definition of equivalence**: translation equivalence only, or also synonyms, broader/narrower concepts, and related forms.
4. **Source access**: approved bulk datasets and redistribution boundaries.
5. **Review resources**: languages, chemistry expertise, and annotation capacity.
6. **Output audience**: internal search/reranking, translator assistance, public glossary, or ontology integration.
7. **Precision target**: release threshold and acceptable abstention rate.

## 14. Recommended first experiment

Select one narrow chemical domain and one language pair with strong reviewer coverage. English-German or English-French are plausible based on the current sample, but the choice must be based on full-text availability, original-language status, and reviewer expertise—not title presence alone.

Manually validate 30 patent-family pairs, then annotate approximately 500 aligned passage pairs and 1,000 candidate term relations.

Compare three baselines:

1. normalized lexical and identifier matching;
2. multilingual embedding similarity;
3. a chemistry-aware reranker combining context, structure, lexical features, and constrained LLM judgments.

This experiment should answer the most important early question: whether the chosen patent pairs provide sufficiently faithful multilingual evidence to support a high-precision terminology resource.

## 15. Definition of done for the first professional release

The first release is complete only when:

- every accepted term-to-concept mapping is traceable to lightweight evidence;
- every evidence record identifies exact publications and source locators, not only a family;
- original and machine-translated text are distinguishable;
- database migrations can recreate the schema from an empty database;
- a documented command reproduces the release from a fixed input manifest;
- family-level leakage tests pass;
- expert-reviewed precision meets the agreed release threshold for each supported language;
- confidence is calibrated and low-confidence output remains proposed;
- source licenses and required attributions are included;
- PostgreSQL backup restoration has been tested;
- terminology-only Parquet/JSONL exports pass schema and referential-integrity checks;
- the Hugging Face dataset card describes sources, methods, limitations, metrics, and licenses;
- model versions, prompts, code revision, and configuration are recorded;
- no graph database is required to query terms, concepts, translations, or provenance.
