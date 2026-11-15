import tomllib
from pathlib import Path


def test_pytest_is_a_runtime_dependency():
    # The sandbox runs `python -m pytest`; without it every Run would report TESTS FAILED.
    project = tomllib.loads(Path(__file__).parents[2].joinpath("pyproject.toml").read_text())["project"]
    assert any(dep.split("[")[0].split(">")[0].split("=")[0].strip() == "pytest"
               for dep in project["dependencies"])
