from schemas.state_schema import (
    IterationOracleRecord, IterationRevision, IterationsState, WorkspaceState,
)


def test_iteration_record_defaults():
    r = IterationOracleRecord(
        iteration_index=1, code_file="x.py", sim_passed=True,
        cq=27.4, regime_label="clean", raw_record_path=None,
    )
    assert r.iteration_index == 1


def test_iterations_state_disabled_by_default():
    s = IterationsState()
    assert s.enabled is False
    assert s.iterations_completed == 0
    assert s.records == [] and s.revisions == []


def test_workspace_state_accepts_iteration_status():
    WorkspaceState(
        task_id="t", mode="wet_lab", user_input="x", status="iteration",
    )


def test_workspace_state_has_iterations_field():
    s = WorkspaceState(
        task_id="t", mode="wet_lab", user_input="x", status="research",
    )
    assert isinstance(s.iterations, IterationsState)
