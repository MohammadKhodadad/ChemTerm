"""Provider-isolated structured JSON LLM client."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Protocol

import httpx
from pydantic import BaseModel


class StructuredLlmClient(Protocol):
    """Port used by LLM refiners."""

    model: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        """Return one schema-constrained JSON object."""

        ...


class LlmHttpError(RuntimeError):
    """HTTP failure with provider diagnostics but no request credentials."""


def _strict_json_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Adapt Pydantic JSON Schema to OpenAI's strict structured-output subset."""

    schema = deepcopy(response_model.model_json_schema())

    def normalize(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["additionalProperties"] = False
                node["required"] = list(properties)
            for value in node.values():
                normalize(value)
        elif isinstance(node, list):
            for value in node:
                normalize(value)

    normalize(schema)
    return schema


class OpenAICompatibleJsonClient:
    """Small OpenAI-compatible Chat Completions JSON-schema client."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        self.model = model
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        """Call a JSON-schema-capable Chat Completions endpoint."""

        response = self._client.post(
            self._endpoint,
            json={
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "chemterm_terminology_extraction",
                        "strict": True,
                        "schema": _strict_json_schema(response_model),
                    },
                },
            },
        )
        if not response.is_success:
            raise LlmHttpError(
                f"LLM request failed with HTTP {response.status_code}: {response.text}"
            )
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("LLM response content was not a JSON string")
        return response_model.model_validate_json(content).model_dump(mode="json")

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""

        self._client.close()

    def __enter__(self) -> OpenAICompatibleJsonClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
