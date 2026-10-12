import pytest


def pytest_collection_modifyitems(items):
    suites = {
        "test_api_regression.py": ("integration", "contract", "services"),
        "test_live_services.py": ("integration", "services"),
        "test_graph_flow.py": ("integration",),
        "test_api_contract.py": ("unit", "contract"),
    }
    for item in items:
        for name in suites.get(item.path.name, ("unit",)):
            item.add_marker(getattr(pytest.mark, name))
