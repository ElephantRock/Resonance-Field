# Resonance Field v0.1 — Technical Architecture

## 1. Objective

Resonance Field v0.1 is an experimental multi-agent runtime in which agents operate over a shared persistent cognitive substrate. It is designed to test whether useful organizational structures can arise from local interactions rather than being encoded as fixed agent professions.

The architecture separates three layers of claims:

1. **Designed mechanisms** — memory, decay, market allocation, reputation, challenge pressure, policy.
2. **Agent behavior** — actions selected by agents under local context and resource constraints.
3. **Emergent structures** — persistent organization not explicitly assigned in prompts or code.

## 2. Non-goals

v0.1 does not attempt artificial consciousness, unrestricted autonomous internet activity, self-replicating agents, autonomous safety-policy modification, blockchain settlement, model-weight evolution, or storage of private chain-of-thought.

## 3. Design principles

- **Locality:** agents act from locally available evidence rather than a complete global state.
- **Persistent consequences:** useful and harmful actions modify durable system state.
- **Scarcity:** inference, tools, branches, and persistence consume bounded resources.
- **Decay:** unused information loses retrieval salience over time.
- **Provenance:** meaningful actions leave structured decision records without requiring hidden chain-of-thought.
- **Environmental control:** the Gardener changes bounded environmental parameters rather than rewriting agent conclusions.
- **Measurability:** emergence claims must survive quantitative analysis and ablation.

## 4. Logical topology

```text
                         Human / External Requests
                                   |
                              Control API
                                   |
                         Resonance Runtime
              +--------------------+--------------------+
              |                    |                    |
       Agent Scheduler       Policy Gateway       Market Engine
       Oracle Manager           Gardener          Night Scheduler
              |                    |                    |
        Agent Runtime <------ Event / Work Bus --------+
              |                    |
              +--------- Substrate +
                    PostgreSQL + pgvector
              traces / tasks / reputation / economy
              lineage / collisions / audit events
                                   |
                           Metrics / Tracing
                            OpenTelemetry
```

v0.1 should begin as a modular monolith plus worker processes. Logical boundaries should be preserved so services can later split without changing domain contracts.

## 5. Generic agent model

Agents begin with common primitive capabilities and SHOULD NOT receive occupational labels such as Forager, Critic, Librarian, Broker, or Synthesist.

Primitive action vocabulary:

```text
OBSERVE
QUERY_SUBSTRATE
READ_TRACE
WRITE_TRACE
REINFORCE_TRACE
CHALLENGE_TRACE
CROSSOVER
POST_TASK
BID_TASK
DELEGATE
REQUEST_TOOL
REQUEST_FORK
VOTE
ABSTAIN
SLEEP
```

A Forager-like role is therefore an observed behavioral cluster, not an initial class declaration.

## 6. Trace model

Canonical trace fields:

```text
trace_id
agent_id
kind
content
embedding
created_at
updated_at
initial_energy
half_life_seconds
confidence
quality_score
parent_trace_ids
source_trace_ids
adoption_count
reinforcement_count
semantic_region
status
safety_class
visibility
```

Initial trace kinds:

```text
OBSERVATION
CLAIM
HYPOTHESIS
SYNTHESIS
QUESTION
CHALLENGE
COUNTEREXAMPLE
PREDICTION
RESULT
FAILED_BRANCH
MORNING_HYPOTHESIS
LANDMARK
```

## 7. Trace decay

For trace `i`:

```text
E_i(t) = E_0,i * 2 ^ (-(t - t_0) / h_i)
```

where `h_i` is the half-life.

Reinforcement updates energy using bounded contributions from verified reinforcement, independent adoption, and downstream utility. Mere reads must not strongly reinforce a trace, otherwise retrieval loops can make traces immortal.

## 8. Retrieval

Retrieval is multi-objective rather than raw cosine similarity:

```text
score =
    w_semantic * semantic_similarity
  + w_energy   * energy
  + w_quality  * quality
  + w_context  * context_compatibility
  + w_adoption * adoption
  + w_explore  * exploration_bonus
  - w_repeat   * repetition_penalty
```

Default experiment weights are versioned in `configs/v0.1.yaml` and are not protocol constants.

## 9. Exploration pressure

Underexplored semantic regions receive a bounded exploration bonus. This provides pressure toward intellectual exploration without prompting a dedicated Forager role.

## 10. Resonance collisions

A candidate bridge trace `C` connecting parent traces `A` and `B` can be scored as:

```text
bridge(A, B, C) = min(sim(C,A), sim(C,B)) * (1 - sim(A,B))
```

High-scoring candidates can emit a `collision.detected` event and create an explicit resonance relation.

## 11. Day and Night operation

