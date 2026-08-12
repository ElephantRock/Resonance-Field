"""Deterministic substrate-ablation campaign for Experiments 138–141."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .epistemic_substrate_config import (
    EXPECTED_EVIDENCE_REGIMES,
    EXPECTED_RESONANCE,
    EpistemicSubstrateConfig,
)

Triple = tuple[int, int, int]
Key = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: int
    subject: int
    relation: int
    object: int
    epoch: int
    producer_id: int
    packet_id: int

    @property
    def triple(self) -> Triple:
        return (self.subject, self.relation, self.object)

    @property
    def key(self) -> Key:
        return (self.subject, self.relation)


@dataclass(frozen=True, slots=True)
class Query:
    query_id: int
    source: int
    relations: tuple[int, ...]
    target: int
    path: tuple[Triple, ...]


@dataclass(frozen=True, slots=True)
class World:
    seed: int
    claims: tuple[Claim, ...]
    reports: tuple[tuple[Claim, ...], ...]
    transfer_queries: tuple[Query, ...]
    discovery_queries: tuple[Query, ...]
    truth: tuple[tuple[int, ...], ...]
    fast_change: frozenset[Key]
    slow_change: frozenset[Key]
    rumor: frozenset[Key]


@dataclass(frozen=True, slots=True)
class Retrieval:
    claims: tuple[Claim, ...]
    cost: int
    complete: bool


@dataclass(frozen=True, slots=True)
class QueryResult:
    predicted_target: int | None
    path: tuple[Triple, ...]
    producer_ids: frozenset[int]
    retrieval_cost: int


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    arm: str
    transfer_accuracy: float
    collective_emergence_ratio: float
    evidence_coverage: float
    contradiction_resolution_f1: float
    bridge_recall: float
    provenance_completeness: float
    knowledge_survival_rate: float
    duplicate_work_rate: float
    false_synthesis_rate: float
    retrieval_items_consumed: float

    def to_dict(self) -> dict[str, str | float]:
        return {
            "arm": self.arm,
            "transfer_accuracy": self.transfer_accuracy,
            "collective_emergence_ratio": self.collective_emergence_ratio,
            "evidence_coverage": self.evidence_coverage,
            "contradiction_resolution_f1": self.contradiction_resolution_f1,
            "bridge_recall": self.bridge_recall,
            "provenance_completeness": self.provenance_completeness,
            "knowledge_survival_rate": self.knowledge_survival_rate,
            "duplicate_work_rate": self.duplicate_work_rate,
            "false_synthesis_rate": self.false_synthesis_rate,
            "retrieval_items_consumed": self.retrieval_items_consumed,
        }


class Substrate:
    """Common immutable query surface for all four treatment adapters."""

    has_provenance = False

    def retrieve(self, subject: int, relation: int, budget: int) -> Retrieval:
        raise NotImplementedError

    def choose(self, claims: tuple[Claim, ...]) -> Claim | None:
        raise NotImplementedError


class PileSubstrate(Substrate):
    def __init__(self, reports: tuple[tuple[Claim, ...], ...], claim_cost: int) -> None:
        self._reports = reports
        self._claim_cost = claim_cost

    def retrieve(self, subject: int, relation: int, budget: int) -> Retrieval:
        matches: list[Claim] = []
        cost = 0
        for report in self._reports:
            for claim in report:
                if claim.subject != subject or claim.relation != relation:
                    continue
                if cost + self._claim_cost > budget:
                    return Retrieval(tuple(matches), cost, False)
                matches.append(claim)
                cost += self._claim_cost
        return Retrieval(tuple(matches), cost, True)

    def choose(self, claims: tuple[Claim, ...]) -> Claim | None:
        if not claims:
            return None
        objects = {claim.object for claim in claims}
        if len(objects) != 1:
            return None
        return max(claims, key=lambda claim: (claim.epoch, -claim.claim_id))


class SharedMemorySubstrate(Substrate):
    has_provenance = True

    def __init__(self, claims: tuple[Claim, ...], claim_cost: int) -> None:
        by_subject: dict[int, list[Claim]] = defaultdict(list)
        for claim in claims:
            by_subject[claim.subject].append(claim)
        self._by_subject = {subject: tuple(items) for subject, items in by_subject.items()}
        self._claim_cost = claim_cost

    def retrieve(self, subject: int, relation: int, budget: int) -> Retrieval:
        relevant: list[Claim] = []
        cost = 0
        candidates = self._by_subject.get(subject, ())
        for claim in candidates:
            if cost + self._claim_cost > budget:
                return Retrieval(tuple(relevant), cost, False)
            cost += self._claim_cost
            if claim.relation == relation:
                relevant.append(claim)
        return Retrieval(tuple(relevant), cost, True)

    def choose(self, claims: tuple[Claim, ...]) -> Claim | None:
        return _static_provenance_choice(claims)


class ProvenanceGraphSubstrate(Substrate):
    has_provenance = True

    def __init__(self, claims: tuple[Claim, ...], claim_cost: int) -> None:
        by_key: dict[Key, list[Claim]] = defaultdict(list)
        for claim in claims:
            by_key[claim.key].append(claim)
        self._by_key = {key: tuple(items) for key, items in by_key.items()}
        self._claim_cost = claim_cost

    def retrieve(self, subject: int, relation: int, budget: int) -> Retrieval:
        claims = self._by_key.get((subject, relation), ())
        available = budget // self._claim_cost
        selected = claims[:available]
        cost = len(selected) * self._claim_cost
        return Retrieval(tuple(selected), cost, len(selected) == len(claims))

    def choose(self, claims: tuple[Claim, ...]) -> Claim | None:
        return _static_provenance_choice(claims)


class ResonanceFieldSubstrate(ProvenanceGraphSubstrate):
    def __init__(
        self,
        claims: tuple[Claim, ...],
        claim_cost: int,
        activation: dict[int, float],
        override_margin: float,
    ) -> None:
        super().__init__(claims, claim_cost)
        self._activation = activation
        self._override_margin = override_margin

    def choose(self, claims: tuple[Claim, ...]) -> Claim | None:
        if not claims:
            return None
        by_object: dict[int, list[Claim]] = defaultdict(list)
        for claim in claims:
            by_object[claim.object].append(claim)
        if len(by_object) == 1:
            return max(claims, key=lambda claim: (self._activation[claim.claim_id], claim.epoch))

        support = {obj: len(items) for obj, items in by_object.items()}
        activation = {
            obj: max(self._activation[claim.claim_id] for claim in items)
            for obj, items in by_object.items()
        }
        support_order = sorted(support, key=lambda obj: (-support[obj], obj))
        activation_order = sorted(activation, key=lambda obj: (-activation[obj], obj))
        support_winner = support_order[0]
        activation_winner = activation_order[0]

        support_tied = support[support_winner] == support[support_order[1]]
        runner_up = activation[activation_order[1]]
        activation_margin = activation[activation_winner] - runner_up
        latest = {
            obj: max(claim.epoch for claim in items)
            for obj, items in by_object.items()
        }

        if support_winner != activation_winner:
            if activation_margin < self._override_margin:
                return None
            chosen_object = activation_winner
        elif support_tied:
            if activation_margin < self._override_margin:
                return None
            chosen_object = activation_winner
        else:
            freshest_other = max(latest[obj] for obj in latest if obj != support_winner)
            if latest[support_winner] < freshest_other and activation_margin < self._override_margin:
                return None
            chosen_object = support_winner

        items = by_object[chosen_object]
        return max(items, key=lambda claim: (self._activation[claim.claim_id], claim.epoch))


def _static_provenance_choice(claims: tuple[Claim, ...]) -> Claim | None:
    if not claims:
        return None
    by_object: dict[int, list[Claim]] = defaultdict(list)
    for claim in claims:
        by_object[claim.object].append(claim)
    if len(by_object) == 1:
        return max(claims, key=lambda claim: (claim.epoch, -claim.claim_id))

    support = {obj: len(items) for obj, items in by_object.items()}
    ordered = sorted(support, key=lambda obj: (-support[obj], obj))
    winner = ordered[0]
    if support[winner] == support[ordered[1]]:
        return None
    latest_winner = max(claim.epoch for claim in by_object[winner])
    latest_other = max(
        claim.epoch
        for obj, items in by_object.items()
        if obj != winner
        for claim in items
    )
    if latest_winner < latest_other:
        return None
    return max(by_object[winner], key=lambda claim: (claim.epoch, -claim.claim_id))


def _truth_maps(seed: int, entity_count: int, relation_type_count: int) -> tuple[tuple[int, ...], ...]:
    rng = random.Random(seed ^ 0xA5A5)
    maps: list[tuple[int, ...]] = []
    for _ in range(relation_type_count):
        values = list(range(entity_count))
        rng.shuffle(values)
        maps.append(tuple(values))
    return tuple(maps)


def _apply_relations(
    truth: tuple[tuple[int, ...], ...],
    source: int,
    relations: tuple[int, ...],
) -> tuple[int, tuple[Triple, ...]]:
    current = source
    path: list[Triple] = []
    for relation in relations:
        target = truth[relation][current]
        path.append((current, relation, target))
        current = target
    return current, tuple(path)


def _make_transfer_queries(
    rng: random.Random,
    config: EpistemicSubstrateConfig,
    truth: tuple[tuple[int, ...], ...],
) -> tuple[Query, ...]:
    queries: list[Query] = []
    seen: set[tuple[int, tuple[int, ...]]] = set()
    attempts = 0
    while len(queries) < config.transfer_query_count:
        attempts += 1
        if attempts > 10000:
            raise RuntimeError("unable to construct unique transfer queries")
        hops = config.transfer_path_hops[len(queries) % len(config.transfer_path_hops)]
        source = rng.randrange(config.entity_count)
        relations = tuple(rng.randrange(config.relation_type_count) for _ in range(hops))
        signature = (source, relations)
        if signature in seen:
            continue
        target, path = _apply_relations(truth, source, relations)
        keys = [(subject, relation) for subject, relation, _ in path]
        if len(keys) != len(set(keys)):
            continue
        seen.add(signature)
        queries.append(Query(len(queries), source, relations, target, path))
    return tuple(queries)


def _wrong_object(rng: random.Random, truth_object: int, entity_count: int) -> int:
    value = rng.randrange(entity_count - 1)
    return value + int(value >= truth_object)


def _required_keys(queries: Iterable[Query]) -> dict[Key, int]:
    required: dict[Key, int] = {}
    for query in queries:
        for subject, relation, obj in query.path:
            existing = required.setdefault((subject, relation), obj)
            if existing != obj:
                raise AssertionError("truth path assigned two objects to one relation key")
    return required


def _claim_specs_for_required(
    rng: random.Random,
    required: dict[Key, int],
    config: EpistemicSubstrateConfig,
) -> tuple[list[tuple[int, int, int, int]], frozenset[Key], frozenset[Key], frozenset[Key]]:
    keys = list(required)
    rng.shuffle(keys)
    fast_count = EXPECTED_EVIDENCE_REGIMES["fast_change"]
    slow_count = EXPECTED_EVIDENCE_REGIMES["slow_change"]
    rumor_count = EXPECTED_EVIDENCE_REGIMES["recent_rumor"]
    stable_count = EXPECTED_EVIDENCE_REGIMES["stable_confirmation"]
    if fast_count + slow_count + rumor_count + stable_count > len(keys):
        raise ValueError("evidence regimes exceed required relation count")

    cursor = 0
    fast = frozenset(keys[cursor : cursor + fast_count])
    cursor += fast_count
    slow = frozenset(keys[cursor : cursor + slow_count])
    cursor += slow_count
    rumor = frozenset(keys[cursor : cursor + rumor_count])
    cursor += rumor_count
    stable = frozenset(keys[cursor : cursor + stable_count])

    specs: list[tuple[int, int, int, int]] = []
    for key, truth_object in required.items():
        subject, relation = key
        wrong = _wrong_object(rng, truth_object, config.entity_count)
        if key in fast:
            specs.extend(
                [
                    (subject, relation, wrong, 0),
                    (subject, relation, wrong, 1),
                    (subject, relation, truth_object, config.final_epoch),
                ]
            )
        elif key in slow:
            specs.extend(
                [
                    (subject, relation, wrong, 20),
                    (subject, relation, wrong, 21),
                    (subject, relation, truth_object, config.final_epoch),
                ]
            )
        elif key in rumor:
            specs.extend(
                [
                    (subject, relation, truth_object, 20),
                    (subject, relation, truth_object, 21),
                    (subject, relation, wrong, config.final_epoch),
                ]
            )
        elif key in stable:
            specs.extend(
                [
                    (subject, relation, truth_object, 35),
                    (subject, relation, truth_object, config.final_epoch),
                ]
            )
        else:
            specs.append((subject, relation, truth_object, config.final_epoch))
    return specs, fast, slow, rumor


def _fill_distractors(
    rng: random.Random,
    specs: list[tuple[int, int, int, int]],
    required: dict[Key, int],
    transfer_queries: tuple[Query, ...],
    truth: tuple[tuple[int, ...], ...],
    config: EpistemicSubstrateConfig,
) -> None:
    transfer_subjects = sorted({triple[0] for query in transfer_queries for triple in query.path})
    candidates = [
        (subject, relation)
        for subject in transfer_subjects
        for relation in range(config.relation_type_count)
        if (subject, relation) not in required
    ]
    rng.shuffle(candidates)
    fallback = [
        (subject, relation)
        for subject in range(config.entity_count)
        for relation in range(config.relation_type_count)
        if (subject, relation) not in required and (subject, relation) not in candidates
    ]
    rng.shuffle(fallback)
    candidates.extend(fallback)

    cursor = 0
    while len(specs) < config.relation_count:
        if cursor >= len(candidates):
            raise RuntimeError("not enough distractor keys to fill observation claims")
        subject, relation = candidates[cursor]
        cursor += 1
        specs.append((subject, relation, truth[relation][subject], config.final_epoch))
    if len(specs) > config.relation_count:
        raise ValueError("required evidence exceeds frozen observation-claim count")


def _packetize_and_assign(
    rng: random.Random,
    specs: list[tuple[int, int, int, int]],
    transfer_queries: tuple[Query, ...],
    config: EpistemicSubstrateConfig,
) -> tuple[tuple[Claim, ...], tuple[tuple[Claim, ...], ...]]:
    packet_size = config.relation_count // config.source_packet_count
    if packet_size * config.source_packet_count != config.relation_count:
        raise ValueError("relation_count must divide evenly into source packets")
    packets_per_agent = config.source_packet_count // config.agent_count
    if packets_per_agent * packet_size != config.observations_per_agent:
        raise ValueError("packet geometry does not match observations_per_agent")

    accepted_packets: list[list[tuple[int, int, int, int]]] | None = None
    accepted_producers: dict[int, int] | None = None
    for _ in range(10000):
        shuffled = list(specs)
        rng.shuffle(shuffled)
        packets = [
            shuffled[index : index + packet_size]
            for index in range(0, len(shuffled), packet_size)
        ]
        packet_order = list(range(config.source_packet_count))
        rng.shuffle(packet_order)
        producer_for_packet = {
            packet_id: position // packets_per_agent
            for position, packet_id in enumerate(packet_order)
        }
        producer_truth: dict[int, set[Triple]] = defaultdict(set)
        for packet_id, packet in enumerate(packets):
            producer_id = producer_for_packet[packet_id]
            for subject, relation, obj, _epoch in packet:
                producer_truth[producer_id].add((subject, relation, obj))
        if all(
            not any(set(query.path).issubset(triples) for triples in producer_truth.values())
            for query in transfer_queries
        ):
            accepted_packets = packets
            accepted_producers = producer_for_packet
            break
    if accepted_packets is None or accepted_producers is None:
        raise RuntimeError("unable to distribute transfer evidence across producers")

    claims: list[Claim] = []
    reports: list[list[Claim]] = [[] for _ in range(config.agent_count)]
    claim_id = 0
    for packet_id, packet in enumerate(accepted_packets):
        producer_id = accepted_producers[packet_id]
        for subject, relation, obj, epoch in packet:
            claim = Claim(claim_id, subject, relation, obj, epoch, producer_id, packet_id)
            claims.append(claim)
            reports[producer_id].append(claim)
            claim_id += 1
    for report in reports:
        report.sort(key=lambda claim: (claim.packet_id, claim.claim_id))
    return tuple(claims), tuple(tuple(report) for report in reports)


def generate_world(seed: int, config: EpistemicSubstrateConfig) -> World:
    rng = random.Random(seed)
    truth = _truth_maps(seed, config.entity_count, config.relation_type_count)
    transfer_queries = _make_transfer_queries(rng, config, truth)
    required = _required_keys(transfer_queries)
    specs, fast, slow, rumor = _claim_specs_for_required(rng, required, config)
    _fill_distractors(rng, specs, required, transfer_queries, truth, config)
    claims, reports = _packetize_and_assign(rng, specs, transfer_queries, config)

    discovery: list[Query] = []
    for index in range(config.discovery_query_count):
        transfer = transfer_queries[index % len(transfer_queries)]
        prefix_length = min(len(transfer.relations), 1 + index % len(transfer.relations))
        relations = transfer.relations[:prefix_length]
        target, path = _apply_relations(truth, transfer.source, relations)
        discovery.append(Query(index, transfer.source, relations, target, path))

    world = World(
        seed=seed,
        claims=claims,
        reports=reports,
        transfer_queries=transfer_queries,
        discovery_queries=tuple(discovery),
        truth=truth,
        fast_change=fast,
        slow_change=slow,
        rumor=rumor,
    )
    validate_world(world, config)
    return world


def validate_world(world: World, config: EpistemicSubstrateConfig) -> None:
    if len(world.claims) != config.relation_count:
        raise AssertionError("world observation-claim count changed")
    if len(world.reports) != config.agent_count:
        raise AssertionError("world producer count changed")
    if any(len(report) != config.observations_per_agent for report in world.reports):
        raise AssertionError("producer observation budget changed")
    if len(world.transfer_queries) != config.transfer_query_count:
        raise AssertionError("world transfer-query count changed")
    if len(world.discovery_queries) != config.discovery_query_count:
        raise AssertionError("world discovery-query count changed")

    for query in world.transfer_queries:
        holders = {
            claim.producer_id
            for triple in query.path
            for claim in world.claims
            if claim.triple == triple
        }
        if len(holders) < 2:
            raise AssertionError("transfer query does not require collective evidence")
        for report in world.reports:
            triples = {claim.triple for claim in report}
            if set(query.path).issubset(triples):
                raise AssertionError("one producer can solve a transfer query alone")


def _bridge_triples(claims: tuple[Claim, ...]) -> frozenset[Triple]:
    pair_to_triples: dict[tuple[int, int], set[Triple]] = defaultdict(set)
    graph: dict[int, set[int]] = defaultdict(set)
    for claim in claims:
        left, right = sorted((claim.subject, claim.object))
        if left == right:
            continue
        pair_to_triples[(left, right)].add(claim.triple)
        graph[left].add(right)
        graph[right].add(left)

    timer = 0
    discovery: dict[int, int] = {}
    low: dict[int, int] = {}
    bridges: set[tuple[int, int]] = set()

    def visit(node: int, parent: int | None) -> None:
        nonlocal timer
        timer += 1
        discovery[node] = timer
        low[node] = timer
        for neighbor in graph[node]:
            if neighbor == parent:
                continue
            if neighbor not in discovery:
                visit(neighbor, node)
                low[node] = min(low[node], low[neighbor])
                if low[neighbor] > discovery[node]:
                    bridges.add(tuple(sorted((node, neighbor))))
            else:
                low[node] = min(low[node], discovery[neighbor])

    for node in graph:
        if node not in discovery:
            visit(node, None)
    return frozenset(triple for pair in bridges for triple in pair_to_triples[pair])


def _activation(claims: tuple[Claim, ...], config: EpistemicSubstrateConfig) -> dict[int, float]:
    initial = float(EXPECTED_RESONANCE["initial_activation"])
    decay = float(EXPECTED_RESONANCE["decay_factor_per_epoch"])
    confirmation_gain = float(EXPECTED_RESONANCE["independent_confirmation_gain"])
    contradiction_gain = float(EXPECTED_RESONANCE["contradiction_gain"])
    bridge_gain = float(EXPECTED_RESONANCE["bridge_gain"])
    maximum = float(EXPECTED_RESONANCE["maximum_activation"])
    bridge_triples = _bridge_triples(claims)

    by_triple: dict[Triple, list[Claim]] = defaultdict(list)
    by_key: dict[Key, set[int]] = defaultdict(set)
    for claim in claims:
        by_triple[claim.triple].append(claim)
        by_key[claim.key].add(claim.object)

    activation: dict[int, float] = {}
    for triple, items in by_triple.items():
        ordered = sorted(items, key=lambda claim: (claim.epoch, claim.claim_id))
        value = initial
        last_epoch = ordered[0].epoch
        seen_producers = {ordered[0].producer_id}
        for claim in ordered[1:]:
            value *= decay ** max(0, claim.epoch - last_epoch)
            if claim.producer_id not in seen_producers:
                value += confirmation_gain
                seen_producers.add(claim.producer_id)
            last_epoch = claim.epoch
        value *= decay ** max(0, config.final_epoch - last_epoch)
        if len(by_key[(triple[0], triple[1])]) > 1:
            value += contradiction_gain
        if triple in bridge_triples:
            value += bridge_gain
        value = min(maximum, value)
        for claim in items:
            activation[claim.claim_id] = value
    return activation


def make_substrate(arm: str, world: World, config: EpistemicSubstrateConfig) -> Substrate:
    if arm == "pile":
        return PileSubstrate(world.reports, config.pile_claim_cost)
    if arm == "shared_memory":
        return SharedMemorySubstrate(world.claims, config.shared_claim_cost)
    if arm == "provenance_graph":
        return ProvenanceGraphSubstrate(world.claims, config.graph_claim_cost)
    if arm == "resonance_field":
        return ResonanceFieldSubstrate(
            world.claims,
            config.graph_claim_cost,
            _activation(world.claims, config),
            config.contradiction_override_margin,
        )
    raise ValueError(f"unknown substrate arm: {arm}")


def solve_query(query: Query, substrate: Substrate, config: EpistemicSubstrateConfig) -> QueryResult:
    current = query.source
    path: list[Triple] = []
    producers: set[int] = set()
    budget = config.max_retrieval_items_per_query
    spent = 0

    for relation in query.relations[: config.max_reasoning_steps_per_query]:
        retrieval = substrate.retrieve(current, relation, budget - spent)
        spent += retrieval.cost
        if not retrieval.complete or not retrieval.claims:
            return QueryResult(None, tuple(path), frozenset(producers), spent)
        chosen = substrate.choose(retrieval.claims)
        if chosen is None:
            return QueryResult(None, tuple(path), frozenset(producers), spent)
        path.append(chosen.triple)
        producers.add(chosen.producer_id)
        current = chosen.object
    return QueryResult(current, tuple(path), frozenset(producers), spent)


def _required_path_triples(world: World) -> frozenset[Triple]:
    return frozenset(triple for query in world.transfer_queries for triple in query.path)


def _coverage(world: World) -> float:
    required = _required_path_triples(world)
    deposited = {claim.triple for claim in world.claims}
    return len(required & deposited) / len(required) if required else 1.0


def _contradiction_keys(world: World) -> frozenset[Key]:
    by_key: dict[Key, set[int]] = defaultdict(set)
    for claim in world.claims:
        by_key[claim.key].add(claim.object)
    return frozenset(key for key, objects in by_key.items() if len(objects) > 1)


def _contradiction_f1(world: World, substrate: Substrate, config: EpistemicSubstrateConfig) -> float:
    keys = _contradiction_keys(world)
    if not keys:
        return 1.0
    tp = fp = fn = 0
    for subject, relation in keys:
        retrieval = substrate.retrieve(subject, relation, config.max_retrieval_items_per_query)
        chosen = substrate.choose(retrieval.claims) if retrieval.complete else None
        truth_object = world.truth[relation][subject]
        if chosen is None:
            fn += 1
        elif chosen.object == truth_object:
            tp += 1
        else:
            fp += 1
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def _diagnostic_retrievals(
    world: World,
    substrate: Substrate,
    config: EpistemicSubstrateConfig,
) -> tuple[list[int], int]:
    seen_ids: list[int] = []
    total_cost = 0
    for query in world.transfer_queries:
        current = query.source
        budget = config.max_retrieval_items_per_query
        spent = 0
        for relation in query.relations[: config.max_reasoning_steps_per_query]:
            retrieval = substrate.retrieve(current, relation, budget - spent)
            spent += retrieval.cost
            total_cost += retrieval.cost
            seen_ids.extend(claim.claim_id for claim in retrieval.claims)
            if not retrieval.complete or not retrieval.claims:
                break
            chosen = substrate.choose(retrieval.claims)
            if chosen is None:
                break
            current = chosen.object
    return seen_ids, total_cost


def evaluate_arm(world: World, arm: str, config: EpistemicSubstrateConfig) -> ArmMetrics:
    substrate = make_substrate(arm, world, config)
    results = [solve_query(query, substrate, config) for query in world.transfer_queries]
    total = len(results)
    correct = sum(
        result.predicted_target == query.target
        for query, result in zip(world.transfer_queries, results, strict=True)
    )
    collective = sum(
        result.predicted_target == query.target
        and result.path == query.path
        and len(result.producer_ids) >= 2
        for query, result in zip(world.transfer_queries, results, strict=True)
    )
    answered = sum(result.predicted_target is not None for result in results)
    wrong = sum(
        result.predicted_target is not None and result.predicted_target != query.target
        for query, result in zip(world.transfer_queries, results, strict=True)
    )

    bridge_truth = _bridge_triples(world.claims) & _required_path_triples(world)
    recovered = {
        triple
        for query, result in zip(world.transfer_queries, results, strict=True)
        if result.predicted_target == query.target
        for triple in result.path
    }
    bridge_recall = len(bridge_truth & recovered) / len(bridge_truth) if bridge_truth else 1.0

    seen_ids, diagnostic_cost = _diagnostic_retrievals(world, substrate, config)
    duplicate_work = 0.0
    if seen_ids:
        duplicate_work = 1.0 - len(set(seen_ids)) / len(seen_ids)
    average_cost = diagnostic_cost / total if total else 0.0
    coverage = _coverage(world)

    return ArmMetrics(
        arm=arm,
        transfer_accuracy=correct / total,
        collective_emergence_ratio=collective / total,
        evidence_coverage=coverage,
        contradiction_resolution_f1=_contradiction_f1(world, substrate, config),
        bridge_recall=bridge_recall,
        provenance_completeness=float(substrate.has_provenance),
        knowledge_survival_rate=coverage,
        duplicate_work_rate=duplicate_work,
        false_synthesis_rate=wrong / answered if answered else 0.0,
        retrieval_items_consumed=average_cost,
    )


def run_world(seed: int, config: EpistemicSubstrateConfig) -> tuple[ArmMetrics, ...]:
    world = generate_world(seed, config)
    ordered = sorted(config.experiments, key=lambda item: int(item[0]))
    return tuple(evaluate_arm(world, arm, config) for _experiment, arm in ordered)


__all__ = [
    "ArmMetrics",
    "Claim",
    "Query",
    "World",
    "evaluate_arm",
    "generate_world",
    "run_world",
    "solve_query",
    "validate_world",
]
