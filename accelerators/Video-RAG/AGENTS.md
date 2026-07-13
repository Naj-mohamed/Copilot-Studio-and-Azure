# AGENTS.md — Video RAG Accelerator

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

An **event-driven video ingestion pipeline** that makes video content searchable and citeable by a Copilot Studio agent. When a video is uploaded to Azure Blob Storage, an **Event Grid** trigger fires a **Logic App** workflow that:

- **Extracts** transcript + AI summary via **Azure Content Understanding**,
- **Generates** vector embeddings (`text-embedding-3-large`, 3072 dims),
- **Indexes** the content in **Azure AI Search** (HNSW vector + semantic config + OpenAI vectorizer).

The Copilot Studio agent then answers natural-language questions grounded in video content — no bespoke ML work.

Use cases: training video libraries, corporate knowledge management, educational repositories, media asset management.

## Project structure

| Path | Purpose |
|---|---|
| `README.md` | Full deployment + configuration walkthrough |
| `deploy/azuredeploy.json` | ARM template for one-click deployment (all resources) |
| `setup-sample-code/logic-app-sample-code.json` | Logic App workflow definition |
| `setup-sample-code/ai-search-index-schema.json` | AI Search index definition sample (`video-training-index`) |
| `images-samples/` | Architecture + screenshot references |
| `video-samples/` | Sample videos about Copilot Studio |

## How an agent should work with it

- Deployment is **ARM-first** (`deploy/azuredeploy.json`); the template wires resource URLs into the Logic App automatically and auto-creates the `video-training-index`.
- Prefer a **scripted deployment** of the ARM template (PowerShell `New-AzResourceGroupDeployment` or `az deployment group create`) over the manual "Deploy to Azure" portal clicks — it is repeatable and CI-friendly. The portal button remains the no-tooling fallback.
- Orchestration is **Logic Apps + Event Grid**, not custom code — edit the workflow via `logic-app-sample-code.json` rather than scaffolding a service.
- **Region-constrained**: Content Understanding is not available in all regions; the template restricts region selection to supported ones.
- Required model deployments: Azure OpenAI `text-embedding-3-large`; Content Understanding `gpt-4.1`, `gpt-4.1-mini`, `text-embedding-3-large`.
- **Auth is managed identity** — Logic App + AI Services use system-assigned identities with all RBAC assigned by the template (Storage Blob Data Reader, Storage Account Contributor, EventGrid EventSubscription Contributor, Cognitive Services User, Cognitive Services OpenAI User, Key Vault Secrets User). AI Search admin key is stored in Key Vault.
- Videos are uploaded to the `uploadedvideocontent` blob container to trigger the pipeline.

## Setup / deploy commands

Deploy the ARM template with a script instead of the portal clicks:

```powershell
# PowerShell (Az module)
Connect-AzAccount
New-AzResourceGroup -Name <rg-name> -Location <supported-region>
New-AzResourceGroupDeployment `
  -ResourceGroupName <rg-name> `
  -TemplateFile ./deploy/azuredeploy.json
```

```bash
# Azure CLI equivalent
az group create --name <rg-name> --location <supported-region>
az deployment group create \
  --resource-group <rg-name> \
  --template-file ./deploy/azuredeploy.json
```

This provisions Storage, Azure AI Services (Foundry) + models, AI Foundry Hub/Project, Key Vault, Azure OpenAI, Azure AI Search (+ index), the Logic App, and the Event Grid connection. Then add the AI Search index as a Copilot Studio knowledge source.

> Portal fallback: use the **"Deploy to Azure"** button in `README.md`.

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "Video RAG"
  slug: "video-rag"
  repo_path: "accelerators/Video-RAG"
  maturity: "sample"
  primary_platform: "Azure Logic Apps + Event Grid + Copilot Studio"

use_case:
  primary_scenario: "Automated video content processing for RAG-grounded Copilot Studio answers"
  features:
    - "Event-driven video ingestion on blob upload"
    - "Transcript + summary extraction via Content Understanding"
    - "Vector embedding + AI Search indexing (HNSW + semantic + vectorizer)"
    - "Natural-language Q&A over video content with citations"
  domain: "media / training / knowledge management"
  extensibility: "Edit Logic App workflow; adjust index schema; extend to other media types"

agentic_patterns:
  orchestration: "Logic Apps workflow (ingestion) + Copilot Studio generative orchestration (query)"
  tool_function_calling: "AI Search knowledge source consumed by Copilot Studio"
  memory_state: "none (indexing pipeline is stateless per event)"
  human_in_the_loop: "n/a"
  guardrails: "Copilot Studio grounding/safety"

data_scenario:
  data_source_types: ["video files (blob storage)"]
  connectors: ["Event Grid (blob events)", "Azure AI Search"]
  retrieval_patterns: ["vector search (HNSW)", "semantic ranking"]
  transformation_pipelines: ["Content Understanding video analysis", "embedding generation", "index upload"]

ai_stack:
  llm_provider: "Azure AI Foundry (gpt-4.1 / gpt-4.1-mini) + Azure OpenAI (embeddings)"
  search_integration: "Azure AI Search with OpenAI vectorizer"
  agent_framework: "Copilot Studio"
  observability: "Logic Apps run history / Azure Monitor"
  languages: ["Logic Apps (JSON workflow)", "ARM"]

hosting:
  compute_platform: "Azure Logic Apps (Consumption) + Event Grid"
  scaling_model: "event-driven / serverless"
  regional_availability: "restricted to Content Understanding supported regions"

api_integration:
  internal_apis: "Content Understanding, Azure OpenAI, AI Search REST"
  external_saas_apis: "none"
  mcp_support: false
  auth: ["Managed identity (system-assigned) + RBAC", "Key Vault secret for AI Search admin key"]

ui_scenario:
  channels: ["Copilot Studio agent (any published channel)"]
  ui_framework: "n/a (backend pipeline)"
  ux_patterns: ["grounded answers with citations to video content"]

infrastructure:
  iac: "ARM template (deploy/azuredeploy.json) — one-click, auto-wired"
  cicd: "none (portal deployment)"
  monitoring: "Logic Apps run history, Azure Monitor"

stack_summary: ["Azure Logic Apps", "Event Grid", "Azure AI Content Understanding", "Azure AI Foundry", "Azure OpenAI", "Azure AI Search", "Azure Storage", "Key Vault", "Copilot Studio"]
```
