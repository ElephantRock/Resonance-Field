# Experiments 142–145 — Provider Identity Probe Result

Date: 2026-08-12
Status: successful pre-confirmatory compatibility probe; no scientific treatment execution

## Frozen evidence

- Workflow run: `31642753502`
- Workflow: `LLM Epistemic Substrate 142-145 Provider Identity Probe`
- Trigger/head SHA: `a0bc74d8b163932e1b417dbad99122d5dcc815ee`
- Artifact ID: `9159514128`
- Artifact digest: `sha256:c56a57e94a57657054195960bb0bd556aadd504b7d6d2ba9e53a19babba4757a`
- Probe JSON SHA-256: `835bc51a029517d6d3f5271c5f0f0d98e286df79b486d64742517742c81d7581`
- Request-contract SHA-256: `739fba6b309308d0798003f7c1c6a5d9b859b8ad2c4d94fc3bdcd75a8f246acd`

Boundary evidence:

- `inferential: false`
- `confirmatory_access: false`
- `confirmatory_cases_evaluated: false`
- `treatment_execution: false`
- `scientific_content_access: false`

## Request identity

The frozen compatibility probe requested:

- provider: Z.AI;
- endpoint: `https://api.z.ai/api/coding/paas/v4`;
- protocol: OpenAI-compatible Chat Completions;
- requested model string: **`glm-5.1`**;
- temperature: `1.0`;
- thinking enabled with `clear_thinking: false`;
- JSON object structured output;
- SDK-internal retries disabled;
- explicit transient retry business codes 1302/1305.

## Served identity

The three synthetic request modes returned:

1. structured JSON call → **`glm-5.2`**;
2. forced function-call response → **`glm-5.2`**;
3. tool-free structured finalization → **`glm-5.2`**.

The provider-returned identity was therefore non-empty and byte-identical across the complete synthetic request surface.

**Sealed expected response-model identity for the confirmatory protocol: `glm-5.2`.**

The requested alias and served identity remain separate fields. The campaign continues to request `glm-5.1`; it does not rewrite the request to `glm-5.2` based on completion metadata.

## Enforcement

Every confirmatory completion must pass exact returned-model identity enforcement against `glm-5.2`, including:

- all producer responses and schema retries;
- evaluator tool-call responses;
- evaluator boundary-finalization responses;
- evaluator schema retries;
- all five independent evaluator draws per case/arm.

Any completion that returns a different identity, or omits the identity, is a provider-identity failure. The execution must stop under the existing seal; mixed identities may not be pooled and no model substitution is authorized.

Implementation support: `ModelIdentityEnforcingCompletions` in `src/resonance/experiments/llm_epistemic_zai_retry.py`.

## Probe payload

The exact probe payload recorded:

```json
{
  "confirmatory_access": false,
  "consistent_response_model": "glm-5.2",
  "forced_tool_call_ok": true,
  "probe_version": "zai-identity-probe-v1",
  "provider_base_url": "https://api.z.ai/api/coding/paas/v4",
  "request_contract_sha256": "739fba6b309308d0798003f7c1c6a5d9b859b8ad2c4d94fc3bdcd75a8f246acd",
  "requested_model": "glm-5.1",
  "response_models": ["glm-5.2", "glm-5.2", "glm-5.2"],
  "scientific_content_access": false,
  "structured_output_ok": true,
  "tool_finalization_ok": true,
  "treatment_execution": false
}
```

## Scientific status

This probe is provider-mechanical evidence only. It supplies no P/S/G/R observation, cannot be pooled with instrumentation outcomes, and does not access or expose any future confirmatory case.

The provider/model identity blocker is resolved for seal preparation. Confirmatory corpus construction remains blocked by the case-strata/source-allocation/scoring/seal-policy work still outstanding.
