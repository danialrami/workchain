# `.agents/`

Agent-facing instructions that travel with the repository.

Workchain is built to be operated by agents, so the conventions an agent needs should live in
the repo rather than in someone's private configuration. Anything here is readable by any agent
that clones this repo, and is versioned alongside the code it describes — which means it can go
stale, and should be corrected like code when it does.

## Layout

```
.agents/
├── README.md
└── skills/
    ├── authoring-a-component/SKILL.md    # write a component that is verified, not just runnable
    └── submitting-an-issue/SKILL.md      # report a bug in someone else's project, to our standard
```

Each skill is a directory with a `SKILL.md` carrying YAML frontmatter (`name`, `description`).
The `description` is what an agent matches on when deciding whether a skill applies, so it
should name the *situations* that should trigger it, not just the topic.

Room is deliberately left for more: a skill directory may also carry `scripts/` and
`references/` subdirectories, and this folder can grow sibling directories for slash-commands or
agent definitions (e.g. a reviewer that checks a `verify:` block against what `run.sh` actually
writes) as the need appears. Add them when a real workflow repeats, not speculatively.

## The two rules that matter

**These describe how we work, not merely how the code works.** `authoring-a-component` encodes
the prime directive — proven correct, not merely exited 0 — as a procedure. If a skill and the
code disagree, that is a defect of unknown side: one encodes an intention and the other encodes
what shipped. Report it rather than silently editing either to match.

**Never invent a measurement.** Several documents here quote real measured values. They are
provenance claims about actual audio. Do not alter, round, extrapolate, or add to them.

## See also

- `AGENTS.md` at the repo root — the contract model and repo-wide conventions
- `llms.txt` and `agent.json` — machine-readable discovery for the tool surface
- `docs/format.md` — the chain and `step.yaml` specification
