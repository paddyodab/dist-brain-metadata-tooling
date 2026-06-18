# Setup runbook — wiring a repo to publish its brain to the wiki

Step-by-step to take a repo from "has `src/` + `flags.yml`" to "its wiki
auto-updates on every merge, with an agent-queryable MCP server." Includes the
manual GitHub steps (wiki init, PAT) that can't be automated.

---

## 0. Prerequisites

- The consumer repo has a `src/` directory of Python with colocated contracts
  (`@intent` / `@param` / `@returns` / `@raises`, plus `@feature`/`@flag`) and a
  `flags.yml` registry. (Use `init.sh` to drop in the `/feature` authoring kit.)
- **The repo is public, or on a GitHub plan that includes wikis.** Wikis on
  private repos require a paid plan.

## 1. Install the authoring kit

```bash
git clone https://github.com/paddyodab/dist-brain-metadata-tooling
dist-brain-metadata-tooling/init.sh ../your-repo
```

Adds `.claude/commands/feature.md`, `CONTRIBUTING.md`, `.github/pull_request_template.md`.

## 2. Add the two CI workflows

In `your-repo/.github/workflows/`:

```yaml
# ci.yml
on: [pull_request, push]
jobs:
  gate:
    uses: paddyodab/dist-brain-metadata-tooling/.github/workflows/gate.yml@v1
```

```yaml
# wiki.yml
on:
  push:
    branches: [main]
jobs:
  wiki:
    uses: paddyodab/dist-brain-metadata-tooling/.github/workflows/wiki.yml@v1
    secrets:
      wiki-token: ${{ secrets.WIKI_TOKEN }}
```

Commit and push. The gate runs immediately; the wiki job will run but **skip
publishing** until step 4 is done — that's expected.

## 3. Initialize the wiki  ⟵ manual, one-time

The wiki is a separate git repo (`<repo>.wiki.git`) that **doesn't exist until
you create the first page**:

1. Go to your repo on GitHub → **Wiki** tab.
2. Click **Create the first page**.
3. Type anything (the materializer overwrites `Home`) → **Save Page**.

Verify it exists:

```bash
git ls-remote https://github.com/<owner>/<repo>.wiki.git >/dev/null && echo "wiki ready"
```

## 4. Create a token and add the secret  ⟵ manual, one-time

The default `GITHUB_TOKEN` **cannot push to wikis**, so you must supply a PAT.

1. **Create a classic PAT** — GitHub → **Settings → Developer settings →
   Personal access tokens → Tokens (classic) → Generate new token (classic)** →
   check the **`repo`** scope → generate → copy.
   - ⚠️ **It must be a *classic* token.** Fine-grained PATs cannot push to wikis
     either — this is a known GitHub limitation.
2. **Add it as the `WIKI_TOKEN` secret:**
   ```bash
   gh secret set WIKI_TOKEN --repo <owner>/<repo>
   ```
   (paste the token at the prompt) — or via **Settings → Secrets and variables →
   Actions → New repository secret**, name `WIKI_TOKEN`.

## 5. Trigger and verify

Re-run the last wiki workflow (now that the secret exists) or push any commit:

```bash
gh run rerun --repo <owner>/<repo> \
  $(gh run list --repo <owner>/<repo> --workflow wiki --limit 1 --json databaseId --jq '.[0].databaseId')
```

Then check the wiki — `Home`, one page per module, `Features`, `Decisions`,
`Changelog`, `agent-context`, and `Runbook-<feature>` pages should appear:
`https://github.com/<owner>/<repo>/wiki`

From here, every merge to `main` updates the wiki automatically.

## 6. (Optional) Connect the agent MCP server

Give agents the *depth* surface over the brain (`search` / `get_entity` /
`neighbors` / `list_decisions` / `overview`):

```bash
pip install -r dist-brain-metadata-tooling/mcp/requirements.txt
```

Point it at the wiki's raw `graph.json` and register it with Claude Code (project
scope writes `.mcp.json`):

```bash
claude mcp add dist-brain -s project \
  -e DIST_BRAIN_GRAPH=https://raw.githubusercontent.com/wiki/<owner>/<repo>/graph.json \
  -- python3 /abs/path/to/dist-brain-metadata-tooling/mcp/server.py
```

See the README's "Agent projection" section for the equivalent `.mcp.json`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Wiki job logs `WIKI_TOKEN secret not set — skipping` | Step 4 not done — add the `WIKI_TOKEN` secret. |
| `could not clone <repo>.wiki.git` | Step 3 not done — initialize the wiki by creating one page in the UI. |
| Push to wiki fails with `403` | The token is **fine-grained**; wikis need a **classic** PAT with `repo` scope. |
| Gate fails in CI | A contract is stale — read the `✗` lines; fix the code or the metadata. |
| MCP `overview` returns empty | `DIST_BRAIN_GRAPH` points at a wiki that hasn't materialized yet, or a wrong URL. |
