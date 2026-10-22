import os
from pathlib import Path
import subprocess
import sys

import pytest

from colcon_worktree.package_selection import owners

GIT = [
    "git",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "user.name=t",
    "-c",
    "user.email=t@t",
    "-c",
    "commit.gpgsign=false",
]
PKG = """<?xml version="1.0"?>
<package format="3"><name>{name}</name><version>0.0.0</version>
<description>d</description><maintainer email="t@example.com">t</maintainer>
<license>MIT</license>{deps}
<export><build_type>ament_cmake</build_type></export></package>
"""


def _pkg(root, name, *deps):
    d = root / "src" / name
    d.mkdir(parents=True)
    (d / "package.xml").write_text(
        PKG.format(name=name, deps="".join(f"<depend>{x}</depend>" for x in deps))
    )
    (d / "CMakeLists.txt").touch()


def colcon_list(cwd, *extra, underlay=None):
    env = dict(os.environ)
    if underlay is not None:
        env["AMENT_PREFIX_PATH"] = str(underlay)
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from colcon_core.command import main; "
            "sys.exit(main(argv=sys.argv[1:]))",
            "list",
            "-n",
            "--worktree-changed",
            *extra,
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.split())


@pytest.fixture
def ws(tmp_path):
    main, wt = tmp_path / "main", tmp_path / "wt"
    subprocess.run([*GIT, "init", "-q", str(main)], check=True)
    _pkg(main, "a")
    _pkg(main, "b", "a")
    _pkg(main, "a_msgs")
    subprocess.run([*GIT, "add", "."], cwd=main, check=True)
    subprocess.run([*GIT, "commit", "-qm", "init"], cwd=main, check=True)
    subprocess.run([*GIT, "worktree", "add", "-q", str(wt)], cwd=main, check=True)
    (main / "install").mkdir()
    return main.resolve(), wt.resolve()


def test_main_checkout_is_noop(ws):
    main, _ = ws
    assert colcon_list(main) == {"a", "b", "a_msgs"}


def test_unchanged_worktree_selects_nothing(ws):
    main, wt = ws
    assert colcon_list(wt, underlay=main / "install") == set()


def test_change_selects_package_and_dependents(ws):
    main, wt = ws
    (wt / "src" / "a" / "CMakeLists.txt").write_text("# x\n")
    assert colcon_list(wt, underlay=main / "install") == {"a", "b"}


def test_path_boundary_and_untracked(ws):
    main, wt = ws
    (wt / "src" / "a_msgs" / "X.msg").touch()
    assert colcon_list(wt, underlay=main / "install") == {"a_msgs"}


def test_built_from_stamp_is_the_base(ws):
    main, wt = ws
    (wt / "src" / "a_msgs" / "f").write_text("1\n")
    subprocess.run([*GIT, "add", "."], cwd=wt, check=True)
    subprocess.run([*GIT, "commit", "-qm", "c"], cwd=wt, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True
    ).stdout
    (main / "install" / ".built_from").write_text(head)
    assert colcon_list(wt, underlay=main / "install") == set()


def test_other_selection_args_compose(ws):
    main, wt = ws
    (wt / "src" / "a" / "CMakeLists.txt").write_text("# x\n")
    got = colcon_list(wt, "--packages-skip", "b", underlay=main / "install")
    assert got == {"a"}


def test_flag_absent_is_inert(ws):
    _, wt = ws
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from colcon_core.command import main; "
            'sys.exit(main(argv=["list", "-n"]))',
        ],
        cwd=wt,
        capture_output=True,
        text=True,
        check=True,
    )
    assert set(out.stdout.split()) == {"a", "b", "a_msgs"}


@pytest.mark.parametrize(
    "files, expected",
    [
        ([], set()),
        (["src/a/file.cpp"], {"a", "alias"}),
        (["src/a"], {"a", "alias", "nested"}),
        (["src/a/nested/file.cpp"], {"a", "alias", "nested"}),
        (["src"], {"a", "alias", "nested", "a_msgs"}),
        (["src/a_msgs/file.msg"], {"a_msgs"}),
        (["src/ab/file.cpp", "README.md"], set()),
        (["src/a/file.cpp", "src/a/file.cpp", "src/a_msgs"],
         {"a", "alias", "a_msgs"}),
    ],
)
def test_owners_preserves_path_relationships(tmp_path, files, expected):
    pkgs = {
        "a": tmp_path / "src/a",
        "alias": tmp_path / "src/a",
        "nested": tmp_path / "src/a/nested",
        "a_msgs": tmp_path / "src/a_msgs",
    }
    assert owners([tmp_path / f for f in files], pkgs) == expected


def test_owners_matches_pairwise_reference():
    paths = [Path(p) for p in (".", "src", "src/a", "src/ab", "src/a/b", "/src/a")]
    pkgs = {str(i): path for i, path in enumerate(paths)}
    for path in [*paths, Path("src/a/b/file"), Path("/src/a/file")]:
        expected = {
            name for name, root in pkgs.items()
            if path.is_relative_to(root) or root.is_relative_to(path)
        }
        assert owners([path], pkgs) == expected
    assert owners(paths, {}) == set()


def test_new_untracked_package_selects_dependents(ws):
    main, wt = ws
    _pkg(wt, "new", "a")
    _pkg(wt, "consumer", "new")
    assert colcon_list(wt, underlay=main / "install") == {"new", "consumer"}


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__)), "-q"]))
