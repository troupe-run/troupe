from importlib.metadata import version
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_installed_version_is_the_one_in_pyproject() -> None:
    pyproject = (REPO / "packages" / "troupe" / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{version("troupe")}"' in pyproject


def test_package_licence_text_is_identical_to_the_repo_licence_text() -> None:
    # Text, not bytes: a checkout made before .gitattributes existed can hold one copy with CRLF
    # line endings, and line endings aren't what this test protects.
    package = (REPO / "packages" / "troupe" / "LICENSE").read_text(encoding="utf-8")
    assert package == (REPO / "LICENSE").read_text(encoding="utf-8")
