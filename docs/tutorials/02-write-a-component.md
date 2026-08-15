---
title: "Write your own verified component"
description: "Scaffold a component, watch it fail until implemented, add a real verify contract, then break the output on purpose and watch the verifier catch it."
type: tutorial
---

# Write your own verified component

A component is a folder: `step.yaml` (the contract) + `run.sh` (the work) + `README.md`. The
filesystem under `components/` *is* the registry — there is no database.

The definition of done here is not "it runs". It is **"it proves what it produced."** This
tutorial walks you through building a tiny component — `tutorial_gain`, which applies a fixed
gain in dB — and watching the verify contract do its job three times: fail-closed while
unimplemented, pass when honest, and catch you when you break it.

**Time:** about 10 minutes.
**Requires:** the CLI from [tutorial 01](01-first-chain.md), plus a `tone.wav` (any audio
file works; reuse the one you made there).

---

## 1. Scaffold the component

```bash
cd workchain
workchain generate component \
  --name tutorial_gain \
  --description "Apply a fixed gain to an audio file (tutorial example)" \
  --commands ffmpeg \
  --type audio
```

You get a full directory, not a stub:

```
Component 'tutorial_gain' created successfully!
Path: /path/to/workchain/components/tutorial_gain
Files created:
  - components/tutorial_gain/step.yaml
  - components/tutorial_gain/run.sh
  - components/tutorial_gain/provision.sh
  - components/tutorial_gain/README.md
  - components/tutorial_gain/test-chain.yaml
```

`--commands ffmpeg` pre-declares the inbound requirement. The scaffold's `run.sh` is complete
except for the actual processing.

---

## 2. Watch it fail first

Before you implement anything, run what you just generated:

```bash
workchain run-component tutorial_gain tone.wav -o ./out_scaffold --json
```

It fails on purpose:

```json
{
  "status": "failed",
  "exit_code": 1,
  "steps": {
    "tutorial_gain": {
      "status": "not_implemented",
      "outputs": {
        "primary_output": {
          "path": "…/out_scaffold/tone_tutorial_gain.wav",
          "exists": false,
          "note": "scaffold_not_implemented"
        }
      }
    }
  },
  "verification": null
}
```

and on stderr the reason:

```
[ERROR] tutorial_gain is an unimplemented scaffold.
[ERROR] Add processing in components/tutorial_gain/run.sh, then remove the 'WORKCHAIN_NOT_IMPLEMENTED=1' line.
```

The sentinel is a real line in `run.sh`, not a comment:

```bash
WORKCHAIN_NOT_IMPLEMENTED=1
```

The `run.sh` checks this variable: if set, it registers the output as `not_implemented` and
returns 1. That is the point — **a generated component can never be mistaken for a working one
by whoever runs it, human or agent.** No implementation, no false success. The verifier is not
even reached; the step never gets that far.

---

## 3. Declare the parameter

Open `components/tutorial_gain/step.yaml`. The scaffold leaves `params_schema` commented.
Uncomment and fill in one parameter:

```yaml
params_schema:
  gain_db:
    type: number
    default: 0
    description: "Gain to apply in dB (positive = louder, negative = quieter)"
    range: { min: -60, max: 60 }
```

A param definition supports exactly four keys: `type`, `default`, `description`, `range`.
**There is no `required` key** — add one and every parser layer silently discards it. A
parameter is made mandatory by convention: omit `default` and guard it in `run.sh`. We give
`gain_db` a default (0 dB = pass-through), so no guard is needed here.

Note the `range` on one line — the shared parser does not support flow collections that span
lines. See [../format.md](../format.md) for the parser gotchas.

---

## 4. Implement `run.sh`

Open `components/tutorial_gain/run.sh`. Two edits:

**4a.** After the `get_param()` helper (which the scaffold already defines), read the
parameter:

```bash
GAIN_DB=$(get_param "gain_db" "0")

log_info "$COMPONENT_NAME parameters:"
log_info "  gain_db: ${GAIN_DB} dB"
```

`get_param` reads the engine-resolved config. The engine has already applied precedence
(step `params` > chain `globals` > schema `default`); the component must never re-resolve it.

**4b.** Replace the `IMPLEMENT ME` block — the `WORKCHAIN_NOT_IMPLEMENTED=1` line and the
`if [[ "${WORKCHAIN_NOT_IMPLEMENTED:-0}" == "1" ]]` guard, through the closing `fi` — with the
actual work:

```bash
# Apply the gain with ffmpeg's volume filter. The filter takes a dB value like 6dB or -12dB.
if ffmpeg -nostdin -y -i "$INPUT_FILE" -af "volume=${GAIN_DB}dB" "$OUTPUT_FILE" >> "$LOG_FILE" 2>&1; then
    log_info "Applied ${GAIN_DB} dB gain -> $OUTPUT_FILE"
else
    log_error "ffmpeg failed. Check log: $LOG_FILE"
    register_output "$CONTEXT_FILE" "$COMPONENT_NAME" "primary_output" "$OUTPUT_FILE" "file" \
        "{\"error\": \"ffmpeg_failed\"}" \
        "failed"
    return 1
fi
```

Keep the scaffold's tail exactly as generated — the "honest output check" that refuses to
report success when `$OUTPUT_FILE` is missing, and the final `register_output ... "completed"`
(the scaffold already fills the registered JSON with `{}`; you can replace it with
`"{\"gain_db\": ${GAIN_DB}}"` so the recorded output metadata carries what you asked for).

The `return` (never `exit` — the engine sources `run.sh`), the `log_*` helpers writing to
stderr, `register_output`, and `get_param` are all defined in the scaffold's preamble via
`lib/common-utils.sh`. stdout stays clean; the engine emits the final JSON itself.

---

## 5. Declare a real `verify:` block

Now the outbound contract — what the component *guarantees* after it exits. The scaffold's
`verify:` already asserts `[exists, non_empty, audio_valid]` on `primary_output`. That is a
valid structural contract, but a contract that proves only "a decodable file exists" is
leaving most of the story untold. Add a post-condition, a metamorphic invariant:

```yaml
verify:
  schema_version: "1.0"
  outputs:
    - name: primary_output
      assert: [exists, non_empty, audio_valid]
  post_conditions:
    - id: duration_preserved
      check: audio_duration_matches
      outputs: [primary_output]
      tolerance_s: 0.1
      description: "Gain changes the amplitude, never the length: the output must last as long as the input within 0.1 s. A truncated or padded file fails this."
```

Why this check and not, say, a loudness assert? A gain component's output loudness depends on
the *input's* loudness, which varies — there is no single correct absolute target, so we assert
the relation that *must* hold regardless: duration is preserved. This is the metamorphic
pattern for operations with no right answer (separation, denoise, restoration all use variants
of it).

**Never ship an empty `verify:` block.** An empty contract proves nothing and manufactures
confidence. If you cannot yet assert anything numeric, keep the structural asserts and say in
the README, out loud, what the contract does *not* cover. Ours still does not prove the gain
was actually applied — no registered check re-measures input vs output loudness — and this
README-sized gap is honest to acknowledge: the contract proves audibility, duration, and that
the file is a real sound. That is a deliberate, documented choice for a tutorial component, not
a silent one.

---

## 6. Watch verify pass

```bash
workchain run-component tutorial_gain tone.wav -o ./out --params-json '{"gain_db":6}' --json
```

