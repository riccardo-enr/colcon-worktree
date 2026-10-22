# colcon-worktree

A [colcon](https://colcon.readthedocs.io) package-selection extension that
builds a ROS 2 workspace from a linked `git worktree` by rebuilding only what
changed. Every other package comes from the main checkout's `install/`, which
you use as an underlay.

## Why

`git worktree` gives you several checkouts of one repository: a feature
branch, a review, a bisect, each in its own directory. In a colcon workspace
each new worktree starts with no `build/` or `install/`, so a plain
`colcon build` there rebuilds the whole workspace from scratch. That costs the
same as a full build, even when the branch touches one package.

The main checkout has usually built all of those packages already. This
extension gives colcon a `--worktree-changed` flag. In a linked worktree the
flag selects only the packages whose files differ from what main's `install/`
was built from, plus every package that depends on them. Everything else is
found in main's install through the normal underlay mechanism.

```
main checkout                         linked worktree
  src/  --colcon build-->  install/     src/ (edited a)
              |                          |
              +--> install/.built_from   +--> colcon build --worktree-changed
                     (commit built)            = a + its dependents only,
                                                 --allow-overriding a,
                                                 everything else from main
```

## Prerequisites

- Python >= 3.10
- `colcon-core` >= 0.12 (the usual ROS 2 `colcon` install provides it)
- `git` on `PATH`, with support for `git rev-parse --path-format=absolute`
- A main checkout (a normal, non-bare clone) whose `install/` holds a full
  build of the workspace. The colcon workspace root must be the git
  repository root, because the extension looks for `<repo root>/install`.
- `build/`, `install/` and `log/` listed in `.gitignore`. Otherwise the
  clean-source check below never passes, and build artifacts in the worktree
  count as untracked changes.

## Installation

Install from source.

colcon loads extensions from the Python interpreter it runs on, so install
the package into that interpreter. To find it, read the shebang of the
`colcon` script:

```
head -1 "$(command -v colcon)"
```

For colcon installed from apt (`/usr/bin/python3`), a user install works.
`--break-system-packages` is needed on distributions that mark the system
Python as externally managed (PEP 668), for example Ubuntu 24.04:

```
git clone https://github.com/riccardo-enr/colcon-worktree.git
cd colcon-worktree
/usr/bin/python3 -m pip install --user --break-system-packages -e .
```

If colcon runs from a venv or another environment, run `pip install -e .`
with that environment's `pip` instead.

Check that colcon sees the flag:

```
colcon build --help | grep -- --worktree-changed
```

## Usage

### 1. Build main and record what was built

In the main checkout, run a full build, then write the built commit to
`install/.built_from`. Write the stamp only when the build succeeded **and**
the source was clean and committed. A stamp that names a commit the install
was not really built from makes the worktree diff against the wrong base.
Keep main's source and HEAD unchanged throughout the build.

```
cd <main>
rm -f install/.built_from \
  && git diff --quiet HEAD \
  && test -z "$(git ls-files --others --exclude-standard)" \
  && colcon build --symlink-install \
  && git rev-parse HEAD > install/.built_from
```

The extension only reads the stamp. Nothing in it writes or refreshes the
stamp, so put this step wherever you run your full main builds. Repeat it
each time you rebuild main.

### 2. Build in a worktree

```
cd <main>
git worktree add ../ws-feature -b feature

source <main>/install/setup.bash     # main's install is the underlay
cd ../ws-feature
git submodule update --init          # only if the repo has submodules
colcon build --symlink-install --worktree-changed
source install/setup.bash            # use the overlay
```

The worktree gets its own `build/`, `install/` and `log/`, which hold only
the selected packages. On every build the extension prints the base and the
directly changed packages to stderr, for example:

```
worktree: changed since 1a2b3c4d5e: my_pkg
```

Run colcon from the worktree root. The extension finds the repository from
the current directory.

`git worktree add` does not populate submodules. colcon does not discover
packages under an uninitialized submodule, so a changed gitlink there
selects nothing, and the old copy in main's install is used without a
warning. `git submodule update --init --reference <main>/<path> <path>`
avoids a network clone.

## How selection works

1. **Detect the worktree.** If `git rev-parse --git-dir` and
   `--git-common-dir` match, the directory is the main checkout (or a
   standalone clone), and the flag does nothing. Without `--worktree-changed`
   the extension does nothing either.
2. **Pick the base commit.** The extension reads `<main>/install/.built_from`.
   If the stamp is missing, it logs a warning and uses
   `git merge-base HEAD <main HEAD>`.
3. **List changed files.** These are the files that `git diff --name-only <base>`
   reports (committed, staged and unstaged changes, deletions included),
   plus untracked files that `.gitignore` does not exclude
   (`git ls-files --others --exclude-standard`).
4. **Map files to packages.** A file selects the package whose directory
   contains it. Paths are compared by component, so a change in `src/a_msgs`
   does not select `src/a`. A changed path that is a directory, which is
   how a submodule gitlink shows up in the diff, selects every package
   below it.
5. **Add dependents.** Every package that recursively depends on a changed
   package stays selected. All other packages are deselected.
6. **Allow overriding.** The directly changed packages are appended to
   `--allow-overriding`, so colcon does not warn that they shadow the same
   packages in main's install. Dependents are not added.
7. **Check the underlay.** If any package was deselected and `<main>/install`
   is in neither `COLCON_PREFIX_PATH` nor `AMENT_PREFIX_PATH`, `colcon build`
   exits with an error that names the `setup.bash` to source. Without this
   check the failure would surface later as a CMake `find_package` error.
   Other verbs, such as `colcon list` or `colcon test`, only log a warning.

A new package that exists only as untracked files is selected, together with
the packages that depend on it.

### Interaction with other selection flags

`--worktree-changed` only deselects packages. It never re-selects one, so it
combines with the other colcon selection flags as an intersection:

```
colcon build --worktree-changed --packages-skip slow_pkg
colcon build --worktree-changed --packages-up-to my_node
```

Dependents are computed over the whole workspace, not only over the packages
that the other flags leave selected. A package named in `--packages-select`
that did not change and does not depend on a changed package is not built.

To inspect the selection without building:

```
colcon list -n --worktree-changed
```

## Troubleshooting

**`--worktree-changed skipped packages, but <main>/install is not sourced`**
Run `source <main>/install/setup.bash` in this shell, then build again. The
check compares the resolved path of `<main>/install` with the entries of
`COLCON_PREFIX_PATH` and `AMENT_PREFIX_PATH`. If you sourced main through a
symlinked path, the entries do not match. Source it through the real path.

**`install/.built_from is missing; diffing against the merge-base ...`**
Main's install has no stamp, so the base is the merge-base with main's
*current* HEAD. If main's HEAD has moved since its last build, the base is
newer than the install. Packages changed between the two commits are then
not selected, and they build against stale versions from the underlay.
Rebuild main and write the stamp (step 1).

**Stale stamp.** The stamp is trusted as written. If main's `install/` was
rebuilt without a stamp update, or the stamp survived a failed build,
selection is computed against the wrong commit. Delete the stamp before each
main build and write it again only after a clean, successful build.

**Stamp names an unknown commit.** If the commit in `.built_from` does not
exist in the repository (for example after a rebase and `git gc`),
`git diff` fails and colcon reports the error. Rebuild main and write the
stamp again.

**Nothing selected.** `worktree: changed since <sha>: nothing` means that
no changed file falls inside a discovered package. The worktree can still
differ from the base outside package directories (see Limitations). Compare
`git rev-parse HEAD` in the worktree with the stamp, and check
`git diff --stat <sha>`.

## Limitations

- **Main's install must match a commit.** If main was built from a dirty
  tree, no commit describes its install, and no stamp can be correct.
  Uncommitted edits in the main checkout are invisible to the worktree's
  diff. With `--symlink-install`, files in main's install (Python, launch,
  config) link back into main's `src/`. Editing main or switching its branch
  then changes the underlay while the stamp stays the same.
