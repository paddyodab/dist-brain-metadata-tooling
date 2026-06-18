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
  `check_tags.py`, `flags_registry.py`, `publish_wiki.sh`). They analyze a target
  repo via `--root` (default `$GITHUB_WORKSPACE`), so the engine's location is
  decoupled from the repo it inspects.
- **`.github/workflows/gate.yml`, `wiki.yml`, `tags.yml`** — `workflow_call` reusable workflows.
- **`template/` + `init.sh`** — the authoring kit (`/feature`, `/learning`, CONTRIBUTING, PR template).
- **`examples/iac/`** — a CloudFormation + Terraform sample with a `tag-policy.yml`.
- **`mcp/`** — an MCP server exposing the brain as agent query tools.

**New here? See [`SETUP.md`](SETUP.md)** for the full step-by-step (incl. the manual wiki-init and PAT steps).

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

**3. (IaC) Enforce required tags** — if the repo has CloudFormation/Terraform, add a
`tag-policy.yml` (required tag keys) and:

```yaml
# tags.yml — fail the PR when a taggable resource is missing a required tag
on: [pull_request, push]
jobs:
  tags:
    uses: paddyodab/dist-brain-metadata-tooling/.github/workflows/tags.yml@v1
```

No-ops cleanly if there's no `tag-policy.yml`. See `examples/iac/`.

That's the whole adoption: the engine is never copied into the product repo.

**Inputs:** gate/wiki take `src` (default `src`), `flags` (default `flags.yml`); tags
takes `iac` (dir to scan, default whole repo) and `tag-policy` (default `tag-policy.yml`).

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

## Agent projection (MCP server)

The wiki is the *human* projection (browse). The **agent** projection is two parts:
the breadth surface is `agent-context.md` in the wiki (one token-dense read with
everything, incl. ADRs); the depth surface is the **MCP server** in `mcp/`, which
exposes the `graph.json` as query tools: `overview`, `search`, `get_entity`,
`neighbors`, `list_decisions`.

```bash
pip install -r mcp/requirements.txt
```

**Grok Build** (preferred) — project-scoped `.grok/config.toml` (installed by `init.sh`
when you pass `<owner>/<repo>`), or add manually:

```toml
[mcp_servers.dist-brain]
command = "/abs/path/to/dist-brain-metadata-tooling/.venv/bin/python3"
args = ["/abs/path/to/dist-brain-metadata-tooling/mcp/server.py"]
enabled = true

[mcp_servers.dist-brain.env]
DIST_BRAIN_GRAPH = "https://raw.githubusercontent.com/wiki/<owner>/<repo>/graph.json"
```

Or via CLI:

```bash
grok mcp add dist-brain \
  -e DIST_BRAIN_GRAPH=https://raw.githubusercontent.com/wiki/<owner>/<repo>/graph.json \
  --scope project \
  -- /abs/path/to/dist-brain-metadata-tooling/.venv/bin/python3 \
     /abs/path/to/dist-brain-metadata-tooling/mcp/server.py
```

**Claude Code** (legacy):

```bash
claude mcp add dist-brain -s project \
  -e DIST_BRAIN_GRAPH=https://raw.githubusercontent.com/wiki/<owner>/<repo>/graph.json \
  -- python3 /abs/path/to/mcp/server.py
```

`DIST_BRAIN_GRAPH` also accepts a local path (e.g. `brain/graph.json`). The server
reloads per call, so it always reflects the latest published graph.

## Authoring kit (`/feature`, `/infra`, `/learning`, `/freshness-review`)

`init.sh` installs **Grok skills** (preferred) and Claude commands (legacy):

| Skill | What it does |
|---|---|
| **`/feature`** | Contract-first capture: plan → metadata contracts → implement to them |
| **`/infra`** | Contract-first IaC: ask for required tags + intent before writing resources |
| **`/learning`** | Route a learning by half-life: how-to → code, claim → test, decision → ADR, volatile → pointer |
| **`/freshness-review`** | Tier-2 semantic gate: does prose intent still match the code? |
| **`/dist-brain`** | Query the materialized brain via MCP (`overview`, `search`, `get_entity`, …) |
| **`/verification`** | Contract → pytest loop — the checkpoint for long-running agent work |

```bash
# skills only
./init.sh ../your-repo

# skills + .grok/config.toml for the repo's wiki brain
./init.sh ../your-repo <owner>/<repo-with-wiki>
```

## Contract verification (long-running agent checkpoint)

`engine/generate_verification.py` turns `@raises` / `@returns` contracts into
`tests/generated/test_contract_verification.py`. CI can enforce stubs stay in sync:

```yaml
verify:
  uses: paddyodab/dist-brain-metadata-tooling/.github/workflows/verify.yml@v1.5
```

The `/feature` → `/verification` loop: approve contracts → implement → regenerate
stubs → pytest green. That's the oracle for goal/loop sessions — not "I think I'm
done," but gates + tests pass.

## Materialization includes IaC

When a repo has IaC, the materializer projects an **Infrastructure** wiki page and
an agent-context section: each CloudFormation/Terraform resource with its intent,
its tags, and tag coverage against `tag-policy.yml`. Resources also land in
`graph.json`, so the MCP server can query them.

## Roadmap

- **`/feature` + `/infra` + `/learning` as a Claude Code plugin** (vs. copy-in).
