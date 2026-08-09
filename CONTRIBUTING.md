# Contributing

Resonance Field is research software. Changes should preserve the distinction between designed mechanisms and measured emergence.

## Development workflow

1. Create a focused branch from `main`.
2. Add or update tests for behavioral changes.
3. Run `ruff check .` and `pytest`.
4. Keep mechanism parameters configurable where they are expected to participate in ablation experiments.
5. Document changes that alter experimental semantics.

## Design constraints

- Do not introduce occupational agent roles as defaults when the behavior can be measured post hoc.
- Do not make reputation directly spendable; compute credits are the consumable resource.
- Do not allow agents to alter safety policy or audit history.
- Do not treat model-generated hidden reasoning as required provenance.
- Prefer falsifiable metrics over anthropomorphic claims.

## Commits

Use concise imperative or conventional commit messages where practical.

## Pull requests

A pull request should explain:

- what mechanism changes;
- why it is needed;
- how it is tested;
- which emergence metrics or ablations may be affected.
