import os
from pathlib import Path

import pytest

from codeforge.config import load_env_files

# Same config sources as the console: shell, then .env.local, then .env.
load_env_files(Path(__file__).parents[1])


def pytest_collection_modifyitems(config, items):
    if os.environ.get("GROQ_API_KEY"):
        return
    skip = pytest.mark.skip(reason="GROQ_API_KEY not set")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)
