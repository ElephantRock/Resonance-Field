# Lifecycle Campaign — Experiments 063–074

## Research question

Experiments 001–062 kept market-active identities effectively immortal. They varied
trace decay, reputation, practice gain, environmental regime duration, and several
forms of active-memory attenuation, but the actors themselves remained continuously
eligible to compete.

The lifecycle campaign asks:

> Does finite competitive lifetime preserve fast capability formation while reducing
> incumbent entrenchment, with useful shared substrate knowledge surviving succession?

The primary intervention is **competitive exit**, not deletion. Population size stays
constant: every exiting actor is immediately replaced by a fresh equivalent identity.

## Persistence layers

The campaign separates:

- **competitive persistence** — whether an identity may continue bidding;
- **private capability persistence** — identity-specific practice history;
- **reputation persistence** — evidence attached to the old identity;
- **cultural persistence** — public traces left in the shared substrate;
- **lineage persistence** — whether the same succession seat continues to dominate.

A successor receives a new agent identity, neutral reputation, and no private practice.
The predecessor's exact remaining compute-credit balance transfers to the successor,
so succession does not inject or erase economic resources. Public traces remain unless
an experiment explicitly diversifies retrieval.

## Public knowledge channel

The integration simulator previously used author-specific verified traces as bid
evidence. The lifecycle campaign adds a fixed shared-knowledge channel for every arm:
decayed verified traces for the required skill are retrievable across authors and
provide a bounded contribution to confidence and task success.

This is necessary to distinguish "the actor died" from "the civilization forgot."
The channel is identical across the core lifecycle arms.

## Incumbency metrics

The existing `early_incumbent_share` follows population slots and therefore becomes a
**lineage/seat incumbency** metric under succession.

The campaign adds `early_actor_incumbent_share`, which follows exact agent identity.
A replacement in the same slot breaks actor incumbency while preserving lineage
continuity. Reporting both exposes whether succession removes individual power but
leaves dynastic/institutional dominance intact.

Additional lifecycle metrics include:

- turnover events and turnover rate;
- mean public-knowledge signal;
- retrieval-lineage HHI;
- predecessor-lineage retrieval share;
- newborn success rate;
- maximum generation reached.

## Experimental sequence

1. **063 — immortal high-learning baseline.** Reproduce the fast-practice regime with
   and without reference reputation.
2. **064 — fixed competitive exit.** Staggered fixed-age retirement plus immediate
   fresh replacement.
3. **065 — stochastic retirement.** Same expected lifetime, stochastic exogenous
   hazard.
4. **066 — turnover dose.** Short, medium, and long fixed lifetimes.
5. **067 — death versus retirement.** Same exit schedule; compare hard destruction of
   private executable state with silent retirement. Public traces remain in both.
6. **068 — advisory retirement.** Test whether explicit post-retirement consultation
   preserves knowledge without recreating competitive incumbency.
7. **069 — reputation interaction.** Cross the selected lifecycle with reference
   reputation and no reputation to determine whether succession is intrinsically
   useful or specifically counteracts reputation accumulation.
8. **070 — rapid regime shift.** Stress the selected lifecycle under faster
   task-to-skill remapping.
9. **071 — cultural persistence.** Compare ordinary public retrieval with
   lineage-diversified retrieval.
10. **072 — synthesis.** Test whether fast learning, quality, actor turnover, lineage
    plasticity, and knowledge survival can coexist.
11. **073 — independent replication.**
12. **074 — unseen holdout.** New seeds, remap cadence, candidate count, lifetime, and
    lifecycle phase.

## Causal success criterion

Competitive exit counts as a discovery only if the finite-lifecycle candidate:

1. preserves task success within the pre-registered success tolerance;
2. reduces actor incumbency by at least the configured absolute threshold;
3. retains the configured fraction of the immortal arm's public knowledge signal;
4. does not create an unacceptable lineage-incumbency increase;
5. preserves all existing economic/provenance invariants;
6. passes independent replication and the unseen holdout.

## Death and retirement semantics

"Death" in this experiment means destruction of executable/private identity state.
Audit history and public traces remain because scientific provenance is append-only.

"Retirement" means the old identity loses bidding and ordinary trace-writing
eligibility but may retain archived private state. It is not consultable unless the
experiment explicitly enables the advisor channel.

Therefore the campaign tests whether **authority must expire**, not whether historical
records should be deleted.

## Cultural bracket

Lineage-diversified retrieval does not delete dominant traces or assign them shorter
half-lives. It limits how many traces from one succession lineage occupy the bounded
public retrieval set before other lineages are represented.

This tests cultural monopoly while preserving history.

## Out of scope

The campaign does not implement:

- bankruptcy-driven extinction;
- "no wins for N cycles" death;
- endogenous mortality;
- lineage reputation inheritance;
- autonomous reproduction;
- production reputation scoring.

Those mechanisms would confound the first causal test of competitive exit. Compute
resource refresh is also out of scope: succession conserves the lineage's exact remaining
credit balance rather than issuing a fresh endowment.

Production remains reputation-neutral regardless of campaign outcome.
