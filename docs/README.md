# Workchain Documentation

This is the documentation index for [LUFS Workchain](https://github.com/lufs-audio/workchain), a YAML-driven, agent-first audio processing engine where "it worked" means proven correct, not merely exited zero.

## Diátaxis map

| Type | Path | What it is |
|---|---|---|
| **Tutorials** | `docs/tutorials/` | Guided learning: first chain, write a component, drive as an agent |
| **How-to**: operate | `docs/how-to/operate/` | Install, run chains/components, inspect results, provision heavy, use shipped chains |
| **How-to**: author | `docs/how-to/author/` | Write chains, write components with verify contracts, publish your own |
| **Reference**: interfaces | `docs/reference/interfaces/` | CLI, MCP, and Bash engine command references |
| **Reference**: contracts | `docs/reference/contracts/` | Verify checks catalog, requirements classes, context.json |
| **Explanations** | `docs/explanation/` | Architecture, verification philosophy, agent-first design |
| **Case studies** | `docs/case-studies/` | Component war stories — shipped bugs, contract design, measured verification |
| **FAQ** | `docs/faq.md` | Frequently asked questions (operators, authors, agents) |
| **Troubleshooting** | `docs/troubleshooting.md` | Common failures: verification reads, preflight, YAML gotchas, provisioning |

## Reading paths

- **New user**: README.md → `docs/tutorials/01-first-chain.md` → `docs/tutorials/02-write-a-component.md`
- **Operator**: `docs/how-to/operate/install.md` → `docs/how-to/operate/run-chains.md` → `docs/how-to/operate/inspect-a-run.md` → `docs/reference/interfaces/cli.md`
- **Author**: `docs/format.md` → `docs/how-to/author/author-a-component.md` → `docs/how-to/author/write-a-verify-block.md` → `docs/reference/contracts/verify-checks.md`
- **Agent (AI)**: `llms.txt` → `agent.json` → `docs/explanation/agent-first.md` → `docs/tutorials/03-drive-workchain-as-an-agent.md` → `docs/reference/interfaces/mcp.md`
- **Component consumer**: `workchain components --json` → `docs/case-studies/*.md` → the component's own `README.md`

## Canonical source docs (not part of the Diátaxis tree)

| Path | Purpose |
|---|---|
| `README.md` | Project overview, architecture, quickstart |
| `AGENTS.md` | Contract model, build commands, and conventions for AI coding agents |
| `llms.txt` | Machine-readable docs index (for LLM/agent retrieval) |
| `docs/format.md` | Formal specification of chain YAML and step.yaml |
| `docs/PUBLISHING.md` | npm publishing procedure |

## Docs conventions (for contributors)

- **Frontmatter**: every page under `docs/` carries `title`, `description`, and `type` (one of: `tutorial`, `how-to`, `reference`, `explanation`, `case-study`, `faq`, `troubleshooting`).
- **Voice**: match the repo — terse, opinionated, honest about failure. Active voice, direct address, imperative steps, short sentences.
- **Agent-readiness**: every page opens naming the product+surface; headings are answer-shaped; code blocks are copy-paste units with real responses shown; failure modes are documented.
- **Measurements**: never invent. Every measured value in case studies is quoted verbatim from the component README it analyzes, with provenance noted.
- **Links**: relative paths within the repo. Every link must resolve at PR time. Link to canonical sources (README, AGENTS.md, format.md, component READMEs) rather than duplicating their content.
- **Tools**: documentation health is checked by `tools/doc-check.sh` (link resolution, llms.txt freshness, frontmatter completeness, license consistency). Run it before submitting a docs PR.