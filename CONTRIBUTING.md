# Contributing

## Code contributions: not yet, and here is the honest reason

**We are not accepting pull requests at the moment.** If you send one it will be read with
genuine interest and then closed with thanks, which is a waste of your time — so we would
rather say so on the way in than on the way out.

The reason is ownership, not quality. Apache-2.0 §5 means a contribution arrives licensed to us
under Apache-2.0, but it does **not** transfer copyright. Every accepted patch therefore adds a
rights holder. That is completely fine for a project that will only ever be Apache-2.0, and it
quietly removes options for a project that might later need to grant someone different terms —
the additional-licence mechanism described in [`LICENSING.md`](./LICENSING.md) works precisely
*because* one party holds all the rights.

We have not decided how we want to handle that. The two honest routes are a DCO (you keep your
copyright, we lose relicensing flexibility) or a CLA (you grant us a broad licence, which is
more paperwork for you and which some people reasonably decline). Choosing badly and quietly
would be worse than waiting. Accepting patches *before* choosing would be worst of all, because
it would make the decision for us and we would have made it with your code.

So: the door is closed for now, on purpose, and it is not closed because of you.

## What is genuinely wanted right now

All of these are more useful to us than a patch, and none of them create an ownership problem.

**Bug reports.** Especially anything where the engine reported success and the audio was wrong.
That is the failure this project exists to eliminate, and a real instance of it is worth a great
deal to us. Please include the chain or component, the input's format and duration, what you
expected, and what you measured.

**Holes in the verification model.** If you can describe an audio defect that our `verify:`
vocabulary cannot express, that is the most valuable thing you can send. We already know about
one: there is no assertion for "this output is audible" — a render can be structurally perfect,
correctly long, and sit at −64 dBFS, and every current check passes it. Tell us about the
others.

**Format feedback.** The chain and `step.yaml` format is meant to be implemented by other
people (see [`LICENSING.md`](./LICENSING.md)). If something in it is ambiguous, awkward, or
impossible to implement faithfully, we want to hear it while the format is still young enough to
change.

**Your own components, in your own repository.** The filesystem is the registry, so a component
is just a folder — you do not need our permission or our repo to write one. Tell us it exists
and we will link it.

**Telling us the documentation is wrong.** If a README and its `step.yaml` disagree, that is a
defect of unknown side: one of them encodes an intention and the other encodes what shipped.
Reporting it is more useful than guessing which is which.

## If you have already written a patch

Open an issue describing it rather than a PR. If it is a fix we should make, we will make it and
credit you in the commit message by name and by link. That gets the fix shipped without either
of us signing anything, which is the best available outcome until the terms above are settled.

## Ground rules for issues

- Search open **and** closed issues first.
- One issue per issue.
- Include versions: OS, `node --version`, `python3 --version`, `ffmpeg -version`.
- For audio problems, measurements beat adjectives. "Peak −64 dBFS" is actionable; "sounds
  broken" needs a round trip.
- Never paste a value you did not measure. A fabricated number in a bug report about
  verification is a special kind of unhelpful.