**Day mode** prioritizes external tasks, active markets, evidence retrieval, execution, and verification.

**Night mode** samples cooling, unresolved, failed, or neglected traces and applies controlled operators such as reinterpretation, crossover, counterfactual generation, domain transfer, and constraint reversal. Outputs are `MORNING_HYPOTHESIS` traces with limited initial energy and must earn persistence.

## 12. Memetic lineage

Crossovers and mutations store explicit parent relationships. Initial mutation operators:

- analogy;
- inversion;
- constraint substitution;
- scale transformation;
- counterfactual;
- composition;
- simplification.

Interestingness is not popularity. Evaluation combines novelty, downstream utility, bridge value, independent adoption, and optional human review.

## 13. Reputation genome

Reputation is **not spendable currency**. It is evidence about agent capability.

Initial dimensions:

- Truth Bond;
- Creativity;
- Bridge Score;
- Dissent Value.

Dimensions should be stored as Bayesian evidence, for example Beta-distribution parameters `(alpha, beta)`, rather than arbitrary directly editable floats.

## 14. Compute economy

Agents spend **compute credits** on inference, tools, simulations, and Oracle branches. Reputation influences eligibility and allocation but is not destroyed when compute is consumed.

A minimum exploration stipend prevents successful incumbents from capturing all compute.

## 15. Task market

Tasks expose a budget, success condition, and optional capability constraints. Agents submit sealed bids containing price, confidence, and a concise strategy summary. Selection combines reputation, confidence, diversity contribution, and price rather than choosing the lowest bid automatically.

## 16. Adversarial challenge pressure

The Nematode begins as a challenge mechanism, not necessarily a permanent agent species. It targets fast-rising, high-impact, or consensus-dominant traces and produces structured attacks such as contradictions, unsupported assumptions, counterexamples, causal confusion, distribution shift, Goodhart failures, security failures, or externalities.

Dissent Value increases only when later evaluation finds the challenge materially useful.

## 17. Oracle

The Oracle launches isolated branches with independent mutable state, bounded budgets, explicit stopping conditions, and recursion limits.

Evaluation preference order:

1. deterministic test;
2. empirical outcome;
3. executable benchmark;
4. externally verified data;
5. structured human evaluation;
6. model-based judge.

Losing branches are archived as `FAILED_BRANCH` traces rather than deleted.

## 18. Gardener

Allowed environmental interventions include bounded changes to trace half-life, exploration bonus, consensus tax, retrieval temperature, novelty reward, resource allocation, experiment regions, and challenge probability.

The Gardener must not secretly rewrite outputs, manufacture evidence, alter reputation history, delete valid audit history, or change safety policy.

## 19. Safety governor

The Safety Governor sits outside the agent economy. External side-effect actions pass through a policy gateway that may allow, restrict, require human approval, or reject an action.

Humans can freeze branches, agents, semantic regions, or tools. Freeze operations preserve history and set execution state to `HALTED_FOR_REVIEW`.

## 20. Provenance

Every meaningful decision stores structured provenance including trigger, retrieved trace IDs, action, tool calls, outputs, confidence, compute spent, policy result, model/runtime metadata, and timestamps. Private chain-of-thought is not required or stored.

## 21. Core event subjects

```text
trace.created
trace.reinforced
trace.decayed
trace.archived
collision.detected
task.created
task.bid
task.awarded
task.completed
agent.action
agent.idle
reputation.updated
credits.transferred
challenge.created
challenge.resolved
oracle.started
oracle.branch.completed
oracle.resolved
gardener.intervention
policy.rejected
human.veto
```

Consumers must be idempotent because delivery may be at least once.

## 22. Storage and runtime

Initial choices:

- Python 3.12+
- PostgreSQL + pgvector for canonical state and vector retrieval
- LangGraph-compatible agent state machines
- NATS JetStream-compatible work/event transport
- S3-compatible object storage for large artifacts
- OpenTelemetry for traces, metrics, and logs
- Temporal only when durable long-running workflows justify the additional infrastructure

## 23. Required ablations

Every major mechanism must be feature-flagged. Minimum experiment matrix:

```text
A0  Full system
A1  No decay
A2  No market
A3  No reputation
A4  No Night Mode
A5  No crossover
A6  No challenge pressure
A7  No Gardener
A8  No compute scarcity
A9  No exploration bonus
A10 Explicit roles instead of emergent roles
```

Compare task performance, novelty, specialization, diversity, cost, robustness, adaptability, and error rate.

## 24. v0.1 acceptance target

The platform is successful when it can reproducibly measure whether agents with common capabilities develop persistent behavioral niches, and when the contribution of individual mechanisms can be tested through controlled ablation.

The target is not that agents "appear alive." The target is a measurable, falsifiable artificial cognitive ecosystem.