- **Submodule precision.** The diff runs in the superproject. Any change
  inside a submodule, such as a new submodule commit or (depending on your
  git submodule `ignore` settings) a dirty submodule work tree, appears as
  the gitlink path. That path selects every package under the submodule,
  not only the one that changed. Untracked files inside a submodule are not
  listed one by one.
- **Removed packages are not tracked.** A package deleted in the worktree
  is not selected, because it no longer exists. The copy in main's install
  stays visible through the underlay.
- **Changes outside package directories select nothing.** This includes a
  top-level `README.md`, but also shared CMake modules or a `colcon.meta`
  at the repository root. Packages that use them are not rebuilt.

## Performance

Selection runs a handful of git commands: several `rev-parse` metadata
queries, one `git diff`, one `git ls-files`, and a `merge-base` when the
stamp is missing. The file-to-package mapping indexes every package directory
and its parent directories once, then walks the parent directories of each
changed file. This avoids comparing every changed file with every package.
It does not change how fast colcon builds the packages it selects. The time
saved on a worktree build depends on how few packages the selection leaves.

## Testing

The tests run real `colcon list` calls against temporary git repositories
and worktrees. Use a venv that can see the system colcon:

```
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```

Once the test dependencies are installed, rerun only the last command. If
unrelated ROS pytest plugins interfere with collection, set
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` when running pytest.
