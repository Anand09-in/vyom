# Vyom (व्योम)

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

## Screenshots

| | |
|---|---|
| ![Chat](docs/screenshots/chat-answer.png) *Cited, grounded answer* | ![Sidebar](docs/screenshots/sidebar.png) *Per-user conversation history* |
| ![Routing](docs/screenshots/routing.png) *Live routing rationale* | ![Guardrail block](docs/screenshots/guardrail-block.png) *Prompt-injection caught* |

*(placeholders — drop PNGs into `docs/screenshots/`)*

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
        Generate["generate<br/>Bedrock Mistral Large 3<br/>+ 2nd guardrail check"]
        Classify --> Retrieve --> Grade
        Grade -->|"empty, loop < max"| Classify
        Grade -->|"chunks found"| Generate
    end

    Store["Redis history<br/>+ RDS query_log"]

    Browser -->|"Bearer ID token"| API --> Precheck
    Precheck -->|clear| Pipeline
    Precheck -.->|blocked| Blocked
    Generate -.->|guardrail blocked| Blocked
    Pipeline --> Store --> Browser
    Blocked --> Store

    RDS[("RDS<br/>pgvector")]
    Bedrock["Bedrock"]
    Tavily["Tavily"]
    Retrieve -.-> RDS & Tavily
    Generate -.-> Bedrock

    classDef blocked fill:#f5e3dc,stroke:#b4562a,color:#7a3016
    class Blocked blocked
```

## Engineering highlights

- **Root-caused a Terraform state-reconciliation bug in production** — mixing inline `ingress` blocks with a separate `aws_security_group_rule` caused every `apply` to silently delete the EC2→RDS access rule. Caught it via the health-check metric's own history.
- **Diagnosed an LLM citation-hallucination bug** — the model copied a literal example citation tag from its own system prompt when no matching source existed, because the example's index looked like a real one. Fixed with an explicit anti-hallucination instruction.
- **Debugged a guardrail false-positive cascade** — a blocked response's refusal text, once stored in history, kept re-triggering the injection classifier on later turns from prompt *shape* alone, independent of content. Fixed the storage layer and rescoped which calls need guardrail screening.

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

RAGAS on a 25-question golden set (single-turn + multi-turn):

| Faithfulness | Answer relevancy | Context precision | Context recall |
|---|---|---|---|
| 0.84 | 0.79 | 0.33 | 0.44 |

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
