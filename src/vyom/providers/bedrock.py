"""Bedrock provider — Amazon Bedrock for the AWS deployment.

Pay-per-token. No models to host, so idle cost is near zero.
This is the provider used when VYOM_PROVIDER=bedrock.

Generation uses the Bedrock Converse API — one interface for all model families
(Claude, Titan, Llama) so switching models is a config change, not a code change.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from functools import cached_property

from vyom.config import Settings
from vyom.providers.base import Provider, RerankResult

logger = logging.getLogger(__name__)


class BedrockProvider(Provider):
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @cached_property
    def _runtime(self):
        import boto3

        return boto3.client("bedrock-runtime", region_name=self._s.aws_region)

    @cached_property
    def _agent_runtime(self):
        # Rerank lives on the bedrock-agent-runtime surface
        import boto3

        return boto3.client("bedrock-agent-runtime", region_name=self._s.aws_region)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Titan embeds one text per API call."""
        results: list[list[float]] = []
        for text in texts:
            resp = self._runtime.invoke_model(
                modelId=self._s.bedrock_embed_model,
                body=json.dumps({"inputText": text}),
            )
            results.append(json.loads(resp["body"].read())["embedding"])
        return results

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        resp = self._runtime.converse(
            modelId=self._s.bedrock_gen_model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system=[{"text": system}] if system else [],
        )
        return resp["output"]["message"]["content"][0]["text"]

    def stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        resp = self._runtime.converse_stream(
            modelId=self._s.bedrock_gen_model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system=[{"text": system}] if system else [],
        )
        for event in resp["stream"]:
            if "contentBlockDelta" in event:
                yield event["contentBlockDelta"]["delta"]["text"]

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        resp = self._agent_runtime.rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": query}}],
            sources=[
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {
                        "type": "TEXT",
                        "textDocument": {"text": doc},
                    },
                }
                for doc in documents
            ],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "numberOfResults": top_n or len(documents),
                    "modelConfiguration": {
                        "modelArn": self._s.bedrock_rerank_model,
                    },
                },
            },
        )
        return [
            RerankResult(index=r["index"], score=float(r["relevanceScore"]))
            for r in resp["results"]
        ]