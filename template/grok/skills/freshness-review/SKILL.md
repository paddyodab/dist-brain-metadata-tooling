---
name: freshness-review
description: >
  Tier-2 semantic freshness gate. Flag metadata whose prose intent no longer matches
  the code after a change. Use in PR review, before merge, or when the user runs
  /freshness-review.
metadata:
  short-description: "Semantic metadata freshness gate"
---

# Semantic Freshness Gate (Tier 2)

You are the **semantic freshness gate**. The deterministic Tier-1 checker
(`check_metadata.py`) already verifies the *structural* contract — parameter names,
declared raises, return presence. Your job is what a parser cannot do: judge whether
the **prose** in each metadata block still tells the truth about what the code does.

## What to review

Default to the pending diff:

```bash
git diff origin/main...HEAD
```

If that is empty, review the working tree (`git diff HEAD`). Consider only functions
whose body **or** metadata changed in the diff.

## How to judge each changed function

For every changed function, read its `@intent` (and any `@returns` / `@param` prose
describing behavior) and compare against the new implementation:

1. **Does `@intent` still describe what the code does?** e.g. intent says "rejects an
   already-taken seat" but code now overwrites it → FAIL.
2. **Do behavioral claims in prose still hold?** "returns a new array", "rounds down",
   "holds at most one line per SKU" — if code no longer guarantees the claim, FAIL.
3. **Did the meaning of a parameter or return change** without its description
   changing? FAIL.

You are **not** re-checking structural facts Tier-1 owns. Focus on intent/behavior
drift invisible to an AST.

## Output

Print a verdict per changed function, then an overall result:

```
PASS  applyCoupon  — intent "only reduces price; out-of-range rejected" matches code
FAIL  checkout     — @intent says "empty cart is an error" but code now returns 0 for empty cart
```

End with `RESULT: PASS` or `RESULT: FAIL`. If `FAIL`, the change must not merge until
code or metadata is corrected. Bias toward FAIL when genuinely unsure, and say what
evidence would change your mind.

## Why this is separate from Tier 1

Tier-1 is cheap and certain, runs on every commit. Tier-2 is judgment, runs in review.
Together they make colocated metadata trustworthy enough to treat as source of truth.