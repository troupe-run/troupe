from importlib.metadata import version
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_installed_version_is_the_one_in_pyproject() -> None:
    pyproject = (REPO / "packages" / "troupe" / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{version("troupe")}"' in pyproject


def test_package_licence_is_identical_to_the_repo_licence() -> None:
    package = (REPO / "packages" / "troupe" / "LICENSE").read_bytes()
    assert package == (REPO / "LICENSE").read_bytes()
