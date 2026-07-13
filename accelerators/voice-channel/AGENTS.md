# AGENTS.md — Voice Channel for Copilot Studio (Foundry IT Assistant)

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

An accelerator that gives a Copilot Studio agent a **real-time voice experience** and **native Teams / Microsoft 365 Copilot distribution** — **without** the Omnichannel / Contact Center Engagement Hub licence.

One Foundry **IT Assistant** agent serves **three surfaces**:

| Surface | Transport | Voice UX |
|---|---|---|
| Web UI (Container App) | Voice Live WebSocket, browser mic → PCM16 | Real-time full-duplex streaming, barge-in, HD voices |
| Microsoft Teams | Azure Bot Service (publish-copilot) | Text + M365 Copilot push-to-talk mic |
| M365 Copilot Chat | Azure Bot Service (same app package) | Text + push-to-talk mic |

The backend is grounded via a **Copilot Studio** agent ("Microsoft Learn Assistant") on the **Microsoft Learn MCP** server. Voice Live runs in **agent mode** (WebSocket connects by `agent_id`, so the Foundry agent's instructions + tools apply automatically). Adapted from [call-center-voice-agent-accelerator](https://github.com/Azure-Samples/call-center-voice-agent-accelerator).

## Project structure

| Path | Purpose |
|---|---|
| `azure.yaml` | azd service map |
| `infra/main.bicep` (+ `main.bicepparam`, `abbreviations.json`) | Foundry + Container App + ACR + Key Vault + Log Analytics + App Insights |
| `server/` | Python FastAPI Container App service (`app/main.py`, `voice_live.py` WS relay, `static/` Voice Live web UI) |
| `foundry-agent/` | IT Assistant Foundry Agent — instructions, `it-assistant.agent.json`, `ask-mcs.openapi.yaml` tool, `create-foundry-agent.ps1`, `publish-to-teams.ps1` |
| `copilot-studio-agent/` | "Microsoft Learn Assistant" declarative agent (`agent.yaml`, `tools/microsoft-learn-mcp.yaml`, topics, `create-agent.ps1`) |
| `teams-app/` | Teams personal-app tab package (`package.ps1` → `dist/teams-app.zip`) |
| `deploy/` | `azuredeploy.json` + `createUiDefinition.json` (one-click) + `README.md` |

## How an agent should work with it

- Two deploy paths: **azd** (`azd up`) or the **one-click portal button** (builds the server container via **ACR Tasks** — no local Docker needed on the portal path).
- After infra: run `foundry-agent/create-foundry-agent.ps1` (creates the IT Assistant agent + attaches the MCS tool + updates the Container App) and `foundry-agent/publish-to-teams.ps1` (publishes to Teams + M365). The Copilot Studio backend is created via `copilot-studio-agent/create-agent.ps1` (pac CLI, Direct Line).
- The server sets `Content-Security-Policy: frame-ancestors …teams.microsoft.com …microsoft365.com …cloud.microsoft` so the web UI iframes into Teams/M365; the client uses `@microsoft/teams-js` to detect the host and apply Teams theming.
- Requires the `Azure AI Project Manager` role on the Foundry project to publish agent applications; a Power Platform SPN is needed to auto-create the MCS agent + write the Direct Line secret to Key Vault.
- Default region on the azd path is `swedencentral`.

## Setup / deploy commands

```powershell
git clone https://github.com/Azure/Copilot-Studio-and-Azure.git
cd Copilot-Studio-and-Azure/accelerators/voice-channel

azd auth login
azd init         # first time only — pick a region
azd up           # Foundry, Container Apps, ACR, Key Vault, LA, App Insights + build/deploy web UI

# then:
./copilot-studio-agent/create-agent.ps1 -EnvironmentUrl 'https://<env>.crm.dynamics.com'
./foundry-agent/create-foundry-agent.ps1
./foundry-agent/publish-to-teams.ps1
```

Requires: `azd` 1.9+, Azure CLI 2.60+, `pac` 1.34+, Docker (or buildpacks), Copilot Studio-enabled Power Platform environment, M365 tenant admin.

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "Voice Channel for Copilot Studio"
  slug: "voice-channel"
  repo_path: "accelerators/voice-channel"
  maturity: "sample"
  primary_platform: "Azure AI Foundry (Voice Live, Agent Service) + Container Apps + Copilot Studio"

use_case:
  primary_scenario: "Voice-enabled Copilot Studio/Foundry agent across web, Teams, and M365 Copilot Chat without Contact Center licensing"
  features:
    - "Real-time full-duplex voice (Voice Live agent mode, barge-in, HD voices)"
    - "One agent serving 3 surfaces (web Container App, Teams, M365 Copilot Chat)"
    - "Copilot Studio + Microsoft Learn MCP grounded backend"
    - "Teams personal-app tab + Bot Service chat distribution"
  domain: "conversational voice assistant / IT helpdesk"
  extensibility: "Swap agent instructions/tools; point MCP at other servers; add channels"

agentic_patterns:
  orchestration: "Foundry Agent Service (agent mode) fronting Copilot Studio agent"
  tool_function_calling: "OpenAPI tool (ask-mcs) -> Copilot Studio Direct Line; Microsoft Learn MCP tool"
  memory_state: "per-session Voice Live WebSocket session"
  human_in_the_loop: "voice conversation (user in the loop)"
  guardrails: "Copilot Studio + Foundry agent instructions; CSP frame-ancestors restriction"

data_scenario:
  data_source_types: ["Microsoft Learn documentation (via MCP)"]
  connectors: ["Microsoft Learn MCP server", "Copilot Studio Direct Line"]
  retrieval_patterns: ["MCP tool retrieval / grounding"]
  transformation_pipelines: "none"

ai_stack:
  llm_provider: "Azure AI Foundry (Voice Live + Agent Service)"
  search_integration: "grounding via Copilot Studio + Microsoft Learn MCP"
  agent_framework: "Foundry Agent Service + Copilot Studio"
  observability: "Application Insights + Log Analytics"
  languages: ["Python (FastAPI)", "PowerShell", "JavaScript (web client)", "Bicep"]

hosting:
  compute_platform: "Azure Container Apps (+ ACR)"
  scaling_model: "container auto-scale"
  regional_availability: "Voice Live supported regions (default swedencentral)"

api_integration:
  internal_apis: "Copilot Studio Direct Line, Foundry Agent REST"
  external_saas_apis: ["Azure Bot Service", "Microsoft Teams / M365 Copilot", "Microsoft Learn MCP"]
  mcp_support: true
  auth: ["Managed identity", "Key Vault (Direct Line secret)", "Power Platform SPN", "Entra app (Bot)"]

ui_scenario:
  channels: ["Web (Container App)", "Microsoft Teams", "M365 Copilot Chat"]
  ui_framework: "static JS web client (Voice Live UI) + Teams personal app tab"
  ux_patterns: ["real-time streaming voice", "barge-in", "push-to-talk", "adaptive Teams theming"]

infrastructure:
  iac: "Bicep (infra/) + azd (azure.yaml) + ARM azuredeploy.json/createUiDefinition (one-click)"
  cicd: "azd up; ACR Tasks container build; PowerShell post-deploy scripts"
  monitoring: "Application Insights + Log Analytics"

stack_summary: ["Azure AI Foundry (Voice Live, Agent Service)", "Azure Container Apps", "ACR", "Azure Bot Service", "Copilot Studio", "Microsoft Learn MCP", "Key Vault", "Bicep", "azd", "pac CLI"]
```
