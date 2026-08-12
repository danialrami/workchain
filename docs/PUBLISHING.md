# Publishing @lufs/workchain to npm

This document describes how to publish the `@lufs/workchain` package from the **repo root**.

---

## Prerequisites

1. The repo must be **public** on GitHub before publishing. The npm package page links to
   `https://github.com/lufs-audio/workchain`; publishing from a private repo is possible
   but the README and repository links will 404 for consumers.

2. You must belong to (or create) the `lufs` npm organisation:

   ```sh
   npm org create lufs          # one-time, if the org does not yet exist
   npm team add lufs:developers <your-npm-username>
   ```

3. Authenticate with npm:

   ```sh
   npm login                    # opens browser for OAuth; or use npm login --auth-type=legacy
   npm whoami                   # verify you are logged in
   ```

---

## Inspect before you ship

From the repo root, generate and inspect the tarball without publishing:

```sh
npm pack --dry-run             # prints the full file list and sizes
npm pack                       # writes lufs-workchain-0.1.0.tgz
tar -tzf lufs-workchain-0.1.0.tgz | head -40
```

Confirm the list includes:
- `package/engine/workchain-engine.sh`
- `package/lib/common-utils.sh` and `package/lib/workchain_yaml.py`
- `package/components/normalization/run.sh`
- `package/chains/deliverable-voice.yaml`
- `package/cli/bin/workchain.js`

And does NOT include `node_modules/`, `__pycache__/`, `docs/`, `ci/`, `tools/`, `mcp-server/`,
or any `.venv/` directory.

Clean up afterwards: `rm lufs-workchain-0.1.0.tgz`

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
npm install @lufs/workchain          # or: npm install -g @lufs/workchain
node node_modules/@lufs/workchain/cli/bin/workchain.js components --json
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

## Deprecate or unpublish

If you need to pull a bad release within 72 hours of publishing:

```sh
npm unpublish @lufs/workchain@0.1.0 --force
```

After 72 hours, unpublish is blocked by npm policy. Use deprecation instead:

```sh
npm deprecate @lufs/workchain@0.1.0 "This release has a critical bug; use 0.1.1"
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
