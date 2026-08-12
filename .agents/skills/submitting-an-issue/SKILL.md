---
name: submitting-an-issue
description: How to file a bug report on someone else's open-source project, to LUFS standard. Use whenever preparing to report a defect in a third-party library, tool, or dependency — especially a first contact with a maintainer we do not know. Covers the research that must happen before filing, the structure of a report that gets fixed, and the etiquette that determines whether we are read as a colleague or a drive-by.
---

# Submitting an issue

We find bugs in other people's code as a side effect of what we do: we verify audio, so we
notice when something reports success and produces the wrong output. How we report that is a
reputational act. A first issue is often the first thing a maintainer ever learns about us.

**The governing idea: a bug report is a transfer of cost.** Every element below moves work off
the maintainer and onto us. That is the whole craft. A report that makes someone else do the
reproducing, the bisecting, and the guessing is a bill; a report that hands them a diagnosis is
a gift. Maintainer attention is the scarce resource in open source, not code.

## 1. Before writing anything

**Search open AND closed issues.** The most-skipped step and the most damaging to skip — a
duplicate says "I did not do my homework" before your first sentence. Check closed ones too: it
may be fixed on main and unreleased, which changes the report entirely.

**Read the project's existing issues to learn its register.** This is the highest-leverage
research step and almost nobody does it. Projects differ enormously in what they want. Some
want a symptom and nothing more; some want root cause, a patch, and a test.

> Worked example: `cdp-wasm` has two issues, both filed by the maintainer himself, each
> structured as Version + commit SHA → Summary → Minimal reproduction → Actual → Expected →
> **Root cause with line permalinks** → **Suggested fix** → **Regression test**. In that
> project, arriving with a root-cause analysis is *meeting the house standard*. The generic
> advice "report, don't prescribe" would have produced a thinner report than the maintainer
> writes for himself.

So: **do not apply a default register. Derive it from the project.** If there is no issue
history, read recent merged PRs and the commit messages.

**Read `CONTRIBUTING.md` and check for `.github/ISSUE_TEMPLATE/`.** If a template exists, use
it exactly — its fields are the maintainer telling you what they need. Ignoring it is the
cheapest possible way to look careless.

**Reproduce on a released artifact.** Install the published package at a stated version. A bug
that only reproduces against your local checkout of a vendored copy is not yet a report.

**Try to disconfirm your own finding.** Before you claim a defect, look for the reading in
which the maintainer is right. Is the input actually legal? Is the behaviour documented
somewhere you have not read? Is your test signal appropriate? Then go further and establish the
blast radius — if the bug only fires outside the documented envelope, that changes what you are
reporting and how.

> This is the single most credible thing you can put in a report. "I drove all 156 effects at
> their own declared defaults and got zero silent failures" tells a maintainer you tried to
> prove yourself wrong. Nothing else buys that much trust in one sentence.

**Record your dead ends.** Hypotheses you investigated and discarded belong in our notes, and
sometimes in the report. Saying "I suspected the sample-rate threading and confirmed it is
handled correctly" shows the shape of the search.

## 2. The report

Adapt to the house style, but the full form is:

**Title** — a factual claim about behaviour, specific enough to search for. `stretch.time
factor 0.02 returns a zero-length file with exit 0`, not `Bug in stretch` and not `stretch is
broken`.

**Version and environment** — published version, commit SHA if you have it, OS, runtime
versions, and where it reproduces (Node API, CLI, browser).

**Summary** — two or three sentences. What you expected the contract to be, and what happens
instead. If the project documents an intention that this behaviour violates, quote it.

**Minimal reproduction** — the smallest runnable thing. No project scaffolding, no
`node_modules` assumptions beyond the package, no audio files the maintainer does not have
(synthesise the input in the snippet). Someone should be able to paste and run it.

**Actual result / Expected result** — separately, with measured values. Bytes, frames,
durations, dBFS. Never adjectives where a number exists.

**Root cause** — if you found it, name it with permalinks to specific line ranges (on GitHub:
open the file, click the line numbers, press `y` to freeze the permalink to a commit SHA).
Explain the mechanism, not just the location. If you did *not* find it, say so plainly rather
than speculating in a way that sounds like a diagnosis.

**Suggested fix** — only where the project's own register invites it, and always as a proposal.
"Would X be the right fix, or does that break something I cannot see?" leaves the maintainer
their judgment. They know constraints you do not.

**Regression test** — what to assert so it cannot come back. Cheap for us, and it is the part
maintainers most often have to write themselves.

**Offer, do not dump** — "Happy to open a PR if that would help." Then wait for an answer.
Attaching an unrequested PR to a first contact reads as presumption, and creates review work
nobody asked for.

## 3. Etiquette

- **One issue per issue.** Never bundle findings. Two defects in one thread means one of them
  gets lost and the other gets a confused discussion. If you found three things, file the
  strongest one and hold the rest until it lands.
- **Never imply carelessness.** Where a behaviour is a deliberate design choice, quote the
  choice and frame the finding as a case its premise does not cover. Understanding *why* the
  code is the way it is, and saying so, is the difference between a colleague and a drive-by.
- **Assume competence and good faith.** If something looks obviously wrong in a mature
  project, the likeliest explanation is a constraint you have not found yet.
- **No entitlement.** No deadlines, no bumping, no "any update on this?" within a week, no
  implication that a free thing owes you a fix. Bug-bounty energy poisons a first contact.
- **Lead with one specific line of credit, then stop.** Something that proves you read the
  code. Paragraphs of praise read as nervous or as softening a blow.
- **Do not sell.** If our own work is relevant to how we found the bug, one neutral clause is
  the ceiling. An issue is about their code. Pitching in an issue thread is the fastest way to
  be remembered badly — take that to a DM or an email where it belongs.
- **Close the loop.** If they fix it, say thank you on the thread and confirm the fix works
  against the release. That is where a working relationship actually starts.
- **Match their pace and stop when they stop.** Some maintainers close issues terse and fast.
  That is not rudeness.

## 4. Before you hit submit

- [ ] Searched open and closed issues
- [ ] Used the template if one exists
- [ ] Read existing issues and matched the project's register
- [ ] Reproduces on a published release, version stated
- [ ] Repro snippet is self-contained and was actually run, exactly as pasted
- [ ] Every number in the report was measured, not remembered or estimated
- [ ] Tried to disconfirm it; blast radius established
- [ ] One defect only
- [ ] Nothing in it implies carelessness
- [ ] No pitch
- [ ] Read once more as the maintainer, on a bad day

## 5. Never

**Never paste a number you did not measure.** In a report about correctness, an invented figure
is disqualifying — it destroys the only thing that makes the report worth reading, and it is not
recoverable. If you did not measure it, either measure it or leave it out.

**Never file on behalf of Daniel without his review.** These go out under his name and land on
his professional reputation. Draft it, show him, let him send it.

## Related

- The mirror image — what we want from people reporting to *us*, and why we currently decline
  PRs on ownership grounds: `CONTRIBUTING.md` at the repo root.
- Deep-dive KB suites: `docs/strategy/open-source-contribution/` and
  `docs/strategy/open-source-licensing/` in the agent knowledge base.
