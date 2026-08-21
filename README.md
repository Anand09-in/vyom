# Vyom

**Multi-source agentic RAG over Indian fintech data** — BSE/NSE filings, SEBI circulars, RBI macro data, and live web search, fused into one cited answer.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-Bedrock%20%C2%B7%20RDS%20%C2%B7%20EC2%20%C2%B7%20Cognito-FF9900?logo=amazonaws&logoColor=white)
![Terraform](https://img.shields.io/badge/IaC-Terraform-844FBA?logo=terraform&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

| **4** sources fused | **97** Nifty 100 companies | **0.84** RAGAS faithfulness | **100%** Terraform |
|---|---|---|---|

## What it does

> "HDFC Bank's annual report flags rising NPA risk in unsecured lending — what does RBI's latest policy say about the repo rate, and is there any current news that would affect this?"

A single-source RAG can't answer that — it needs a BSE filing, RBI macro data, *and* a live web search, fused into one cited answer. Vyom routes each query to the right source(s), retrieves, and answers only from what it actually found — with inline citations back to the exact filing, circular, series, or web result.

## Glimpses

| | |
|---|---|
| ![Sign-in and product overview](docs/screenshots/login.png) <br> **Sign-in and product overview** — the sign-in screen doubles as the product pitch, with the headline, source badges, and live stats alongside the auth form. | ![Cross-source answer with citations](docs/screenshots/chat3.png) <br> **Cross-source answers with citations** — a markdown table pulling from BSE, SEBI, and RBI, followed by a live-web price lookup, with every claim tagged back to its source. |
| ![Layered guardrails](docs/screenshots/guardrail.png) <br> **Layered guardrails** — a topic-policy block, a system-prompt rule catching a softer prompt-extraction attempt, and a history-safe placeholder for an earlier block, all within one conversation. | ![CloudWatch dashboard](docs/screenshots/dashboard.png) <br> **Production monitoring** — CPU, memory, health-check uptime, latency, and error/blocked counts on a single CloudWatch dashboard. |
| ![CloudWatch alarms](docs/screenshots/alarms.png) <br> **CloudWatch alarms** — five alarms covering disk usage, health checks, CPU, and instance status checks. | ![RAGAS metrics in MLflow](docs/screenshots/metrics.png) <br> **RAGAS evaluation in MLflow** — scores logged against a 31-question golden set, matching the evaluation table below. |

## Architecture

```mermaid
flowchart TD
    Browser["Browser<br/>Next.js chat UI"]
    API["FastAPI<br/>Cognito JWT verify"]
    Precheck{{"guardrail<br/>pre-check"}}
    Blocked["blocked response"]

    subgraph Pipeline["LangGraph pipeline"]
        direction TB
        Classify["classify_and_rewrite<br/>route() · HyDE"]
        Retrieve["retrieve_all<br/>hybrid search + rerank<br/>BSE · SEBI · RBI · live web"]
        Grade{"grade"}
        Generate["generate<br/>Bedrock Mistral Large 3"]
        Classify --> Retrieve --> Grade
        Grade -->|"empty, loop < max"| Classify
        Grade -->|"chunks found"| Generate
    end

    Store["Redis history<br/>+ RDS query_log"]

    Browser -->|"Bearer ID token"| API --> Precheck
    Precheck -->|clear| Pipeline
    Precheck -.->|blocked| Blocked
    Pipeline --> Store
    Blocked --> Store

    RDS[("RDS<br/>pgvector")]
    Bedrock["Bedrock"]
    Tavily["Tavily"]
    Retrieve -.-> RDS & Tavily
    Generate -.-> Bedrock

    classDef blocked fill:#f5e3dc,stroke:#b4562a,color:#7a3016
    class Blocked blocked
```

<!-- ## Engineering highlights

- **Root-caused a Terraform state-reconciliation bug in production** — mixing inline `ingress` blocks with a separate `aws_security_group_rule` caused every `apply` to silently delete the EC2→RDS access rule. Caught it via the health-check metric's own history.
- **Diagnosed an LLM citation-hallucination bug** — the model copied a literal example citation tag from its own system prompt when no matching source existed, because the example's index looked like a real one. Fixed with an explicit anti-hallucination instruction.
- **Debugged a guardrail false-positive cascade** — a blocked response's refusal text, once stored in history, kept re-triggering the injection classifier on later turns from prompt *shape* alone, independent of content. Fixed the storage layer and rescoped which calls need guardrail screening.
- **Layered SEBI/FEMA compliance guardrails, and scoped them to what actually applies** — audited a battery of adversarial test prompts (unauthorized investment advice, guaranteed-return claims, cross-border capital-flight requests, system-prompt extraction) and fixed the two real gaps: an explicit no-investment-advice/no-guaranteed-returns rule and an anti-prompt-disclosure rule, backed by Bedrock Guardrail topic-denial and PII-regex policies as defense-in-depth. Declined to "fix" a PAN/Aadhaar-leak scenario that assumed a KYC data store Vyom doesn't have — the underlying injection pattern was already covered, the premise wasn't. -->

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| API | FastAPI (nginx + systemd on EC2) |
| Database / cache | PostgreSQL + pgvector (RDS) · Redis (ElastiCache) |
| Generation / guardrails | Amazon Bedrock — Mistral Large 3 + Guardrails |
| Embedding / reranking | `nomic-embed-text-v1.5` · `bge-reranker-v2-m3` (local) |
| Live search | Tavily |
| Auth | Amazon Cognito |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind |
| Evaluation | RAGAS + MLflow |
| Infra / observability | Terraform · CloudWatch (logs, alarms, dashboard) |

## Evaluation

RAGAS on a 31-question golden set (single-turn + multi-turn):

| Faithfulness | Answer relevancy | Context precision | Context recall |
|---|---|---|---|
| 0.84 | 0.79 | 0.33 | 0.44 |

![RAGAS metrics in MLflow](docs/screenshots/metrics.png)

## Running locally

```bash
cp .env.example .env && docker compose up -d
pip install -e ".[api,cloud,local]"
uvicorn src.vyom.api.app:app --reload

cd frontend && npm install && npm run dev
```

Deployment is fully Terraform-managed — see `infra/main.tf`.

## Author

**[Anand09-in](https://github.com/Anand09-in)**

## License

[MIT](LICENSE)
