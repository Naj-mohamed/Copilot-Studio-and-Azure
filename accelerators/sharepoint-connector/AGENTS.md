# AGENTS.md — SharePoint → Azure AI Search Connector

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

A **production-oriented push connector** (serverless Azure Function, Python) that keeps an **Azure AI Search** index in sync with one (or a subset of) SharePoint site so a **Copilot Studio** agent can ground answers on up-to-date enterprise content — while honouring each user's access rights via optional **per-user security trimming**.

It overcomes the built-in SharePoint knowledge source / AI Search SharePoint connector (preview) limitations: file-size caps (>200 MB), no private endpoint support, no Conditional Access compatibility, no SLA, no per-user trimming, and limited extraction control.

Core capabilities:
- **Unified multimodal index** — text + image content in the same vector space (**Azure OpenAI `text-embedding-3-large` (3072d)** embeddings + **`gpt-5.1`** image captioning; **Azure AI Vision** Florence multimodal 1024d as a regional fallback; optional Document Intelligence Layout).
- **Visio diagram search** — `.vsdx` (and `.vsd` via LibreOffice) shape/stencil labels extracted and indexed.
- **Video transcription** — video files transcribed via **Azure Speech Fast Transcription** (same Foundry AIServices account) into timestamped text blocks.
- **Metadata column filter** — `METADATA_FILTERS` (e.g. `DocumentStatusTX=Approved`) dispatches only files whose SharePoint column values match, before any download/embedding.
- **Scoped monitoring** — watch a whole site or just a folder/library.
- **Near-real-time deletion propagation** via Microsoft Graph `/delta`.
- **Least-privilege Graph access** (`Sites.Selected`), nightly backups.
- **Opt-in per-user security trimming** (adds `/api/search` endpoint, Entra app, Power Platform connection).

## Project structure

| Path | Purpose |
|---|---|
| `function_app.py` | Azure Functions entrypoint (dispatcher timer + queue workers) |
| `indexer.py` | Orchestrates delta scan → enqueue → index |
| `sharepoint_client.py` | Microsoft Graph `/delta` + file download |
| `document_processor.py`, `chunker.py`, `blocks.py` | Extraction + chunking pipeline |
| `doc_intelligence_client.py` | Document Intelligence Layout extraction |
| `visio_processor.py` | Visio `.vsdx`/`.vsd` shape + stencil label extraction |
| `openai_embeddings_client.py` | Azure OpenAI `text-embedding-3-large` embeddings + `gpt-5.1` captioning |
| `multimodal_embeddings_client.py` | Azure AI Vision Florence multimodal embeddings (regional fallback) |
| `content_understanding_client.py` | Azure AI Content Understanding client (optional extraction path) |
| `speech_transcription_client.py` | Azure Speech Fast Transcription for video files |
| `search_client.py`, `search_security.py` | AI Search index upsert + security trimming |
| `image_storage.py` | Image crop upload to blob for citation thumbnails |
| `state_store.py`, `index_backup.py` | Delta watermark/run state (Table); nightly backups |
| `enqueue_files.py` | Manually (re)queue specific files onto the indexer queue |
| `config.py`, `host.json`, `pyproject.toml`, `requirements.txt` | Config + Functions runtime + deps |
| `infra/` | Bicep + `deploy.ps1`; provisions everything + RBAC; operational report/health scripts |
| `deploy/` | `azuredeploy.json` (one-click Deploy to Azure) |
| `copilot-studio-topics/` | Copilot Studio topic YAML for the querying agent |
| `tests/` | Test suite |

## How an agent should work with it

- Runtime is **Azure Functions (Flex Consumption)**, Python; the code is pulled from a GitHub Release by the deployment (no local `func publish` needed for the default path).
- Deployment takes **two required params**: `baseName` (3–16 chars, lowercase a–z/0–9/hyphens only) and `sharePointSiteUrl`. Everything else is inferred/defaulted.
- The template creates: Storage (queue/table/blob), Log Analytics + App Insights, Azure AI Search (Basic), Microsoft Foundry / Azure AI Services multi-service (Vision multimodal), Document Intelligence (Layout), Key Vault, Flex Consumption plan, Function App, plus a small `*ds*` deployment-scripts storage account (`allowSharedKeyAccess: true`, tagged `purpose=arm-deployment-scripts`).
- **Auth is managed identity** end-to-end. Post-deploy, three required manual steps grant `Sites.Selected` and the per-site read (Cloud Application Administrator or higher). Skipping any yields Graph `401`/`403`.
- **Security trimming is OFF by default** (`enableSecurityTrimming=false`) — every authenticated agent user sees every chunk. Enabling it is a documented opt-in walkthrough.
- BYO storage supported via `existingStorageAccountResourceId` (requires pre-created containers/queues/tables + cross-RG RBAC).
- Use PowerShell 7+ (`pwsh`) for all helper scripts — Windows PowerShell 5.x will not work.

