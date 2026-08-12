# Publishing @lufs-audio/workchain to npm

This document describes how to publish the `@lufs-audio/workchain` package from the **repo root**.

---

## Prerequisites

1. The repo must be **public** on GitHub before publishing. The npm package page links to
   `https://github.com/lufs-audio/workchain`; publishing from a private repo is possible
   but the README and repository links will 404 for consumers.

2. The publishing scope is **`@lufs-audio`**, at parity with the GitHub organisation. The org
   exists; nothing to do here.

   `@lufs` was the original intent and is **already registered by someone else**, which is why
   the package is `@lufs-audio/workchain`. Parity with the GitHub org is the better answer
   anyway: the trusted-publisher configuration below keys on the GitHub organisation name, so
   having the two match removes a class of mismatch.

   **How to check whether a scope is free — and how not to.** Requesting package names under
   a scope proves nothing. An org can be registered with **zero** published packages, in which
   case every package name under it returns 404 and a registry search for the scope returns
   `total: 0`. Both were true of `@lufs` at the moment it was already taken. The only reliable
   check is attempting to create the org:

   <https://www.npmjs.com/org/create>

   **There is also no `npm org create`.** The CLI's `npm org` supports only `set`, `rm` and
   `ls`; organisations are created in the browser. If you ever add members:

   ```sh
   npm team create lufs-audio:developers      # the team must exist before anyone is added
   npm team add lufs-audio:developers <npm-username>
   ```

   A one-person org needs neither command — being the org owner is enough to publish.

3. Authenticate with npm:

   ```sh
   npm login                    # opens browser for OAuth; or use npm login --auth-type=legacy
   npm whoami                   # verify you are logged in
   ```

4. **If your account has 2FA set to "authorization and writes"**, the publish needs a
   one-time code. Interactively `npm publish` prompts for it; in a non-interactive shell it
   fails with `EOTP`, which reads like an auth failure rather than a missing code:

   ```sh
   npm publish --access public --otp=123456
   ```

   Leaving 2FA on writes is the right setting. Just have the authenticator open.

---

## Inspect before you ship

From the repo root, generate and inspect the tarball without publishing:

```sh
npm pack --dry-run             # prints the full file list and sizes
npm pack                       # writes lufs-audio-workchain-0.1.0.tgz
tar -tzf lufs-audio-workchain-0.1.0.tgz | head -40
```

Confirm the list includes:
- `package/engine/workchain-engine.sh`
- `package/lib/common-utils.sh` and `package/lib/workchain_yaml.py`
- `package/components/normalization/run.sh`
- `package/chains/deliverable-voice.yaml`
- `package/cli/bin/workchain.js`

And does NOT include `node_modules/`, `__pycache__/`, `docs/`, `ci/`, `tools/`, `mcp-server/`,
or any `.venv/` directory.

Clean up afterwards: `rm lufs-audio-workchain-0.1.0.tgz`

---

## Publish

Scoped npm packages default to **restricted** access. Always pass `--access public`:

```sh
npm publish --access public
```

If the `publishConfig.access` field in `package.json` is already `"public"` (it is), the
flag is redundant but harmless and documents intent.

---

## Verify the published package

Install into a clean, temporary directory to confirm the global install path works:

```sh
mkdir /tmp/wc-smoke && cd /tmp/wc-smoke
npm install @lufs-audio/workchain          # or: npm install -g @lufs-audio/workchain
node node_modules/@lufs-audio/workchain/cli/bin/workchain.js components --json
```

You should see a JSON array of available components. A `workchain config set workchainRoot`
step is NOT required when the package is published from root — the binary's directory walk
finds `engine/workchain-engine.sh` relative to its own location inside `node_modules/`.

---

## Tag the release

After a successful publish:

```sh
git tag v0.1.0
git push origin v0.1.0
```

---

## After 0.1.0: publish from CI with provenance

**This cannot be used for the first release, and that is not a configuration mistake.** A
trusted publisher is configured in the *package's* settings on npmjs.com, and the package has
to exist before those settings exist. So `0.1.0` goes out by hand as described above, and
everything after it can go out over OIDC with no token stored anywhere.

Worth doing for `0.1.1`, because it is the supply-chain equivalent of what this project
argues about audio: the registry stops taking our word for where the tarball came from and
instead verifies it cryptographically. npm attaches a **provenance attestation** linking the
published bytes to a specific commit and workflow run, and shows a verified badge on the
package page.

Once `0.1.0` is live:

1. On npmjs.com → package settings → **Trusted Publisher** → GitHub Actions. Fields are
   case-sensitive and exact: organisation `lufs-audio`, repository `workchain`, workflow
   filename `publish.yml` (**filename only**, not `.github/workflows/publish.yml`).
2. Add `.github/workflows/publish.yml` with `permissions: id-token: write` and **no**
   `NODE_AUTH_TOKEN` on the publish step — npm only falls back to OIDC when it finds no
   token, and an *empty* `NODE_AUTH_TOKEN` counts as a token.
3. Pin `node-version: '24'`. Trusted publishing needs **npm CLI ≥ 11.5.1**; Node 22 ships
   npm 10, which does not attempt the OIDC exchange at all and fails looking like a plain
   auth error. If the runner must stay on an older Node, add `npm install -g npm@latest`
   before the publish step.
4. Do **not** add `--provenance`. Trusted publishing generates provenance by default; the
   flag is redundant.

Constraints worth knowing before relying on it:

- **GitHub-hosted runners only.** Self-hosted is not supported, so this one workflow cannot
  move to the LUFS fleet — the same reason `ci/` is GitHub-hosted for this repo.
- **Public repository required** for provenance. Private source repos get trusted publishing
  but no attestation.
- **`repository.url` must match the publishing repo**, or the publish fails a signature check
  with a `422`. Ours already points at `git+https://github.com/lufs-audio/workchain.git`.

Do **not** set `publishConfig.provenance: true` in `package.json` before the manual first
publish. Provenance is only obtainable from a cloud CI runner, so declaring it would make a
publish from a laptop fail.

---

## Deprecate or unpublish

If you need to pull a bad release within 72 hours of publishing:

```sh
npm unpublish @lufs-audio/workchain@0.1.0 --force
```

After 72 hours, unpublish is blocked by npm policy. Use deprecation instead:

```sh
npm deprecate @lufs-audio/workchain@0.1.0 "This release has a critical bug; use 0.1.1"
```

Users will see the deprecation warning on install but the package remains accessible.

---

## Notes

- The `cli/package.json` is marked `"private": true` and exists only as a workspace manifest
  and as the version source read by `cli/bin/workchain.js` at runtime. Do not publish from
  inside `cli/`. The canonical publish path is always the repo root.
- The `components/*/.venv/` and `lib/__pycache__/` directories are excluded by the `files`
  glob patterns in the root `package.json` (not by `.npmignore`, due to an npm ≥ 10 behaviour
  where explicit `files` entries bypass `.npmignore` for subdirectories). The `.npmignore`
  file is still present for defence-in-depth.
