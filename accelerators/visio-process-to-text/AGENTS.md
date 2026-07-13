# AGENTS.md — Visio Process → Text

> Machine-readable guide for AI coding agents (GitHub Copilot, Agent Forge / FAF) working with this accelerator.
> The **FAF Evaluation Metadata** section maps this accelerator to the Implementation Recommender Agent's 8 scoring areas so it can be scored automatically as an implementation candidate.

## What this accelerator is

A **deterministic Python CLI** (`visio_to_text.py`, standard library only — **no LLM**) that converts Visio process / flowchart diagrams (`.vsdx` and `.vsd`) into plain-text **process pseudo-information** so they can be ingested by Copilot Studio (or any RAG pipeline) that does not support Visio files.

It reads the diagram, rebuilds the flow graph from Visio's connector (`<Connects>`) table, and emits a readable indented outline with `START`, steps, `DECISION:` nodes, `IF YES` / `IF NO` branches, loop-back markers (`(go to) <step>`), multi-page headers, and standalone notes.

## Project structure

| Path | Purpose |
|---|---|
| `README.md` | Usage, output format, and how-it-works explanation |
| `visio_to_text.py` | The entire converter (single-file CLI) |

## How an agent should work with it

- **Pure standard library** — no `pip install` needed. Do not add dependencies unless asked.
- **Deterministic by design** — do not introduce an LLM into the conversion path; that is a core property of this tool.
- `.vsdx` is parsed directly (it is an OPC/ZIP of XML: `visio/pages/page*.xml`). Legacy binary `.vsd` requires **LibreOffice** (`soffice --headless`) to auto-convert to `.vsdx`; otherwise "Save As" `.vsdx` in Visio.
- Graph edges come from the `<Connects>` table (`BeginX` → source, `EndX` → target); connector text becomes the branch label. `DECISION:` = a node with >1 outgoing connector.
- Requires Python 3.10+.

## Setup / run commands

```powershell
# Convert every .vsd/.vsdx in ./input -> ./output/*.txt
python visio_to_text.py

# Convert a single file to a chosen output folder
python visio_to_text.py "input/Chylothorax algorithm.vsdx" --out output

# Convert a folder
python visio_to_text.py ./diagrams --out ./text
```

Each input diagram produces one `.txt` file with the same base name.

---

## FAF Evaluation Metadata

Consumed by the FAF **Implementation Recommender Agent** (`accelerators-scoring-card.md`). Values describe what this accelerator *already provides*.

```yaml
accelerator:
  name: "Visio Process to Text"
  slug: "visio-process-to-text"
  repo_path: "accelerators/visio-process-to-text"
  maturity: "utility"
  primary_platform: "Python CLI (local)"

use_case:
  primary_scenario: "Convert Visio flowcharts to plain-text process outlines for RAG ingestion"
  features:
    - "Deterministic .vsdx / .vsd parsing (no LLM)"
    - "Flow graph reconstruction with decisions, branches, loops"
    - "Multi-page + standalone-notes handling"
  domain: "data preparation / RAG pre-processing"
  extensibility: "Adjust output format; extend shape/geometry handling"

agentic_patterns:
  orchestration: "n/a (offline pre-processing utility)"
  tool_function_calling: "can be wrapped as a tool feeding an indexer"
  memory_state: "none"
  human_in_the_loop: "CLI operator"
  guardrails: "deterministic output (no model hallucination)"

data_scenario:
  data_source_types: ["Visio diagrams (.vsdx, .vsd)"]
  connectors: ["local filesystem"]
  retrieval_patterns: "n/a (produces text for downstream retrieval)"
  transformation_pipelines: ["Visio OPC/XML parse -> flow graph -> text outline"]

ai_stack:
  llm_provider: "none (deterministic)"
  search_integration: "none (output feeds any index)"
  agent_framework: "none"
  observability: "n/a"
  languages: ["Python (standard library only)"]

hosting:
  compute_platform: "local execution"
  scaling_model: "n/a"
  regional_availability: "n/a"

api_integration:
  internal_apis: "none"
  external_saas_apis: "none"
  mcp_support: false
  auth: ["none"]

ui_scenario:
  channels: ["CLI"]
  ui_framework: "n/a"
  ux_patterns: ["command-line"]

infrastructure:
  iac: "none"
  cicd: "none"
  monitoring: "none"
  dependencies: ["Python 3.10+", "optional LibreOffice for .vsd"]

stack_summary: ["Python", "CLI", "deterministic parser"]
```
