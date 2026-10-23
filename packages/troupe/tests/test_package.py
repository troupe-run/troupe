import json
import shutil
import subprocess
import zipfile
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


def test_the_built_wheel_carries_the_recorded_protocol_version_and_every_schema(
    tmp_path: Path,
) -> None:
    # An installed troupe has only what the wheel holds (spec: protocol, "An installed troupe").
    uv = shutil.which("uv")
    assert uv is not None, "uv isn't on PATH: run the tests with `uv run pytest`"
    subprocess.run(
        [uv, "build", "--package", "troupe", "--wheel", "--out-dir", str(tmp_path), "--quiet"],
        cwd=REPO,
        check=True,
        timeout=120,
    )
    [wheel] = tmp_path.glob("troupe-*.whl")
    copy = REPO / "packages" / "troupe" / "src" / "troupe" / "protocol"
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        record = json.loads(archive.read("troupe/protocol/version.json"))
    assert record == json.loads((copy / "version.json").read_bytes())
    schemas = {
        f"troupe/protocol/{p.relative_to(copy).as_posix()}" for p in copy.rglob("*.schema.json")
    }
    assert schemas
    assert schemas <= names
