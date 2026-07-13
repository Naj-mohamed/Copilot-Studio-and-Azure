# AGENTS.md — Private Endpoint for Content Understanding (Power Platform)

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

An **infrastructure-as-code accelerator** that hosts Azure AI services behind a **Private Endpoint** (no public network access) and exposes them to a **Power Platform Managed Environment** via **Enterprise Policy / VNet injection**, with a ready-to-import custom connector and end-to-end connectivity tests.

It exists because Power Platform is **not** a "trusted Microsoft service" for Cognitive Services, so `publicNetworkAccess=Disabled` + `bypass=AzureServices` will not let a Power Automate flow reach a private-endpoint-locked AI Services account. This ships the supported alternative: paired delegated subnets, Private DNS zones, a `Microsoft.PowerPlatform/enterprisePolicies` (vnet) resource, and the policy link.

Two sub-scenarios share the same pattern:
1. **Content Understanding** (`content-server/`) — `Microsoft.CognitiveServices/accounts` kind `AIServices`.
2. **Azure AI Search** (`ai-search/`) — `Microsoft.Search/searchServices`.

## Project structure

| Path | Purpose |
|---|---|
| `README.md` | Master entry point, shared prerequisites, region-mapping notes |
| `content-server/` | Content Understanding sub-scenario (Bicep/ARM `infra/`, connector, README) |
| `ai-search/` | Azure AI Search sub-scenario (Bicep/ARM `infra/`, connector, README) |
| `infra/` | Shared infrastructure templates |
| `scripts/` | PowerShell helpers (`link-enterprise-policy.ps1`, connectivity tests) |
| `powerplatform/` | Custom connector definition(s) to import via `pac` |
| `docs/` | Supporting docs |

## How an agent should work with it

- Core pattern: (1) disable public network access, (2) expose via Private Endpoint in a VNet, (3) link `enterprisePolicies` (Network Injection) to delegated Power Platform subnets (primary + secondary), (4) call from a Power Platform custom connector at flow runtime.
- **Managed Environment is required** — Sandbox environments cannot be linked to an Enterprise Policy.
- Private DNS zones matter: Content Understanding uses `privatelink.cognitiveservices.azure.com`, `privatelink.openai.azure.com`, `privatelink.services.ai.azure.com`; AI Search uses `privatelink.search.windows.net`.
- **The connector designer test page does NOT use VNet injection** — validate connectivity from a real Power Automate flow run, not the designer.
- Region mapping is explicit (e.g. `unitedstates` → primary `westus`, secondary `eastus`); see `regionMap` in the scenario Bicep.
- If updating Enterprise Policy VNet bindings: unlink first, redeploy, then re-link.

## Setup / deploy commands

```powershell
# 1) copy the scenario .env.example to .env and fill values
# 2) deploy infra (per scenario) via its ARM/Bicep template or deployment script
# 3) link the Enterprise Policy to the Power Platform environment
pwsh ./scripts/link-enterprise-policy.ps1   # calls Enable-SubnetInjection
# 4) push + test the custom connector
pac connector create ...
```

Requires: Azure subscription (Owner/Contributor), Azure CLI ≥ 2.50, PowerShell 7+, `pac` CLI, `Microsoft.PowerPlatform.EnterprisePolicies` module, Power Platform/Global Admin.

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "Private Endpoint for Content Understanding / AI Search (Power Platform)"
  slug: "private-endpoint"
  repo_path: "accelerators/private-endpoint"
  maturity: "sample"
  primary_platform: "Azure networking + Power Platform Enterprise Policy"

use_case:
  primary_scenario: "Private (no public network) access to Azure AI services from Power Platform via VNet injection"
  features:
    - "Private Endpoint + Private DNS for AI Services / AI Search"
    - "Power Platform Enterprise Policy (vnet) + delegated subnet injection"
    - "Importable custom connector + connectivity tests"
    - "Two sub-scenarios: Content Understanding and AI Search"
  domain: "secure networking / regulated enterprise integration"
  extensibility: "Reuse pattern for other Cognitive Services accounts"

agentic_patterns:
  orchestration: "n/a (networking/connectivity enabler for Copilot Studio flows)"
  tool_function_calling: "custom connector consumed as a Copilot Studio / Power Automate tool"
  memory_state: "n/a"
  human_in_the_loop: "n/a"
  guardrails: "network isolation (publicNetworkAccess=Disabled)"

data_scenario:
  data_source_types: ["Azure AI Content Understanding", "Azure AI Search"]
  connectors: ["Power Platform custom connector (private-endpoint routed)"]
  retrieval_patterns: ["AI Search query APIs", "Content Understanding analyzers"]
  transformation_pipelines: "n/a (connectivity layer)"

ai_stack:
  llm_provider: "Azure AI Services (Content Understanding) — models per downstream use"
  search_integration: "Azure AI Search (sub-scenario 2)"
  agent_framework: "Copilot Studio (consumer)"
  observability: "Azure diagnostics (adapt for production)"
  languages: ["Bicep / ARM", "PowerShell"]

hosting:
  compute_platform: "Azure VNet + Private Endpoint; Power Platform Managed Environment"
  scaling_model: "managed"
  regional_availability: "paired primary/secondary regions via regionMap (e.g. westus/eastus)"

api_integration:
  internal_apis: "Azure AI Services / AI Search REST over private endpoint"
  external_saas_apis: "none"
  mcp_support: false
  auth: ["API key", "network-level isolation via Enterprise Policy"]

ui_scenario:
  channels: ["Copilot Studio / Power Automate (backend connectivity)"]
  ui_framework: "n/a"
  ux_patterns: ["connector invocation"]

infrastructure:
  iac: "Bicep + ARM templates (per sub-scenario) + createUiDefinition"
  cicd: "scripted deployment (Azure CLI + PowerShell); pac connector create"
  monitoring: "Azure diagnostics (review/adapt for production)"

stack_summary: ["Bicep/ARM", "Azure AI Services (Content Understanding)", "Azure AI Search", "Private Endpoint", "Private DNS", "VNet", "Power Platform Enterprise Policy (vnet)", "Custom connector", "PowerShell", "pac CLI"]
```
