class RaisingLock:
    def __enter__(self):
        raise AssertionError("read-only contract access should not take env lock")

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_workflow_execution_contract_is_lock_free(test_env):
    test_env._operation_lock = RaisingLock()

    assert test_env.get_workflow_execution_contract("missing") is None
