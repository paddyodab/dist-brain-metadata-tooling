# dist-brain-metadata-tooling

Reusable tooling for the **distributed-brain** pattern: author metadata *with* the
code, **gate** it so it can't go stale, and **materialize** it into a GitHub wiki
on every merge. Drop it into any repo with a `src/` + `flags.yml` and a wiki.

It's the engine extracted from [code-samples-with-ai-metadata](https://github.com/pdabney/code-samples-with-ai-metadata)
and [my-app-with-a-wiki-01](https://github.com/pdabney/my-app-with-a-wiki-01), so a
product repo carries config + a thin workflow instead of copy-pasting the engine.

## What's here

- **`action.yml`** — a composite action (`mode: gate | materialize`).
- **`engine/`** — the scripts (`check_metadata.py`, `extract.py`, `materialize.py`,
  `flags_registry.py`, `publish_wiki.sh`). They analyze a target repo via `--root`
  (default `$GITHUB_WORKSPACE`), so the engine's location is decoupled from the
  repo it inspects.
- **`.github/workflows/gate.yml`, `wiki.yml`** — `workflow_call` reusable workflows.
- **`template/` + `init.sh`** — the authoring kit (`/feature`, CONTRIBUTING, PR template).

## Use it in a consumer repo

**1. Install the authoring kit:**

```bash
git clone https://github.com/paddyodab/dist-brain-metadata-tooling
dist-brain-metadata-tooling/init.sh ../your-repo
```

**2. Add two workflows** to `your-repo/.github/workflows/`:

```yaml
# ci.yml — gate every PR
on: [pull_request, push]
jobs:
  gate:
    uses: paddyodab/dist-brain-metadata-tooling/.github/workflows/gate.yml@v1
```

```yaml
# wiki.yml — materialize to the wiki on merge to main
on:
  push:
    branches: [main]
jobs:
  wiki:
    uses: paddyodab/dist-brain-metadata-tooling/.github/workflows/wiki.yml@v1
    secrets:
      wiki-token: ${{ secrets.WIKI_TOKEN }}
```

That's the whole adoption: the engine is never copied into the product repo.

**Inputs** (both workflows): `src` (default `src`), `flags` (default `flags.yml`).

## Prerequisites (consumer repo)

1. A `flags.yml` registry and public functions carrying contracts (see the kit).
2. **Initialize the wiki** — create one page in the GitHub UI (so `.wiki.git` exists).
3. Add a **`WIKI_TOKEN`** secret — a *classic* PAT with `repo` scope (the default
   `GITHUB_TOKEN` can't push to wikis; fine-grained tokens can't either).

## Run the engine locally

```bash
python3 engine/check_metadata.py --root ../your-repo      # gate
python3 engine/materialize.py    --root ../your-repo --brain /tmp/brain   # render
```

## Roadmap

- **Agent projection** — alongside the human wiki, emit an agent read model: a
  token-dense context bundle (`llms.txt`-style) + a queryable surface over
  `graph.json` (`search`/`get_entity`/`neighbors`), eventually an MCP server. The
  graph is already produced; this shapes it for the *retrieve* access pattern.
- **`/feature` as a Claude Code plugin** (vs. copy-in).
- **Learnings** routing (promote how-tos to code/tests, rationale to ADRs).
