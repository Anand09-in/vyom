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
from vyom.providers.base import GuardrailBlocked, Provider, RerankResult
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

    def _guardrail_config(self) -> dict | None:
        """Prompt-injection / off-topic defense on generation only — see
        infra/main.tf's aws_bedrock_guardrail.vyom. Enforced by Bedrock
        itself via the Converse API, not a code-level filter here. None if
        no guardrail is configured (e.g. running without infra applied)."""
        if not self._s.bedrock_guardrail_id:
            return None
        return {
            "guardrailIdentifier": self._s.bedrock_guardrail_id,
            "guardrailVersion": self._s.bedrock_guardrail_version,
            "trace": "enabled",
        }

    def check_guardrail(self, text: str) -> str | None:
        """Fast up-front check via Bedrock's standalone ApplyGuardrail API —
        runs on the raw query alone, before retrieval, so an obvious
        injection attempt is rejected without paying for embedding/search/
        rerank/HyDE first. See Provider.check_guardrail's docstring for why
        this is separate from generate()'s guardrailConfig."""
        guardrail = self._guardrail_config()
        if not guardrail:
            return None
        resp = self._runtime.apply_guardrail(
            guardrailIdentifier=guardrail["guardrailIdentifier"],
            guardrailVersion=guardrail["guardrailVersion"],
            source="INPUT",
            content=[{"text": {"text": text}}],
        )
        if resp.get("action") != "GUARDRAIL_INTERVENED":
            return None
        return self._blocked_message(resp)

    def _blocked_message(self, resp: dict) -> str:
        """Bedrock's own blocked_input_messaging is a single generic string
        configured once at the guardrail resource level and returned
        verbatim no matter which policy actually fired — so a guaranteed-
        return question was getting told it "looks like an attempt to
        override instructions," which is simply wrong. Inspect the
        assessment to find the real reason and return a message that
        matches it instead."""
        assessment = (resp.get("assessments") or [{}])[0]

        topics = {
            t["name"]
            for t in assessment.get("topicPolicy", {}).get("topics", [])
            if t.get("detected")
        }
        if "investment-recommendations" in topics:
            return (
                "Vyom isn't a SEBI-registered investment adviser, so it "
                "can't recommend a specific security to buy or sell, or "
                "promise a guaranteed/fixed return — market-linked "
                "investments always carry risk."
            )
        if "illegal-cross-border-funds" in topics:
            return (
                "This request can't be processed — it asks for help moving "
                "money across India's borders in a way that would evade "
                "FEMA reporting or tax obligations."
            )

        filters = {
            f["type"]
            for f in assessment.get("contentPolicy", {}).get("filters", [])
            if f.get("detected")
        }
        if "PROMPT_ATTACK" in filters:
            return (
                "This request can't be processed — it looks like an attempt "
                "to override Vyom's instructions rather than a genuine "
                "question about Indian financial or regulatory data."
            )

        if assessment.get("sensitiveInformationPolicy", {}).get("regexes"):
            return (
                "This request can't be processed — it contains a personal "
                "identifier Vyom won't handle."
            )

        outputs = resp.get("outputs", [])
        if outputs:
            return outputs[0]["text"]
        return (
            "This request can't be processed — it doesn't look like a "
            "genuine question about Indian financial or regulatory data."
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._local.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._local.embed_query(text)

    def generate(
        self, prompt: str, *, system: str | None = None, apply_guardrail: bool = True
    ) -> str:
        guardrail = self._guardrail_config() if apply_guardrail else None
        resp = self._runtime.converse(
            modelId=self._s.bedrock_gen_model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system=[{"text": system}] if system else [],
            **({"guardrailConfig": guardrail} if guardrail else {}),
        )
        text = resp["output"]["message"]["content"][0]["text"]
        if resp.get("stopReason") == "guardrail_intervened":
            logger.warning(
                "Bedrock Guardrails intervened on a generate() call. Trace: %s\nPrompt was: %s",
                resp.get("trace"), prompt[:3000],
            )
            raise GuardrailBlocked(text)
        return text

    def stream(
        self, prompt: str, *, system: str | None = None, apply_guardrail: bool = True
    ) -> Iterator[str]:
        guardrail = self._guardrail_config() if apply_guardrail else None
        resp = self._runtime.converse_stream(
            modelId=self._s.bedrock_gen_model,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system=[{"text": system}] if system else [],
            **({"guardrailConfig": guardrail} if guardrail else {}),
        )
        for event in resp["stream"]:
            if "contentBlockDelta" in event:
                yield event["contentBlockDelta"]["delta"]["text"]
            if event.get("messageStop", {}).get("stopReason") == "guardrail_intervened":
                logger.warning("Bedrock Guardrails intervened on a stream() call")

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        return self._local.rerank(query, documents, top_n=top_n)