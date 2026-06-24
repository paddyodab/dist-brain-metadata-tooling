#!/usr/bin/env python3
"""Materializer (stdlib-only) — reusable engine.

Analyzes a target repo (--root) and writes the wiki-flat brain into --brain
(typically a cloned .wiki.git). Projections: Home (+ Mermaid map), per-module
entity pages, Features (flag map), Runbook-<feature> (derived + authored notes
from <root>/runbooks/), and an append-only Changelog. No LLM (deterministic).

Usage: python3 materialize.py --root DIR --brain DIR [--src DIR] [--flags FILE]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from brain_store import BrainStore, DEFAULT_REVISION, export_graph_json

ENGINE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1


def git_sha(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "nogit"


def extract(root: Path, src, flags) -> tuple[list[dict], list[dict]]:
    cmd = ["python3", str(ENGINE / "extract.py"), "--root", str(root)]
    if src:
        cmd += ["--src", str(src)]
    if flags:
        cmd += ["--flags", str(flags)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out[out.find("{"):])
    nodes, edges = data["nodes"], data["edges"]
    # IaC resources (best-effort; never block the code materialization on it)
    try:
        iac = subprocess.run(["python3", str(ENGINE / "extract_iac.py"), "--root", str(root)],
                             capture_output=True, text=True, check=True).stdout
        idata = json.loads(iac[iac.find("{"):])
        nodes += idata["nodes"]
        edges += idata["edges"]
    except Exception as e:
        print(f"  ! IaC extraction skipped: {e.__class__.__name__}")
    return nodes, edges


def required_tags(root: Path) -> list[str]:
    f = root / "tag-policy.yml"
    if not f.exists():
        return []
    out, in_block = [], False
    for line in f.read_text().splitlines():
        s = line.strip()
        if s.startswith("required_tags:"):
            in_block = True
            continue
        if in_block:
            if s.startswith("- "):
                out.append(s[2:].strip())
            elif s and not s.startswith("#") and not line.startswith((" ", "\t")):
                break
    return out


def page_name(subsystem: str) -> str:
    return subsystem.split(":")[-1]


def diff_nodes(old, new) -> dict:
    o, n = {x["id"]: x for x in old}, {x["id"]: x for x in new}
    return {
        "added": [n[i] for i in n if i not in o],
        "removed": [o[i] for i in o if i not in n],
        "changed": [n[i] for i in n if i in o
                    and n[i]["provenance"]["source_sha"] != o[i]["provenance"]["source_sha"]],
    }


def short_intent(node) -> str:
    return (node.get("intent") or "_(no intent)_").split(". ")[0].strip()


def mermaid_map(entities, flags, edges) -> str:
    safe: dict[str, str] = {}

    def sid(nid: str) -> str:
        return safe.setdefault(nid, f"n{len(safe)}")

    out = ["```mermaid", "graph LR"]
    by_sub: dict[str, list[dict]] = {}
    for n in entities:
        by_sub.setdefault(n["subsystem"], []).append(n)
    for sub, ns in sorted(by_sub.items()):
        out.append(f"  subgraph {page_name(sub)}")
        for n in ns:
            out.append(f'    {sid(n["id"])}["{n["title"]}"]')
        out.append("  end")
    for fl in flags:
        out.append(f'  {sid(fl["id"])}(["🚩 {fl["title"]}"])')
    for e in edges:
        if e["type"] == "gated-by":
            out.append(f'  {sid(e["from"])} -. flag .-> {sid(e["to"])}')
        elif e["type"] == "raises":
            label = e["to"].split(":")[-1]
            out.append(f'  {sid(e["from"])} -- raises --> {sid(e["to"])}(["{label}"])')
    out.append("```")
    return "\n".join(out)


def load_runbook_notes(root: Path) -> dict[str, str]:
    d = root / "runbooks"
    notes: dict[str, str] = {}
    if d.exists():
        for f in sorted(d.glob("*.md")):
            notes[f.stem] = f.read_text().strip()
    return notes


def feature_of(flag_node, gated) -> str:
    for g in gated:
        if g["facts"].get("feature"):
            return g["facts"]["feature"]
    return flag_node["title"]


def render(brain: Path, root: Path, nodes, edges, sha, stamp) -> dict:
    entities = [n for n in nodes if n["type"] in ("function", "method")]
    flags = [n for n in nodes if n["type"] == "flag"]
    decisions = [n for n in nodes if n["type"] == "decision"]
    resources = [n for n in nodes if n["type"] == "resource"]
    req_tags = required_tags(root)
    gated_by: dict[str, list[str]] = {}
    for e in edges:
        if e["type"] == "gated-by":
            gated_by.setdefault(e["to"], []).append(e["from"])
    subsystems: dict[str, list[dict]] = {}
    for n in entities:
        subsystems.setdefault(n["subsystem"], []).append(n)

    foot = f"\n\n---\n_Generated from `{sha}` · {stamp}. Derived projection — do not edit; regenerated by the materializer._\n"
    notes = load_runbook_notes(root)
    ent_by_id = {n["id"]: n for n in entities}

    runbook_link: dict[str, tuple[str, str]] = {}
    for fl in flags:
        gated = [ent_by_id[i] for i in gated_by.get(fl["id"], []) if i in ent_by_id]
        feature = feature_of(fl, gated)
        page = f"Runbook-{feature}"
        runbook_link[fl["id"]] = (feature, page)
        rl = [f"# Runbook — {feature}", "", fl.get("intent") or "", "",
              "## Toggle (kill switch)", "",
              f"- flip flag `{fl['title']}` — default `{fl['facts'].get('default')}`, "
              f"owner {fl['facts'].get('owner') or '—'}", "", "## Affected functions", ""]
        for g in sorted(gated, key=lambda x: x["title"]):
            raises = ", ".join(g["facts"]["raises"]) or "—"
            rl.append(f"- `{g['title']}` — {short_intent(g)} _(raises: {raises})_")
        rl += ["", "## Operator notes _(authored)_", "",
               notes.get(feature) or f"_No operator notes yet — add `runbooks/{feature}.md`._"]
        (brain / f"{page}.md").write_text("\n".join(rl) + foot)

    for sub, ns in subsystems.items():
        lines = [f"# {page_name(sub)}", ""]
        for n in sorted(ns, key=lambda x: x["title"]):
            f = n["facts"]
            badge = " 🚩" if f.get("flag") else ""
            lines += [f"## `{n['title']}` · {n['type']}{badge}", "", n.get("intent") or "_(no intent)_", ""]
            lines.append(f"- **params:** {', '.join(f['params']) or '—'}")
            lines.append(f"- **returns:** {f['returns'] or '—'}")
            lines.append(f"- **raises:** {', '.join(f['raises']) or '—'}")
            if f.get("flag"):
                lines.append(f"- **feature:** `{f.get('feature') or '—'}` — gated by `{f['flag']}` (see [Features](Features))")
            p = n["provenance"]
            mark = " ✓" if p["status"] == "verified" else ""
            lines.append(f"- _source:_ `{p['source_path']}` · `{p['source_sha']}` · {p['status']}{mark}")
            lines.append("")
        (brain / f"{page_name(sub)}.md").write_text("\n".join(lines) + foot)

    flines = ["# Features", "",
              "Each feature is toggled by a flag in `flags.yml`. To turn a feature on/off, flip its flag.", ""]
    for fl in sorted(flags, key=lambda x: x["title"]):
        ff = fl["facts"]
        gates = ", ".join("`" + e.split("#")[-1] + "`" for e in gated_by.get(fl["id"], [])) or "—"
        flines += [f"## `{fl['title']}`", "", fl.get("intent") or "_(no description)_", ""]
        flines.append(f"- **default:** `{ff.get('default')}`")
        flines.append(f"- **owner:** {ff.get('owner') or '—'}")
        flines.append(f"- **gates:** {gates}")
        feature, page = runbook_link[fl["id"]]
        flines.append(f"- **runbook:** [{feature}]({page})")
        flines.append("")
    (brain / "Features.md").write_text("\n".join(flines) + foot)

    # Decisions.md — ADRs (cross-cutting 'why'), human view
    dlines = ["# Decisions", "", "Architecture decision records — the cross-cutting *why*.", ""]
    for d in sorted(decisions, key=lambda x: x["id"]):
        dlines += [f"## {d['title']}", "",
                   f"- **status:** {d['facts'].get('status') or '—'}",
                   f"- **id:** `{d['id']}`", "",
                   d.get("intent") or "",
                   f"- _source:_ `{d['provenance']['source_path']}`", ""]
    (brain / "Decisions.md").write_text("\n".join(dlines) + foot)

    # Infrastructure.md — IaC inventory + tag coverage (only if there is IaC)
    if resources:
        il = ["# Infrastructure", "",
              "IaC resources, their intent, and tag coverage against `tag-policy.yml`.", ""]
        for r in sorted(resources, key=lambda x: x["id"]):
            rf = r["facts"]
            tags = rf.get("tags") or {}
            missing = [k for k in req_tags if k not in tags]
            cov = "✓ all required tags" if not missing else f"🚩 missing {missing}"
            tagstr = ", ".join(f"{k}={v}" for k, v in sorted(tags.items())) or "—"
            il += [f"## `{r['title']}`", "", r.get("intent") or "_(no intent)_", "",
                   f"- **iac:** {rf.get('iac')} · `{rf.get('resource_type')}`",
                   f"- **tags:** {tagstr}",
                   f"- **tag coverage:** {cov}",
                   f"- _source:_ `{r['provenance']['source_path']}` · `{r['provenance']['source_sha']}`", ""]
        (brain / "Infrastructure.md").write_text("\n".join(il) + foot)

    # agent-context.md — the AGENT projection: everything in one token-dense read.
    ag = [f"# Agent context — generated from `{sha}` · {stamp}", "",
          "Read this first. Everything an agent needs about this repo: architecture, every "
          "function's contract, feature flags, runbooks, and decisions. IDs are stable "
          "(`path#symbol`, `flag:*`, `decision:*`) — cite them. `status` is verified|inferred. "
          "The canonical graph is in `brain.sqlite` (FTS-indexed; query via dist-brain MCP). "
          "`graph.json` is an optional export for small-repo compat.", "",
          f"counts: entities={len(entities)} · flags={len(flags)} · decisions={len(decisions)}", "",
          "## Functions", ""]
    for sub in sorted(subsystems):
        ag.append(f"### module: {page_name(sub)}")
        for n in sorted(subsystems[sub], key=lambda x: x["title"]):
            f = n["facts"]
            gate = f" · flag:{f['flag']}" if f.get("flag") else ""
            ag.append(f"- `{n['id']}` — {n.get('intent') or '(no intent)'}")
            ag.append(f"    params({', '.join(f['params']) or '—'}) -> {f['returns'] or 'None'}; "
                      f"raises: {', '.join(f['raises']) or '—'}{gate}; {n['provenance']['status']}")
        ag.append("")
    ag += ["## Flags", ""]
    for fl in sorted(flags, key=lambda x: x["title"]):
        ff = fl["facts"]
        gates = ", ".join(e.split("#")[-1] for e in gated_by.get(fl["id"], [])) or "—"
        ag.append(f"- `{fl['id']}` — default={ff.get('default')}, owner={ff.get('owner') or '—'} "
                  f"— gates: {gates} — {fl.get('intent') or ''}")
    ag += ["", "## Runbooks", ""]
    for fl in sorted(flags, key=lambda x: x["title"]):
        feature, page = runbook_link[fl["id"]]
        ag.append(f"- {feature}: to toggle flip `{fl['title']}` "
                  f"(default {fl['facts'].get('default')}); see [{page}]({page})")
    ag += ["", "## Decisions (ADRs)", ""]
    for d in sorted(decisions, key=lambda x: x["id"]):
        ag.append(f"- `{d['id']}` — {d['title']} — {d['facts'].get('status') or ''}")
        if d.get("intent"):
            ag.append(f"    {d['intent']}")
    if resources:
        ag += ["", "## Infrastructure", ""]
        for r in sorted(resources, key=lambda x: x["id"]):
            rf = r["facts"]
            tags = rf.get("tags") or {}
            missing = [k for k in req_tags if k not in tags]
            tagstr = ", ".join(f"{k}={v}" for k, v in sorted(tags.items())) or "—"
            ag.append(f"- `{r['id']}` ({rf.get('iac')}/{rf.get('resource_type')}) — "
                      f"{r.get('intent') or '(no intent)'}")
            ag.append(f"    tags: {tagstr}" + (f" · MISSING {missing}" if missing else ""))
    (brain / "agent-context.md").write_text("\n".join(ag) + foot)

    hlines = ["# knowledge wiki", "",
              "_Auto-generated from the source on every merge to `main`. Derived read model;"
              " edits here are overwritten._", "",
              f"![entities](https://img.shields.io/badge/entities-{len(entities)}-blue) "
              f"![flags](https://img.shields.io/badge/flags-{len(flags)}-orange) "
              f"![source](https://img.shields.io/badge/source-{sha}-lightgrey)", "",
              "## Map", "", mermaid_map(entities, flags, edges), "", "## Modules", ""]
    for sub in sorted(subsystems):
        hlines.append(f"- [{page_name(sub)}]({page_name(sub)}) — {len(subsystems[sub])} functions")
    hlines += ["", "## Operations", "", "- [Features](Features) — feature flags & how to toggle them"]
    for fl in sorted(flags, key=lambda x: x["title"]):
        feature, page = runbook_link[fl["id"]]
        hlines.append(f"- [Runbook: {feature}]({page}) — operate the {feature} feature")
    hlines += ["- [Decisions](Decisions) — architecture decision records (the *why*)"]
    if resources:
        hlines.append(f"- [Infrastructure](Infrastructure) — {len(resources)} IaC resources + tag coverage")
    hlines += ["- [Changelog](Changelog) — what changed, and why",
               "- [Agent context](agent-context) — single-file context for AI agents", ""]
    (brain / "Home.md").write_text("\n".join(hlines) + foot)

    side = ["### 🧠 knowledge wiki", "", "[Home](Home)", "", "**Modules**"]
    side += [f"- [{page_name(s)}]({page_name(s)})" for s in sorted(subsystems)]
    side += ["", "**Operations**", "- [Features](Features)", "- [Decisions](Decisions)"]
    if resources:
        side.append("- [Infrastructure](Infrastructure)")
    side += ["- [Changelog](Changelog)", "- [Agent context](agent-context)", "", "**Runbooks**"]
    side += [f"- [{runbook_link[fl['id']][0]}]({runbook_link[fl['id']][1]})"
             for fl in sorted(flags, key=lambda x: x["title"])]
    (brain / "_Sidebar.md").write_text("\n".join(side) + "\n")
    (brain / "_Footer.md").write_text(f"_Derived projection · generated from `{sha}` · {stamp} · do not edit_\n")
    return subsystems


def append_changelog(brain: Path, delta, seq, sha, stamp) -> None:
    f = brain / "Changelog.md"
    header = "# Changelog\n\n_Append-only. Newest first._\n"
    prior = ""
    if f.exists():
        body = f.read_text()
        prior = body.split("\n", 3)[-1] if body.startswith("# Changelog") else body
    entry = [f"\n## #{seq} · `{sha}` · {stamp}", ""]
    for n in sorted(delta["added"], key=lambda x: x["id"]):
        entry.append(f"- ➕ `{n['id']}` — {short_intent(n)}")
    for n in sorted(delta["changed"], key=lambda x: x["id"]):
        entry.append(f"- ✏️ `{n['id']}` — {short_intent(n)}")
    for n in sorted(delta["removed"], key=lambda x: x["id"]):
        entry.append(f"- ➖ `{n['id']}`")
    entry.append("")
    f.write_text(header + "\n".join(entry) + ("\n" + prior if prior.strip() else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--brain", required=True)
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    ap.add_argument("--snapshot-ref", default=None,
                    help="copy main → this tag revision after materialize (e.g. v1.0)")
    ap.add_argument("--no-json", action="store_true",
                    help="skip graph.json export (large-repo mode)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    brain = Path(args.brain).resolve()
    brain.mkdir(parents=True, exist_ok=True)
    sha, stamp = git_sha(root), datetime.now().isoformat(timespec="seconds")
    print(f"materialize @ {sha} (root={root})")

    nodes, edges = extract(root, args.src, args.flags)
    print(f"  · extracted {len(nodes)} nodes, {len(edges)} edges")

    # Prior state for the delta comes from the canonical store (brain.sqlite), NOT
    # graph.json. graph.json is a derived export that may be huge or absent (--no-json);
    # diffing against it was wrong at scale and treated every --no-json run as a first run.
    db_path = brain / "brain.sqlite"
    store = BrainStore.open(db_path)
    first_run = not any(r["ref"] == DEFAULT_REVISION for r in store.list_revisions())
    prev_nodes = store.load_graph(DEFAULT_REVISION)["nodes"]
    delta = diff_nodes(prev_nodes, nodes)
    changed = bool(delta["added"] or delta["removed"] or delta["changed"])
    print(f"  · delta: +{len(delta['added'])} ~{len(delta['changed'])} -{len(delta['removed'])}")

    render(brain, root, nodes, edges, sha, stamp)

    store.upsert_main(sha, nodes, edges, delta)
    foot = (
        f"\n\n---\n_Generated from `{sha}` · {stamp}. Derived projection — do not edit; "
        f"regenerated by the materializer. Features rendered from `brain.sqlite`._\n"
    )
    (brain / "Features.md").write_text(store.render_features_md(DEFAULT_REVISION) + foot)
    print(f"  · brain.sqlite @ {DEFAULT_REVISION}: {len(nodes)} nodes (incremental upsert)")

    if args.snapshot_ref:
        store.snapshot_revision(args.snapshot_ref, sha)
        print(f"  · snapshot revision `{args.snapshot_ref}` @ {sha}")

    graph = store.load_graph(DEFAULT_REVISION)
    if not args.no_json:
        export_graph_json(graph, brain / "graph.json")
        print("  · graph.json exported (compat / small-repo)")
    else:
        print("  · graph.json skipped (--no-json)")

    store.close()

    state = json.loads((brain / "state.json").read_text()) if (brain / "state.json").exists() else {"seq": 0}
    if changed or first_run:
        state["seq"] += 1
        append_changelog(brain, delta, state["seq"], sha, stamp)
        print(f"  · changelog entry #{state['seq']} appended")
    else:
        print("  · no changes (idempotent)")

    state.update({
        "schema_version": SCHEMA_VERSION,
        "last_sha": sha,
        "node_count": len(nodes),
        "brain_store": "brain.sqlite",
        "revision": DEFAULT_REVISION,
    })
    (brain / "state.json").write_text(json.dumps(state, indent=2))
    print(f"  → {brain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
