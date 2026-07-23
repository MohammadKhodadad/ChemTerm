"""Replaceable embedding providers and stable concept representations."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

from chemterm.models import EMBEDDING_DIMENSIONS
from chemterm.resolution.contracts import ConceptCard, ConceptProposal


class EmbeddingProvider(Protocol):
    """Port implemented by local or hosted embedding backends."""

    model_name: str
    model_version: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed canonical concept representations."""

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed incoming retrieval queries."""


class SentenceTransformerEmbeddingProvider:
    """Lazy sentence-transformers adapter, optional at runtime."""

    dimensions = EMBEDDING_DIMENSIONS

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        model_version: str = "default",
        *,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self._device = device
        self._model = None

    def _load(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install the embedding extra with `uv sync --extra embeddings`."
            ) from exc
        self._model = self._model or SentenceTransformer(
            self.model_name,
            revision=None if self.model_version == "default" else self.model_version,
            device=self._device,
        )
        if self._model.get_sentence_embedding_dimension() != self.dimensions:
            raise ValueError(
                f"{self.model_name} must produce {self.dimensions}-dimension embeddings"
            )
        return self._model

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._load().encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)


def concept_representation(card: ConceptCard) -> str:
    """Create deterministic embedding text from meaning-bearing fields only."""

    identifiers = "; ".join(
        f"{item.namespace}:{item.value}"
        for item in sorted(card.identifiers, key=lambda item: (item.namespace, item.value))
    )
    return "\n".join(
        part
        for part in (
            f"preferred term: {card.preferred_english_term or ''}",
            f"aliases: {'; '.join(sorted(card.aliases))}",
            f"types: {'; '.join(sorted(card.type_codes))}",
            f"identifiers: {identifiers}",
            f"definition: {card.english_definition or ''}",
        )
        if not part.endswith(": ")
    )


def proposal_representation(proposal: ConceptProposal) -> str:
    """Create a query representation from an incoming proposal."""

    identifiers = "; ".join(f"{item.namespace}:{item.value}" for item in proposal.identifiers)
    return "\n".join(
        part
        for part in (
            f"term: {proposal.term}",
            f"types: {'; '.join(proposal.type_codes)}",
            f"identifiers: {identifiers}",
            f"context: {proposal.context}",
        )
        if not part.endswith(": ")
    )


def representation_hash(text: str) -> str:
    """Hash canonical representation text for idempotent refreshes."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
