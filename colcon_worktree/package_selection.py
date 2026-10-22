import os
from pathlib import Path
import subprocess
import sys

from colcon_core.package_selection import logger
from colcon_core.package_selection import PackageSelectionExtensionPoint
from colcon_core.plugin_system import satisfies_version

BUILT_FROM = Path("install") / ".built_from"


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def main_checkout(repo):
    """Return the main checkout when `repo` is a linked worktree, else None."""
    try:
        common, gitdir = (
            Path(_git(repo, "rev-parse", "--path-format=absolute", flag))
            for flag in ("--git-common-dir", "--git-dir")
        )
        return None if common == gitdir else common.parent
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def diff_base(repo, main):
    stamp = main / BUILT_FROM
    if stamp.exists():
        return stamp.read_text().strip()
    logger.warning(
        f"{stamp} is missing; diffing against the merge-base with main's HEAD"
    )
    return _git(repo, "merge-base", "HEAD", _git(main, "rev-parse", "HEAD"))


def changed_files(top, base):
    names = (
        _git(top, "diff", "--name-only", base).splitlines()
        + _git(top, "ls-files", "--others", "--exclude-standard").splitlines()
    )
    return [top / n for n in names]


def owners(files, pkgs):
    # A changed path above a package is a submodule gitlink (or a dirty one).
    return {
        name
        for name, p in pkgs.items()
        for f in files
        if f.is_relative_to(p) or p.is_relative_to(f)
    }


def underlay_sourced(main):
    install = str((main / "install").resolve())
    return any(
        install in os.environ.get(var, "").split(os.pathsep)
        for var in ("COLCON_PREFIX_PATH", "AMENT_PREFIX_PATH")
    )


class WorktreePackageSelection(PackageSelectionExtensionPoint):
    """Select packages changed in a worktree since main's install."""

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(
            PackageSelectionExtensionPoint.EXTENSION_POINT_VERSION, "^1.0"
        )

    def add_arguments(self, *, parser):  # noqa: D102
        parser.add_argument(
            "--worktree-changed",
            action="store_true",
            help="In a linked git worktree, only process packages changed "
            "since the main checkout's install (install/.built_from, "
            "else the merge-base) and packages which recursively "
            "depend on them; overriding them is allowed. No-op in the "
            "main checkout",
        )

    def select_packages(self, *, args, decorators):  # noqa: D102
        if not getattr(args, "worktree_changed", False):
            return
        repo = Path.cwd()
        main = main_checkout(repo)
        if main is None:
            logger.info("--worktree-changed: not a linked worktree, no-op")
            return

        top = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
        base = diff_base(repo, main)
        pkgs = {
            d.descriptor.name: Path(d.descriptor.path).resolve() for d in decorators
        }
        changed = owners(changed_files(top, base), pkgs)
        print(
            f"worktree: changed since {base[:10]}: "
            f"{' '.join(sorted(changed)) or 'nothing'}",
            file=sys.stderr,
        )

        deselected = False
        for d in decorators:
            name = d.descriptor.name
            if name in changed or changed & set(d.recursive_dependencies):
                continue
            if d.selected:
                logger.info(f"Skipping package '{name}' in '{d.descriptor.path}'")
                d.selected = False
                deselected = True

        if hasattr(args, "allow_overriding"):
            args.allow_overriding.extend(sorted(changed - set(args.allow_overriding)))

        if deselected and not underlay_sourced(main):
            msg = (
                f"--worktree-changed skipped packages, but {main / 'install'} "
                "is not sourced: their dependents will not find them. Run "
                f"`source {main / 'install' / 'setup.bash'}` first"
            )
            if getattr(args, "verb_name", None) == "build":
                sys.exit(msg)
            logger.warning(msg)
