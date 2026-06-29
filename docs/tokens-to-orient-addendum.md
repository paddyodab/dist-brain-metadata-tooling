# Tokens to orient: addendum

Companion to `tokens-to-orient.md`. This document contextualizes the B5
measurement result, explains why it doesn't mean what it might look like,
and outlines the next step: dogfooding on a real codebase.

## The result, restated

- WITHOUT brain: 1538 tokens (4 files + 8 greps)
- WITH brain: 1723 tokens (9 MCP calls)
- Ratio: 0.89 — the brain was ~11% more expensive

The brain lost. On paper that looks bad. It isn't.

## Why the fixture can't answer the real question

The bounded-contexts example repo (`examples/bounded-contexts/`) is a test
harness, not a codebase. It has 2 Python files totaling ~50 lines. The
measurement asked "what does orders.py do and what are its dependencies?" and
the answer is reachable in one file read plus a few greps that return almost
nothing because there's no noise in a 2-file repo.

The brain's value proposition is noise reduction. It compresses a large
codebase into structured metadata so you don't have to read 200 files to
understand 5. On a fixture with no noise to compress, the compression overhead
is pure cost.

This is like benchmarking a search engine against a 2-document corpus. The
search engine can't win — reading both documents is faster than indexing them.
The measurement is valid but the scenario is wrong.

## Why the without-brain path scales badly

On a real monorepo (200+ files, multiple contexts, cross-cutting concerns):

- grep for a function name returns 40 hits across tests, configs, docs, and
  unrelated modules. You read most of them before finding the right one.
- The module you need is 800 lines, not 50. You read all of it because you
  don't know which parts matter yet.
- CONTEXT.md and contracts.yml are buried three directories deep. You don't
  know they exist, so you either miss them (wasted cycles guessing) or spend
  searches finding them.
- Dependencies spread across 5 other modules. Each is another grep + read
  cycle, each read pulling in unrelated code alongside the relevant bits.

The without-brain token cost grows roughly with repo size. The brain path
stays roughly constant per function queried — overview, search, get_entity,
neighbors. The JSON overhead is the same whether the repo has 2 files or 2000.

## What B5 actually proved

1. The measurement method works. It's repeatable and produces honest numbers.
2. The brain doesn't pay off on tiny repos. This is expected and fine.
3. We don't yet have a measurement on a real codebase. That's the gap.

## The missing measurement: dogfooding

The dist-brain-metadata-tooling repo itself is the obvious candidate for a
real measurement. It has engine/ (extract, brain_store, check_metadata,
materialize, contracts_registry, context_resolver, refresh_brain), mcp/
(server, brain_query), template/, examples/, docs/ — multiple modules with
real complexity, real cross-module dependencies, and enough surface area that
raw reading would require significant grepping and file traversal.

But the dist-brain repo doesn't dogfood its own behavior. Its own source files
don't carry @intent/@param/@returns tags. There's no CONTEXT.md in engine/
or mcp/. No contracts.yml defining the valid tag vocabulary per context. The
engine can extract metadata from repos that use the dist-brain convention,
but it doesn't use the convention on itself.

This is the gap that `repo-intents` is designed to close. See the design
discussion in the next section.

---

## Next: repo-intents

The dist-brain engine works. The bounded-contexts features (context resolver,
contracts gate, glossary auto-propose, MCP context scoping, materializer
per-context projections) all pass their tests. But the engine has never been
run on a codebase that actually uses the full convention — including itself.

`repo-intents` is the dogfooding repo. It recreates the dist-brain metadata
convention in a new codebase that uses the convention from day one: every
module carries @intent/@param/@returns, every context has CONTEXT.md and
contracts.yml, and the brain is built and queried against the repo's own
source. The repo is self-documenting.

The broader vision and architecture for repo-intents is being fleshed out
separately. This addendum exists to explain why B5's negative result is a
starting point, not a verdict.

---

*Written 2026-06-27.*