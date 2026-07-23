"""English concept retrieval and resolution."""

from chemterm.resolution.contracts import (
    ConceptCard,
    ConceptProposal,
    ConceptResolutionDecision,
    IdentifierDefinition,
    ProposalIdentifier,
    ResolutionOutcome,
    ResolutionReason,
    ResolutionVocabulary,
    RetrievalScores,
    TypeDefinition,
)
from chemterm.resolution.embedding import (
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    concept_representation,
    proposal_representation,
)
from chemterm.resolution.llm_resolver import LlmConceptResolver
from chemterm.resolution.repository import ConceptSearchRepository
from chemterm.resolution.service import ConceptResolutionService

__all__ = [
    "ConceptCard",
    "ConceptProposal",
    "ConceptResolutionDecision",
    "ConceptResolutionService",
    "ConceptSearchRepository",
    "EmbeddingProvider",
    "IdentifierDefinition",
    "LlmConceptResolver",
    "ProposalIdentifier",
    "ResolutionOutcome",
    "ResolutionReason",
    "ResolutionVocabulary",
    "RetrievalScores",
    "SentenceTransformerEmbeddingProvider",
    "TypeDefinition",
    "concept_representation",
    "proposal_representation",
]
