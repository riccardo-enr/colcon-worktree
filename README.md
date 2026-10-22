# colcon-worktree

A colcon package-selection extension for building a ROS 2 workspace from a
linked `git worktree` against the main checkout's `install/` as an underlay.

```
main checkout                         linked worktree
  src/  --colcon build-->  install/     src/ (edited a)
              |                          |
              +--> install/.built_from   +--> colcon build --worktree-changed
                     (commit built)            = a + its dependents only,
                                                 --allow-overriding a,
                                                 everything else from main
```

`--worktree-changed` selects the packages whose files changed since the commit
main's install was built from (`install/.built_from`, falling back to the
merge-base with main's HEAD), plus every package that recursively depends on
them. Untracked files count, and a changed submodule gitlink selects the
packages under it. The selected names are added to `--allow-overriding`.

It is a no-op in the main checkout and inert without the flag.

## Use

```
source <main>/install/setup.bash        # main's install is the underlay
cd <main>/.claude/worktrees/<wt>
colcon build --symlink-install --worktree-changed
```

`colcon build --worktree-changed` exits early if main's install is not
sourced, since the skipped packages would otherwise surface as a CMake
`find_package` error.

Writing `install/.built_from` after a clean full build in main is the
caller's job (see `scripts/dev/build.py` in hkust-fuel-ipp-ros2).

## Install

colcon loads extensions from the Python it runs on (system `/usr/bin/python3`
for apt colcon), so install there:

```
pip install --user --break-system-packages -e .
```

## Test

Against the system colcon, in a throwaway venv:

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```
