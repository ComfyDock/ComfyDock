from comfygit_core.models.workflow_contract import WorkflowContractInput


def test_workflow_contract_input_persists_string_ui_control() -> None:
    contract_input = WorkflowContractInput(
        name="prompt",
        type="string",
        node_id="6",
        required=True,
        ui_control="textarea",
    )

    assert contract_input.to_dict()["ui_control"] == "textarea"
    assert contract_input.to_toml_dict()["ui_control"] == "textarea"
    assert WorkflowContractInput.from_toml_dict(contract_input.to_toml_dict()).ui_control == "textarea"


def test_workflow_contract_input_ignores_unknown_ui_control() -> None:
    contract_input = WorkflowContractInput.from_toml_dict(
        {
            "name": "prompt",
            "type": "string",
            "node_id": "6",
            "required": True,
            "ui_control": "wide",
        }
    )

    assert contract_input.ui_control is None


def test_workflow_contract_input_persists_numeric_step() -> None:
    contract_input = WorkflowContractInput(
        name="cfg",
        type="number",
        node_id="6",
        required=True,
        min=0,
        max=20,
        step=0.25,
    )

    assert contract_input.to_dict()["step"] == 0.25
    assert contract_input.to_toml_dict()["step"] == 0.25
    assert WorkflowContractInput.from_toml_dict(contract_input.to_toml_dict()).step == 0.25


def test_workflow_contract_input_ignores_non_positive_numeric_step() -> None:
    contract_input = WorkflowContractInput.from_toml_dict(
        {
            "name": "steps",
            "type": "integer",
            "node_id": "6",
            "required": True,
            "step": 0,
        }
    )

    assert contract_input.step is None
