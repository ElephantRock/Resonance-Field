["mode"]),
            entity_count=int(benchmark["entity_count"]),
            relation_count=int(benchmark["relation_count"]),
            relation_count_semantics=str(benchmark["relation_count_semantics"]),
            relation_type_count=int(benchmark["relation_type_count"]),
            source_packet_count=int(benchmark["source_packet_count"]),
            agent_count=int(benchmark["agent_count"]),
            observations_per_agent=int(benchmark["observations_per_agent"]),
            discovery_query_count=int(benchmark["discovery_query_count"]),
            transfer_query_count=int(benchmark["transfer_query_count"]),
            transfer_path_hops=_int_tuple(benchmark["transfer_path_hops"], "transfer_path_hops"),
            final_epoch=int(benchmark["final_epoch"]),
            evidence_regimes_canonical=_canonical(evidence_regimes),
            producer_memory_destroyed_before_transfer=bool(
                benchmark["producer_memory_destroyed_before_transfer"]
            ),
            max_substrate_writes_per_agent=int(budget["max_substrate_writes_per_agent"]),
            max_retrieval_items_per_query=int(budget["max_retrieval_items_per_query"]),
            pile_claim_cost=int(budget["pile_claim_cost"]),
            shared_claim_cost=int(budget["shared_claim_cost"]),
            graph_claim_cost=int(budget["graph_claim_cost"]),
            max_graph_hops_per_query=int(budget["max_graph_hops_per_query"]),
            max_reasoning_steps_per_query=int(budget["max_reasoning_steps_per_query"]),
            arms_canonical=_canonical(arms),
            resonance_canonical=_canonical(resonance),
            contradiction_override_margin=float(resonance["contradiction_override_margin"]),
            primary_endpoints=tuple(str(item) for item in raw_endpoints),
            confirmatory_contrasts=tuple(contrasts),
            paired_by_world_seed=bool(analysis["paired_by_world_seed"]),
            multiple_testing=str(analysis["multiple_testing"]),
            alpha=float(analysis["alpha"]),
            confidence_interval=float(analysis["confidence_interval"]),
            bootstrap_resamples=int(analysis["bootstrap_resamples"]),
            minimum_total_effect_transfer_accuracy=float(
                analysis["minimum_total_effect_transfer_accuracy"]
            ),
            minimum_total_effect_collective_emergence_ratio=float(
                analysis["minimum_total_effect_collective_emergence_ratio"]
            ),
            identical_worlds_required=bool(gates["require_identical_worlds_across_arms"]),
            identical_observations_required=bool(
                gates["require_identical_agent_observations_across_arms"]
            ),
            identical_queries_required=bool(gates["require_identical_query_sets_across_arms"]),
            identical_budgets_required=bool(gates["require_identical_budgets_across_arms"]),
            no_cross_arm_leakage_required=bool(gates["require_no_cross_arm_state_leakage"]),
            maximum_false_synthesis_rate=float(gates["maximum_false_synthesis_rate"]),
            maximum_provenance_loss_graph_arms=float(
                gates["maximum_provenance_loss_graph_arms"]
            ),
            instrumentation_seeds=_int_tuple(value["instrumentation_seeds"], "instrumentation_seeds"),
            confirmatory_seeds=_int_tuple(value["confirmatory_seeds"], "confirmatory_seeds"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.name != "epistemic-substrate-138-141-v0.1":
            raise ValueError("epistemic-substrate campaign name changed")
        if dict(self.experiments) != EXPECTED_EXPERIMENTS:
            raise ValueError("experiment-to-arm assignment changed")
        if self.arms_canonical != _canonical(EXPECTED_ARMS):
            raise ValueError("substrate arm semantics changed")
        if self.evidence_regimes_canonical != _canonical(EXPECTED_EVIDENCE_REGIMES):
            raise ValueError("evidence regime mixture changed")
        if self.resonance_canonical != _canonical(EXPECTED_RESONANCE):
            raise ValueError("resonance dynamics changed")
        if self.benchmark_mode != "deterministic_relational_world":
            raise ValueError("benchmark mode changed")
        if self.relation_count_semantics != "observation_claims":
            raise ValueError("relation count semantics changed")
        if (
            self.entity_count,
            self.relation_count,
            self.relation_type_count,
            self.source_packet_count,
            self.agent_count,
            self.observations_per_agent,
            self.final_epoch,
        ) != (96, 192, 4, 64, 32, 6, 40):
            raise ValueError("benchmark population or evidence geometry changed")
        if (self.discovery_query_count, self.transfer_query_count) != (24, 32):
            raise ValueError("query counts changed")
        if self.transfer_path_hops != (2, 3, 4):
            raise ValueError("transfer path-depth schedule changed")
        if not self.producer_memory_destroyed_before_transfer:
            raise ValueError("producer memory must be destroyed before transfer")
        if (
            self.max_substrate_writes_per_agent,
            self.max_retrieval_items_per_query,
            self.pile_claim_cost,
            self.shared_claim_cost,
            self.graph_claim_cost,
            self.max_graph_hops_per_query,
            self.max_reasoning_steps_per_query,
        ) != (6, 12, 3, 1, 1, 4, 8):
            raise ValueError("cross-arm budget or representation costs changed")
        if self.contradiction_override_margin != 0.60:
            raise ValueError("contradiction override margin changed")
        if self.primary_endpoints != EXPECTED_PRIMARY_ENDPOINTS:
            raise ValueError("primary endpoints changed")
        if self.confirmatory_contrasts != EXPECTED_CONFIRMATORY_CONTRASTS:
            raise ValueError("confirmatory contrast set changed")
        if (
            not self.paired_by_world_seed
            or self.multiple_testing != "holm"
            or self.alpha != 0.05
            or self.confidence_interval != 0.95
            or self.bootstrap_resamples != 10000
        ):
            raise ValueError("confirmatory analysis settings changed")
        if (
            self.minimum_total_effect_transfer_accuracy,
            self.minimum_total_effect_collective_emergence_ratio,
        ) != (0.10, 0.10):
            raise ValueError("minimum total-effect gates changed")
        if not all(
            (
                self.identical_worlds_required,
                self.identical_observations_required,
                self.identical_queries_required,
                self.identical_budgets_required,
                self.no_cross_arm_leakage_required,
            )
        ):
            raise ValueError("cross-arm identity gates changed")
        if (self.maximum_false_synthesis_rate, self.maximum_provenance_loss_graph_arms) != (
            0.05,
            0.01,
        ):
            raise ValueError("quality gates changed")
        if len(self.instrumentation_seeds) != 8 or len(self.confirmatory_seeds) != 64:
            raise ValueError("cohort sizes changed")
        flat = self.instrumentation_seeds + self.confirmatory_seeds
        if len(flat) != len(set(flat)):
            raise ValueError("instrumentation and confirmatory seeds must be disjoint")


def load_epistemic_substrate_config(
    path: str | Path,
) -> tuple[EpistemicSubstrateConfig, str]:
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("epistemic-substrate config must be a JSON object")
    config = EpistemicSubstrateConfig.from_mapping(value)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return config, hashlib.sha256(canonical).hexdigest()


__all__ = ["EpistemicSubstrateConfig", "load_epistemic_substrate_config"]