## Setup / deploy commands

```powershell
# One-click: use the "Deploy to Azure" button in README.md, OR:
az login
pwsh ./infra/deploy.ps1   # Bicep deploy (baseName + sharePointSiteUrl)
# Then run the post-deploy Sites.Selected grant scripts (pwsh, 3 required steps)
```

Run tests with `pytest` from the accelerator folder (see `tests/`).

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "SharePoint → Azure AI Search Connector"
  slug: "sharepoint-connector"
  repo_path: "accelerators/sharepoint-connector"
  maturity: "production-oriented"
  primary_platform: "Azure Functions (Flex Consumption) + Copilot Studio"

use_case:
  primary_scenario: "Grounded Copilot Studio agent over SharePoint content with multimodal retrieval and per-user security trimming"
  features:
    - "Push-model SharePoint -> AI Search sync via Graph /delta"
    - "Unified multimodal (text + image) vector index"
    - "Scoped monitoring (site or folder), deletion propagation, nightly backups"
    - "Optional per-user security trimming (ACL enforcement at query time)"
  domain: "enterprise knowledge / M365 content grounding"
  extensibility: "Add file formats, swap embedding model, change index schema, adjust concurrency, switch processing modes"
agentic_patterns:
  orchestration: "Copilot Studio built-in generative orchestration over AI Search knowledge source"
  tool_function_calling: "AI Search knowledge source connector; optional HTTP /api/search action for trimming"
  memory_state: "delta watermark + run state (Azure Table)"
  human_in_the_loop: "n/a (retrieval grounding)"
  guardrails: "per-user security trimming (permission_ids), least-privilege Sites.Selected"

data_scenario:
  data_source_types: ["SharePoint Online documents (text-heavy + image-heavy)"]
  connectors: ["Microsoft Graph /delta", "Azure AI Search knowledge source"]
  retrieval_patterns: ["vector", "keyword", "semantic ranker (hybrid)"]
  transformation_pipelines: ["Document Intelligence Layout", "chunking", "multimodal embedding", "image crop -> blob"]

ai_stack:
  llm_provider: "Copilot Studio (answer generation); Azure OpenAI text-embedding-3-large embeddings + gpt-5.1 image captioning; Azure AI Vision Florence multimodal as regional fallback; Azure Speech Fast Transcription for video"
  search_integration: "Azure AI Search (Basic)"
  agent_framework: "Copilot Studio"
  observability: "Log Analytics + Application Insights"
  languages: ["Python"]

hosting:
  compute_platform: "Azure Functions (Flex Consumption)"
  scaling_model: "serverless / queue-based scale-out (Storage Queue workers)"
  regional_availability: "region must support Azure OpenAI text-embedding-3-large + gpt-5.1 (Azure AI Vision multimodal 4.0 for the fallback path)"

api_integration:
  internal_apis: "Azure AI Search REST, Blob/Queue/Table"
  external_saas_apis: ["Microsoft Graph (SharePoint)"]
  mcp_support: false
  auth: ["Managed identity (end-to-end)", "Sites.Selected Graph app permission", "Entra app (trimming opt-in)"]

ui_scenario:
  channels: ["Copilot Studio agent (any published channel)"]
  ui_framework: "n/a (backend connector)"
  ux_patterns: ["citations / source thumbnails from image crops"]

infrastructure:
  iac: "Bicep (infra/) + ARM azuredeploy.json (one-click); deploy.ps1"
  cicd: "GitHub Releases-based code package pull via ARM deploymentScripts"
  monitoring: "Application Insights + Log Analytics"

stack_summary: ["Python", "Azure Functions (Flex Consumption)", "Azure AI Search", "Azure OpenAI (text-embedding-3-large + gpt-5.1)", "Azure AI Vision multimodal (fallback)", "Azure Speech Fast Transcription", "Document Intelligence Layout", "Storage (Queue/Table/Blob)", "Key Vault", "Microsoft Graph", "Copilot Studio"]
```
