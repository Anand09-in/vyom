"""Bedrock provider — Amazon Bedrock for the AWS deployment.

Pay-per-token for generation. This is the provider used when VYOM_PROVIDER=bedrock.

Generation uses the Bedrock Converse API — one interface for all model families
(Claude, Titan, Llama, Mistral, DeepSeek) so switching models is a config
change, not a code change.

embed()/embed_query()/rerank() deliberately delegate to a local LocalProvider
instance rather than calling Bedrock's Titan/Rerank APIs: embedding and
reranking run cheaply and fast on local CPU/GPU with no per-call cost or
quota, whereas generation needs a model too large to run locally. So
"bedrock provider" here specifically means "generation via Bedrock, embedding
and reranking via local models" — not "everything via AWS." (Bedrock's
Rerank API is also blocked by an IAM permissions gap on this account, and its
Titan embed() implementation calls invoke_model once per text with no
batching — a real bottleneck at ingest volume — so local wins outright here
even setting quota concerns aside.)
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import cached_property

from vyom.config import Settings
from vyom.providers.base import Provider, RerankResult
from vyom.providers.local import LocalProvider

logger = logging.getLogger(__name__)


class BedrockProvider(Provider):
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @cached_property
    def _runtime(self):
        import boto3

        return boto3.client("bedrock-runtime", region_name=self._s.aws_region)

    @cached_property
    def _local(self) -> LocalProvider:
        return LocalProvider(self._s)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._local.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._local.embed_query(text)

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
        return self._local.rerank(query, documents, top_n=top_n)