```json
{
  "status": "completed",
  "verification": {
    "component": "tutorial_gain",
    "tier": "verified",
    "verified": true,
    "checks": [
      { "name": "primary_output.exists",         "ok": true, "detail": "path=…/out/tone_tutorial_gain.wav" },
      { "name": "primary_output.non_empty",      "ok": true, "detail": "441078 bytes" },
      { "name": "primary_output.audio_valid",    "ok": true, "detail": "audio_stream=True duration=5.000s" },
      { "name": "duration_preserved",            "ok": true, "detail": "source=5.000s; outputs within ±0.10s → ok" }
    ],
    "failures": []
  }
}
```

stderr confirms: `✓ tutorial_gain — verified (4/4 checks passed)`. The step is recorded
`completed`, tier `verified`.

---

## 7. Break it on purpose

A check nobody has seen fail is decoration. Break it now.

In `run.sh`, replace the ffmpeg line with a "writer bug" — a file that has bytes but no sound:

```bash
# DELIBERATE BREAK: write a 44-byte header with zero samples
if head -c 44 /dev/zero > "$OUTPUT_FILE"; then
    log_info "DELIBERATE BREAK: wrote a 44-byte header with zero samples -> $OUTPUT_FILE"
```

Run again:

```bash
workchain run-component tutorial_gain tone.wav -o ./out_broken --json
```

```json
{
  "status": "failed",
  "verification": {
    "tier": "unverified",
    "verified": false,
    "checks": [
      { "name": "primary_output.exists",      "ok": true,  "detail": "path=…/tone_tutorial_gain.wav" },
      { "name": "primary_output.non_empty",   "ok": true,  "detail": "44 bytes" },
      { "name": "primary_output.audio_valid", "ok": false, "detail": "audio_stream=False duration=0.000s" },
      { "name": "duration_preserved",         "ok": false, "detail": "source=5.000s; outputs within ±0.10s → MISMATCH primary_output=0.000s" }
    ]
  }
}
```

Exit code 1, step `failed`, tier `unverified`.

Read that check list carefully — it is the lesson on a platter:

- `exists` **passed** — the file is there.
- `non_empty` **passed** — *"a 44-byte WAV header with zero samples has bytes."* This is why
  `non_empty` alone would have let the lie through.
- `audio_valid` **failed** — it re-probed with ffprobe and found no audio stream, no duration.
- `duration_preserved` **failed** — the metamorphic invariant: 0.000 s ≠ 5.000 s.

Structural asserts and a metamorphic relation caught the same bug from two directions. That is
the difference between "wrote a file" and "produced sound". Restore the ffmpeg line when
you're done.

---

## 8. Clean up (optional)

The component lives only in your clone, and `components/index.json` is *generated* — adding a
component makes it stale until you regenerate:

```bash
rm -rf components/tutorial_gain
workchain registry generate      # re-syncs components/index.json
workchain registry check         # exits 1 if the index is stale (CI gate)
```

If you keep the component, `registry generate` is the honest way to re-index. Never hand-edit
`components/index.json` or hand-write a definition hash.

---

## What you just proved

- The scaffold fails until implemented — the sentinel is a real line, so a fresh component can
  never lie about being ready.
- A real contract is structural asserts **plus** at least one relation or numeric
  post-condition — never an empty `verify:`.
- The verifier re-measures; it does not trust the component's own claims.
- The `non_empty` → `audio_valid` gap is exactly where silent-failure bugs live.

## Related

- [Your first verified chain](01-first-chain.md) — the same doctrine from the operator's side.
- [Drive Workchain as an agent](03-drive-workchain-as-an-agent.md) — how an agent discovers and
  runs components (including `create_component`, the MCP twin of `generate component`).
- [../../.agents/skills/authoring-a-component/SKILL.md](../../.agents/skills/authoring-a-component/SKILL.md)
  — the authoring doctrine this tutorial is a condensed walk-through of.
- [../../components/normalization/step.yaml](../../components/normalization/step.yaml) — the
  reference contract, including the post-condition that closes a "measured but never compared"
  bug.
- [../format.md](../format.md) — the step.yaml specification: `params_schema`, `outputs`,
  `requirements`, `verify`.