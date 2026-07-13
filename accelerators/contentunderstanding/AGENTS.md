# AGENTS.md — Content Understanding Flow Accelerator

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

A **Power Automate cloud flow + custom connector** (packaged as a solution-aware `.zip`) that connects Microsoft Copilot Studio to **Azure AI Content Understanding** for multimodal extraction over **documents, images, audio, and video**. It turns unstructured enterprise content into structured, grounded outputs using prebuilt analyzers, without writing code.

The flow starts with a manual trigger (inputs: `BaseUrl`, `Body`, `Subscription Key`, `Operation`, `api-version`), initializes defaults (`operation-type` = `prebuilt-invoice`, `api-version` = `2025-11-01`), then calls the Content Understanding API for the selected operation.

Target user: **low-code / citizen developers** who need multimodal document/media analysis from a Power Automate flow.

## Project structure

| Path | Purpose |
|---|---|
| `readme.md` | Full import, Content Understanding defaults setup, connector config, and usage walkthrough |
| `images/` | Screenshots for the setup walkthrough |

There is **no source code to build** — the deliverable is an importable Power Platform solution (flow + custom connector + connection references).

## How an agent should work with it

- Do **not** scaffold a build; this is a Power Platform solution import.
- The importable solution is `ContentUnderstandingAccelerator_1_0_0_2.zip` in this folder.
- Preferred setup is **scripted via the `pac` CLI** (`pac solution import`); the Power Apps portal import is the manual fallback.
- **Prerequisite that is easy to miss:** Content Understanding **defaults must be set** (Azure AI Foundry → Content Understanding settings → Add Foundry resource → enable autodeployment). If skipped, the flow fails with `"Defaults have not yet been set. Call 'PATCH /contentunderstanding/defaults' first."`
- Required Foundry model deployments: `GPT-4.1` / `GPT-4.1-mini` (document analysis) and `text-embedding-3-large` (search-based analyzers). Different prebuilt analyzers require different models.
- Connector host is `<name>.services.ai.azure.com` (no `https://`). Authentication is **API key** (`Subscription Key`); local/API-key auth must be enabled on the AI Services resource.
- `api-version` defaults to `2025-11-01`; override via trigger input.

## Setup / deploy commands

Import the solution with the **Power Platform CLI (`pac`)** instead of clicking through the portal:

```powershell
# 1) Authenticate to the target environment (opens a browser)
pac auth create --environment https://<your-env>.crm.dynamics.com

# 2) Import the solution-aware package
pac solution import --path ./ContentUnderstandingAccelerator_1_0_0_2.zip --publish-changes --activate-plugins

# 3) (optional) confirm the import
pac solution list
```

Then set Content Understanding defaults in Azure AI Foundry, configure the connector (host + api-key connection), and test the flow from Copilot Studio's **Test** panel. Install `pac` with `dotnet tool install --global Microsoft.PowerApps.CLI.Tool`; verify sign-in with `pac auth list`.

> Portal fallback: **Power Apps → Solutions → Import solution → Publish all customizations**.

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "Content Understanding Flow"
  slug: "contentunderstanding"
  repo_path: "accelerators/contentunderstanding"
  maturity: "sample"
  primary_platform: "Power Platform (Copilot Studio + Power Automate)"

use_case:
  primary_scenario: "Low-code multimodal content analysis (documents, images, audio, video) for Copilot Studio"
  features:
    - "Prebuilt analyzers (e.g. prebuilt-invoice) via Content Understanding"
    - "Document / image / audio / video extraction to structured output"
    - "Selectable operation + api-version from the flow trigger"
  domain: "horizontal / document + media intelligence"
  extensibility: "Swap operation-type / analyzer; extend for custom analyzers"

agentic_patterns:
  orchestration: "Copilot Studio generative orchestration calls the flow as a tool"
  tool_function_calling: "Flow exposed as a Copilot Studio tool/action"
  memory_state: "none (stateless flow)"
  human_in_the_loop: "n/a"
  guardrails: "relies on Copilot Studio built-in grounding/safety"

data_scenario:
  data_source_types: ["unstructured documents", "images", "audio", "video"]
  connectors: ["Azure AI Content Understanding custom connector (REST)"]
  retrieval_patterns: ["structured extraction / analysis (not vector retrieval)"]
  transformation_pipelines: "Content Understanding prebuilt analyzers"

ai_stack:
  llm_provider: "Azure AI Foundry (GPT-4.1 / GPT-4.1-mini)"
  search_integration: "text-embedding-3-large for search-based analyzers"
  agent_framework: "Copilot Studio"
  observability: "Power Automate run history"
  languages: ["Power Automate (no-code)", "JSON request bodies"]

hosting:
  compute_platform: "Power Platform managed (Dataverse cloud flow) + Azure AI Services"
  scaling_model: "managed / serverless"
  regional_availability: "follows Content Understanding supported regions"

api_integration:
  internal_apis: "Azure AI Content Understanding REST API"
  external_saas_apis: "none"
  mcp_support: false
  auth: ["API key (subscription key)"]

ui_scenario:
  channels: ["Copilot Studio agent (any published channel)"]
  ui_framework: "n/a (backend flow)"
  ux_patterns: ["tool/action invocation from agent"]

infrastructure:
  iac: "none (solution .zip import); requires Content Understanding + Foundry resource"
  cicd: "Power Platform solution ALM (managed/unmanaged export-import)"
  monitoring: "Power Automate analytics / run history"

stack_summary: ["Power Automate", "Custom Connector", "Azure AI Content Understanding", "Azure AI Foundry", "Copilot Studio"]
```
