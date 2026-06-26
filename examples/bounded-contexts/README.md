# Bounded-contexts example

A minimal two-context monorepo used by the dist-brain integration tests:

- `backend/` — service context (fastapi-style python)
- `frontend/` — component context (react-style python, same language, different tag vocabulary)

The backend's `contracts.yml` permits `@returns` and `@raises`; the frontend's permits
`@props` and `@renders` but not backend tags. This is the "context-driven, not
language-driven" rule in practice.

Run the end-to-end test:

    python3 -m unittest engine.test_bounded_contexts
