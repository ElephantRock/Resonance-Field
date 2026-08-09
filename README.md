# Resonance Field

**A research platform for artificial cognitive ecosystems.**

Resonance Field explores whether useful collective organization can emerge from local interactions among initially general-purpose AI agents operating over a shared, decaying cognitive substrate.

The project is built around a falsifiable question:

> Given agents with common capabilities and no predefined professions, can memory decay, local information, resource scarcity, reputation, recombination, adversarial pressure, and environmental adaptation produce useful organizational structures that were not explicitly specified?

## v0.1 Scope

Resonance Field v0.1 focuses on eight mechanisms:

1. **Stigmergic substrate** — persistent traces with semantic retrieval and decay.
2. **Generic agent runtime** — common primitive actions rather than predefined occupational roles.
3. **Compute economy** — bounded compute credits and market-based task allocation.
4. **Reputation genome** — evidence-backed estimates for truth, creativity, bridging, and dissent.
5. **Night exploration** — proactive sampling of cooling, unresolved, or neglected traces.
6. **Memetic evolution** — crossover, mutation, lineage, adoption, and resurrection.
7. **Adversarial ecology** — challenge pressure and controlled dissent forks.
8. **Gardener interventions** — bounded environmental changes driven by ecosystem metrics.

## Initial Vertical Slice

```text
WRITE_TRACE -> DECAY -> RETRIEVE -> REINFORCE -> REDISCOVER
```

The first milestone establishes the substrate before market, reputation, Oracle, and Gardener mechanisms are layered on top.

## Architecture

```text
Human / External Requests
          |
      Control API
          |
   Resonance Runtime
   /      |       \
Agent   Event      Policy
Runtime  Bus       Gateway
   \      |       /
      Substrate
 PostgreSQL + pgvector
          |
   Metrics / Tracing
    OpenTelemetry
```

See [`docs/architecture.md`](docs/architecture.md) for the v0.1 technical baseline and [`docs/emergence-metrics.md`](docs/emergence-metrics.md) for the emergence measurement framework.

## Repository Layout

```text
src/resonance/      Core runtime package
docs/               Architecture and research specifications
configs/            Versioned experiment configuration
tests/              Unit and integration tests
docker/             Local container environment
.github/workflows/  CI
```

## Development

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Project Status

**Pre-alpha / v0.1 architecture baseline.** APIs and schemas are expected to evolve as experiments invalidate or refine mechanisms.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
