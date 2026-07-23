"""Cross-language terminology mapping."""

from chemterm.mapping.base import ParallelTextMapper
from chemterm.mapping.llm_parallel import LlmParallelTextMapper, ParallelMappingError

__all__ = ["LlmParallelTextMapper", "ParallelMappingError", "ParallelTextMapper"]
