# AGENTS.md — Azure AI Search Flow Accelerator

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

A **Power Automate cloud flow + custom connector** (packaged as a solution-aware `.zip`) that connects Microsoft Copilot Studio to **Azure AI Search** without writing code or managing infrastructure. A single manual-trigger flow exposes three operations via a `Switch` on the `Action` input:

- `CreateIndex` — create a new search index
- `UploadDocuments` — push documents into an index
- `Search` — run a semantic/keyword search with `select`, `filter`, `facets`, `top`, `api-version`

Target user: **low-code / citizen developers** who want a supported Power Platform path into Azure AI Search.

## Project structure

| Path | Purpose |
|---|---|
| `readme.md` | Full import + configuration + usage walkthrough |
| `test-sample/` | `.http` sample request bodies for CreateIndex / UploadDocuments / Search |
| `images/` | Screenshots for the setup walkthrough |

There is **no source code to build** — the deliverable is an importable Power Platform solution (flow + custom connector + connection references).

## How an agent should work with it

- Do **not** scaffold a build; this is a Power Platform solution import, not a compiled app.
- The importable solution is `AccelerationAISearch_1_0_0_4.zip` in this folder.
- Preferred setup is **scripted via the `pac` CLI** (`pac solution import`); the Power Apps portal import is the manual fallback.
- After import: edit the `3ActionAISearch` custom connector → set the AI Search host (`<name>.search.windows.net`, no `https://`) → create an api-key connection on the **Test** tab → **Update connector**.
- Authentication is **API key** against Azure AI Search (`api-key` header). No managed identity in the default flow.
- `api-version` defaults to `2025-09-01`; override via trigger input.
- When editing the flow logic, preserve the variable-initialization + conditional-set + `Switch` pattern documented in `readme.md`.

## Setup / deploy commands

Import the solution with the **Power Platform CLI (`pac`)** instead of clicking through the portal:

```powershell
# 1) Authenticate to the target environment (opens a browser)
pac auth create --environment https://<your-env>.crm.dynamics.com

# 2) Import the solution-aware package
pac solution import --path ./AccelerationAISearch_1_0_0_4.zip --publish-changes --activate-plugins

# 3) (optional) confirm the import
pac solution list
```

Then configure the `3ActionAISearch` connector (AI Search host + api-key connection) and test the flow from Copilot Studio's **Test** panel. Install `pac` with `dotnet tool install --global Microsoft.PowerApps.CLI.Tool`; verify sign-in with `pac auth list`.

> Portal fallback: **Power Apps → Solutions → Import solution → Publish all customizations**.

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "Azure AI Search Flow"
  slug: "aisearch"
  repo_path: "accelerators/aisearch"
  maturity: "sample"
  primary_platform: "Power Platform (Copilot Studio + Power Automate)"

use_case:
  primary_scenario: "Low-code Azure AI Search integration for Copilot Studio (index creation, document upload, semantic search)"
  features:
    - "Create Azure AI Search index from Power Automate"
    - "Upload/ingest documents into an index"
    - "Semantic + keyword search with filter/facets/select/top"
  domain: "horizontal / knowledge retrieval"
  extensibility: "Add operations to the Switch action; adjust index schema via request body"

agentic_patterns:
  orchestration: "Copilot Studio generative orchestration calls the flow as a tool"
  tool_function_calling: "Flow exposed as a Copilot Studio tool/action"
  memory_state: "none (stateless flow)"
  human_in_the_loop: "n/a"
  guardrails: "relies on Copilot Studio built-in grounding/safety"

data_scenario:
  data_source_types: ["structured/unstructured documents via AI Search index"]
  connectors: ["Azure AI Search custom connector (REST)"]
  retrieval_patterns: ["keyword", "semantic search"]
  transformation_pipelines: "none (caller supplies index schema + documents)"

ai_stack:
  llm_provider: "none directly (search only); LLM supplied by Copilot Studio"
  search_integration: "Azure AI Search"
  agent_framework: "Copilot Studio"
  observability: "Power Automate run history"
  languages: ["Power Automate (no-code)", "JSON request bodies"]

hosting:
  compute_platform: "Power Platform managed (Dataverse cloud flow)"
  scaling_model: "managed / serverless"
  regional_availability: "follows Power Platform environment + Azure AI Search region"

api_integration:
  internal_apis: "Azure AI Search REST API"
  external_saas_apis: "none"
  mcp_support: false
  auth: ["API key"]

ui_scenario:
  channels: ["Copilot Studio agent (any published channel)"]
  ui_framework: "n/a (backend flow)"
  ux_patterns: ["tool/action invocation from agent"]

infrastructure:
  iac: "none (solution .zip import)"
  cicd: "Power Platform solution ALM (managed/unmanaged export-import)"
  monitoring: "Power Automate analytics / run history"

stack_summary: ["Power Automate", "Custom Connector", "Azure AI Search", "Copilot Studio"]
```
