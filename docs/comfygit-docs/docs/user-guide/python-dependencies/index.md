# Python Dependency Guides

Python dependency guides cover durable package changes and dependency constraints
inside an environment.

## Start Here

- [Py commands](py-commands.md) covers `cg py add`, `cg py remove`, dependency
  groups, extras, and uv passthrough.
- [Constraints](constraints.md) explains version constraints for packages that
  need tighter resolution control.

Avoid manual installs into `.venv`. Sync can recreate the virtualenv, so durable
dependency changes should go through ComfyGit commands.
