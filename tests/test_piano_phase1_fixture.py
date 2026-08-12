from resonance.experiments.piano_phase1_fixture import run_fixture


def test_fixture_exports_paired_non_scientific_contract_records() -> None:
    control = run_fixture("control")
    treatment = run_fixture("treatment")

    assert control["scientific_claim_allowed"] is False
    assert treatment["scientific_claim_allowed"] is False
    assert len(control["records"]) == len(treatment["records"]) == 3

    first_control = control["records"][0]
    assert first_control["intended_action"] == "OBSERVE"
    assert first_control["speech_action"] == "REQUEST_TOOL"
    assert first_control["action"] == "OBSERVE"

    rejected_control = control["records"][2]
    assert rejected_control["speech_claims_success"] is True
    assert rejected_control["acknowledgement"]["grounded_success"] is False
    assert rejected_control["acknowledgement"]["outcome_status"] == "rejected"

    for record in treatment["records"]:
        assert record["intended_action"] == record["speech_action"] == record["action"]
        assert record["speech_claims_success"] is False
        assert record["acknowledgement"]["grounded_success"] is True
