---
created: 2026-02-13T08:15:55.658Z
title: Migrate to uv environment manager
area: tooling
files:
  - pyproject.toml
  - uv.lock
---

## Problem

The project currently uses setuptools as its build backend (`pyproject.toml` has `setuptools>=70.0` + `wheel`). A `uv.lock` file already exists (untracked), suggesting uv is partially in use, but the project isn't fully migrated. Moving to uv as the primary environment/package manager would provide faster installs, better dependency resolution, and a unified workflow for venv creation, dependency management, and script running.

## Solution

1. Update `pyproject.toml` build-system to use uv-compatible backend (e.g., `hatchling` or keep setuptools — uv supports both)
2. Replace any pip/venv workflows with `uv sync`, `uv run`, `uv add`/`uv remove`
3. Commit `uv.lock` to version control
4. Update any scripts, CI config, or documentation that reference pip/venv
5. Verify all dependencies resolve correctly and the bot runs via `uv run`
