"""End-to-end retrieval and bounded concept-resolution orchestration."""

from __future__ import annotations

from chemterm.resolution.contracts import (
    ConceptCard,
    ConceptProposal,
    ConceptResolutionDecision,
)
from chemterm.resolution.embedding import EmbeddingProvider, proposal_representation
from chemterm.resolution.llm_resolver import LlmConceptResolver
from chemterm.resolution.repository import ConceptSearchRepository


class ConceptResolutionService:
    """Search existing concepts before permitting concept creation."""

    def __init__(
        self,
        repository: ConceptSearchRepository,
        resolver: LlmConceptResolver,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        top_k: int = 8,
    ) -> None:
        self.repository = repository
        self.resolver = resolver
        self.embedding_provider = embedding_provider
        self.top_k = top_k

    def retrieve(self, proposal: ConceptProposal) -> tuple[ConceptCard, ...]:
        """Retrieve candidates with semantic search when a provider is configured."""

        query_embedding = None
        embedding_model = None
        if self.embedding_provider is not None:
            text = proposal_representation(proposal)
            query_embedding = self.embedding_provider.embed_queries([text])[0]
            if len(query_embedding) != self.embedding_provider.dimensions:
                raise ValueError("embedding provider returned an unexpected dimension")
            embedding_model = (
                self.embedding_provider.model_name,
                self.embedding_provider.model_version,
            )
        return self.repository.retrieve(
            proposal,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            top_k=self.top_k,
        )

    def resolve(self, proposal: ConceptProposal) -> ConceptResolutionDecision:
        """Retrieve, then ask the resolver using live controlled vocabulary."""

        candidates = self.retrieve(proposal)
        vocabulary = self.repository.vocabulary()
        return self.resolver.resolve(proposal, candidates, vocabulary)
