# Release checklist (contributors)

Run these checks against the intended release commit. This is a verification
checklist, not a statement that work in progress has been implemented.

- [ ] Full pytest passes on Python 3.11 and 3.12 using the committed `uv.lock`.
- [ ] Ruff lint, Ruff format and Mypy pass.
- [ ] Both sdist and wheel build successfully.
- [ ] Clean-wheel metadata, CLI help, snapshot and self-check pass on both CI Python versions.
- [ ] v1 golden fixtures are unchanged; any intentional compatibility change is reviewed.
- [ ] v2 golden fixtures reflect the code being released.
- [ ] README support claims match the code and its runtime gates.
- [ ] Public dependency ranges match the runtime gates; a locked smoke run alone
      does not establish compatibility with every version in those ranges.
- [ ] No `fastapi-contract-dev` reference appears in public distribution metadata
      (including its README description); repository URLs use `Ryota-Di/fastapi-contract`.
- [ ] Release tag, project version and built distribution versions agree.
- [ ] Push the release tag only after all checks are green; the tag triggers PyPI publishing.

## Local reproduction

Use uv 0.12.7, as pinned in CI. From the repository root:

```sh
uv sync --locked --group dev --python 3.11
uv run --locked --python 3.11 pytest
uv sync --locked --group dev --python 3.12
uv run --locked --python 3.12 pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src

uv build --python 3.12 --build-constraints tools/release/build-constraints.txt --require-hashes
uv run --no-project --python 3.11 python tools/release/check_wheel.py
uv run --no-project --python 3.12 python tools/release/check_wheel.py
```

Use a fresh `dist/` (or build with `--out-dir` and pass the same directory to
`check_wheel.py --dist-dir`). The gate rejects missing or multiple distributions
to avoid testing stale artifacts. CI builds and checks on each matrix interpreter.

The smoke script creates a temporary directory outside the repository and a fresh
venv with no system site packages. It installs only hash-verified runtime
dependencies exported with `uv export --locked --no-dev --no-default-groups
--no-emit-project`, then installs the wheel with `--no-deps` and runs `uv pip check`.
It removes `PYTHONPATH`, `PYTHONHOME` and `VIRTUAL_ENV`, disables user site packages,
and verifies the imported package is inside that venv and came from a wheel.
The installed console script runs from the temporary app directory. Snapshot
checks deliberately avoid fixing the default schema version or schema contents.

Runtime/dev dependencies remain governed by `uv.lock`. Build dependencies are
separately pinned with hashes because isolated build dependencies are not covered
by that lock. To deliberately refresh the build constraints, export the current
`build-system.requires` values and resolve them with the pinned uv:

```sh
python3.12 -c 'import tomllib; print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["build-system"]["requires"]))' > /tmp/fastapi-contract-build.in
uv pip compile --python-version 3.11 --universal --generate-hashes --no-header \
  --output-file tools/release/build-constraints.txt /tmp/fastapi-contract-build.in
```

Review the resulting version/hash changes and rerun the gates before committing.
No dependency upgrades or publishing occur automatically in these gates.
