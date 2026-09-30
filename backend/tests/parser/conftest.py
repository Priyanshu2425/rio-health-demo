import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LLM") == "1":
        return
    skip = pytest.mark.skip(reason="calls OpenRouter; set RUN_LLM=1 to run")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)
