#!/usr/bin/env python3
"""IaC Tier-1 gate: every taggable resource carries the required tag keys.

The infrastructure analog of the code metadata gate. The "contract" for IaC is a
minimal tag set (Owner / Environment / CostCenter / Service, …) declared in the
consumer repo's tag-policy.yml — the thing teams get flagged for missing. Supports
CloudFormation (YAML/JSON) and Terraform (HCL).

Analyzes a target repo via --root (default $GITHUB_WORKSPACE). If the repo has no
tag-policy.yml, the gate no-ops cleanly — so the workflow is safe to enable
everywhere.

Usage: python3 check_tags.py [--root DIR] [--iac DIR] [--policy FILE]

Scope note: pair or replace with the mature ecosystem in production — cfn-lint,
tflint, Checkov, OPA/Conftest — and read Terraform from `terraform show -json` so
provider default_tags / locals / vars resolve (this static scan sees only literal
resource tags). Requires PyYAML for CloudFormation parsing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import yaml

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".terraform"}


def load_policy(path: Path) -> list[str]:
    if not path.exists():
        return []
    return list((yaml.safe_load(path.read_text()) or {}).get("required_tags", []))


# ---- CloudFormation -------------------------------------------------------

class _CfnLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


yaml.add_multi_constructor("!", _intrinsic, Loader=_CfnLoader)

CFN_TAGGABLE = {
    "AWS::S3::Bucket", "AWS::EC2::Instance", "AWS::EC2::Volume", "AWS::RDS::DBInstance",
    "AWS::DynamoDB::Table", "AWS::Lambda::Function", "AWS::SQS::Queue", "AWS::SNS::Topic",
    "AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::ECS::Cluster", "AWS::ECS::Service",
}


def _cfn_tag_keys(tags) -> set:
    if isinstance(tags, list):
        return {t.get("Key") for t in tags if isinstance(t, dict)}
    if isinstance(tags, dict):
        return set(tags.keys())
    return set()


def check_cfn(path: Path, rel: str, required: list[str]) -> list[str]:
    try:
        text = path.read_text()
        doc = (yaml.load(text, Loader=_CfnLoader) if path.suffix in (".yaml", ".yml")
               else json.loads(text))
    except Exception:
        return []
    if not isinstance(doc, dict) or "Resources" not in doc:
        return []
    errs = []
    for name, res in (doc.get("Resources") or {}).items():
        rtype = (res or {}).get("Type", "")
        if rtype not in CFN_TAGGABLE:
            continue
        present = _cfn_tag_keys((res.get("Properties") or {}).get("Tags"))
        missing = [k for k in required if k not in present]
        if missing:
            errs.append(f"{rel}: {name} ({rtype}) missing tags {missing}")
    return errs


# ---- Terraform (static HCL scan) ------------------------------------------

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


def check_tf(path: Path, rel: str, required: list[str]) -> list[str]:
    text = path.read_text()
    errs = []
    for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text):
        rtype, rname = m.group(1), m.group(2)
        if not rtype.startswith("aws_"):
            continue
        body_open = text.index("{", m.start())
        body = text[body_open:_match_brace(text, body_open) + 1]
        present: set = set()
        tm = re.search(r'tags\s*=\s*\{', body)
        if tm:
            ts = body.index("{", tm.start())
            tags_body = body[ts + 1:_match_brace(body, ts)]
            present = {km.group(1) for km in re.finditer(
                r'(?m)^\s*"?([A-Za-z0-9_.\-]+)"?\s*=', tags_body)}
        missing = [k for k in required if k not in present]
        if missing:
            errs.append(f"{rel}: {rtype}.{rname} missing tags {missing}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--iac", default=None, help="dir to scan (default: root)")
    ap.add_argument("--policy", default=None, help="tag policy file (default: <root>/tag-policy.yml)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    iac = Path(args.iac).resolve() if args.iac else root
    policy = Path(args.policy).resolve() if args.policy else root / "tag-policy.yml"

    required = load_policy(policy)
    if not required:
        print(f"No tag-policy.yml (or no required_tags) at {policy} — IaC tag gate skipped.")
        return 0

    errs: list[str] = []
    for f in sorted(iac.rglob("*")):
        if not f.is_file() or set(f.parts) & SKIP_DIRS or f.name == "tag-policy.yml":
            continue
        rel = str(f.relative_to(root)) if str(f).startswith(str(root)) else str(f)
        if f.suffix in (".yaml", ".yml", ".json"):
            errs += check_cfn(f, rel, required)
        elif f.suffix == ".tf":
            errs += check_tf(f, rel, required)

    if errs:
        print("IaC tag contract FAILED:\n")
        for e in errs:
            print(f"  ✗ {e}")
        print(f"\n{len(errs)} resource(s) missing required tags {required}.")
        return 1
    print(f"IaC tag contract passed ✓  (required: {required})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
