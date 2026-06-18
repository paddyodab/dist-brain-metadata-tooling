#!/usr/bin/env python3
"""Extract IaC resources (CloudFormation + Terraform) as graph nodes.

Emits {"nodes": [...], "edges": []}. Each resource node carries its intent
(CloudFormation `Metadata: { Intent: ... }`, or Terraform `# @intent ...`) and its
tags, so the materializer can project an infra inventory + tag-coverage view.
Static scan — see check_tags.py's scope note. PyYAML is needed for CloudFormation;
if absent, only Terraform is extracted.

Usage: python3 extract_iac.py [--root DIR] [--iac DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

try:
    import yaml

    class _CfnLoader(yaml.SafeLoader):
        pass

    def _intrinsic(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    yaml.add_multi_constructor("!", _intrinsic, Loader=_CfnLoader)
    _HAVE_YAML = True
except Exception:
    _HAVE_YAML = False

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".terraform"}
CFN_TAGGABLE = {
    "AWS::S3::Bucket", "AWS::EC2::Instance", "AWS::EC2::Volume", "AWS::RDS::DBInstance",
    "AWS::DynamoDB::Table", "AWS::Lambda::Function", "AWS::SQS::Queue", "AWS::SNS::Topic",
    "AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::ECS::Cluster", "AWS::ECS::Service",
}


def _sha(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def _cfn_tags(tags) -> dict:
    out = {}
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict) and "Key" in t:
                out[t["Key"]] = t.get("Value")
    elif isinstance(tags, dict):
        out = dict(tags)
    return out


def extract_cfn(path: Path, rel: str) -> list[dict]:
    if not _HAVE_YAML:
        return []
    try:
        text = path.read_text()
        doc = (yaml.load(text, Loader=_CfnLoader) if path.suffix in (".yaml", ".yml")
               else json.loads(text))
    except Exception:
        return []
    if not isinstance(doc, dict) or "Resources" not in doc:
        return []
    nodes = []
    for name, res in (doc.get("Resources") or {}).items():
        rtype = (res or {}).get("Type", "")
        if rtype not in CFN_TAGGABLE:
            continue
        props = res.get("Properties") or {}
        meta = res.get("Metadata") or {}
        nodes.append({
            "id": f"{rel}#{name}", "type": "resource", "title": f"{name} · {rtype}",
            "intent": meta.get("Intent"),
            "facts": {"iac": "cloudformation", "resource_type": rtype,
                      "tags": _cfn_tags(props.get("Tags"))},
            "subsystem": "infra",
            "provenance": {"source_path": rel, "source_sha": _sha(json.dumps(res, sort_keys=True, default=str)),
                           "status": "verified", "extracted_by": "cfn-iac@1"},
        })
    return nodes


def _match_brace(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def extract_tf(path: Path, rel: str) -> list[dict]:
    text = path.read_text()
    nodes = []
    for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text):
        rtype, rname = m.group(1), m.group(2)
        if not rtype.startswith("aws_"):
            continue
        body_open = text.index("{", m.start())
        body = text[body_open:_match_brace(text, body_open) + 1]
        im = re.search(r'#\s*@intent\s*(.+)', body)
        intent = im.group(1).strip() if im else None
        tags = {}
        tm = re.search(r'tags\s*=\s*\{', body)
        if tm:
            ts = body.index("{", tm.start())
            tb = body[ts + 1:_match_brace(body, ts)]
            for km in re.finditer(r'(?m)^\s*"?([A-Za-z0-9_.\-]+)"?\s*=\s*"?([^"\n]*)"?', tb):
                tags[km.group(1)] = km.group(2).strip().strip('"')
        nodes.append({
            "id": f"{rel}#{rtype}.{rname}", "type": "resource", "title": f"{rtype}.{rname}",
            "intent": intent,
            "facts": {"iac": "terraform", "resource_type": rtype, "tags": tags},
            "subsystem": "infra",
            "provenance": {"source_path": rel, "source_sha": _sha(body),
                           "status": "verified", "extracted_by": "tf-iac@1"},
        })
    return nodes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--iac", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    iac = Path(args.iac).resolve() if args.iac else root

    nodes = []
    for f in sorted(iac.rglob("*")):
        if not f.is_file() or set(f.parts) & SKIP_DIRS or f.name == "tag-policy.yml":
            continue
        rel = str(f.relative_to(root)) if str(f).startswith(str(root)) else str(f)
        if f.suffix in (".yaml", ".yml", ".json"):
            nodes += extract_cfn(f, rel)
        elif f.suffix == ".tf":
            nodes += extract_tf(f, rel)
    print(json.dumps({"nodes": nodes, "edges": []}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
