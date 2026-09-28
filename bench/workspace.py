"""Build the agent workspace for one benchmark context mode.

    python -m bench.workspace build --mode dbt_context --out /tmp/ws \\
        --dbt ../shorelane-dbt --context ../shorelane-analytics-context \\
        --manifest /tmp/ws.manifest.json
    python -m bench.workspace check --dbt ../shorelane-dbt --context ../shorelane-analytics-context

Modes and sources are declared in bench/modes.yaml. Files are read from the git
object store at each source's pinned commit, never from a working tree, so a
dirty checkout cannot leak into a run. `--allow-unpinned` (development only)
reads a source whose commit is not pinned yet from HEAD, or from a plain
directory, and marks the manifest `pinned: false`.

Every build is scanned by bench.leakage and fails on any finding. The manifest
(written OUTSIDE the workspace) records each mounted file's hash and one
workspace hash, so a result can always be traced to the exact context it had.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Protocol

import yaml

from bench.leakage import Finding, gold_values, scan_workspace

MODES_PATH = pathlib.Path(__file__).resolve().parent / "modes.yaml"


class WorkspaceError(Exception):
    pass


class LeakageError(WorkspaceError):
    def __init__(self, findings: list[Finding]):
        self.findings = findings
        super().__init__("workspace leaks evaluation material:\n  " + "\n  ".join(map(str, findings)))


@dataclass(frozen=True)
class Source:
    name: str
    repo: str
    commit: str | None
    mount: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    rename: dict[str, str] = field(default_factory=dict)


def load_config(path: pathlib.Path = MODES_PATH) -> dict:
    config = yaml.safe_load(path.read_text())
    config["sources"] = {
        name: Source(
            name=name,
            repo=spec["repo"],
            commit=spec.get("commit"),
            mount=spec["mount"],
            include=tuple(spec.get("include") or ()),
            exclude=tuple(spec.get("exclude") or ()),
            rename=dict(spec.get("rename") or {}),
        )
        for name, spec in config["sources"].items()
    }
    for mode, spec in config["modes"].items():
        unknown = set(spec["sources"]) - set(config["sources"])
        if unknown:
            raise WorkspaceError(f"mode {mode} names unknown sources {sorted(unknown)}")
    return config


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return fnmatch.fnmatchcase(path, pattern)


def select(paths: list[str], source: Source) -> dict[str, str]:
    """Mount-relative destination -> source path, for the files a source mounts."""
    chosen = {
        path: path
        for path in paths
        if any(matches(path, p) for p in source.include)
        and not any(matches(path, p) for p in source.exclude)
    }
    for src, dest in source.rename.items():
        if src not in paths:
            raise WorkspaceError(f"{source.name}: renamed file {src} does not exist")
        chosen[dest] = src
    return chosen


class Reader(Protocol):
    revision: str | None

    def list_files(self) -> list[str]: ...

    def read(self, path: str) -> bytes: ...


class GitReader:
    """Files at one commit of a local clone, read from the object store."""

    def __init__(self, root: pathlib.Path, revision: str):
        self.root = root
        self.revision = self._git("rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()

    def _git(self, *args: str) -> bytes:
        try:
            return subprocess.run(
                ["git", "-C", str(self.root), *args], check=True, capture_output=True
            ).stdout
        except subprocess.CalledProcessError as exc:
            raise WorkspaceError(
                f"git {' '.join(args)} failed in {self.root}: {exc.stderr.decode().strip()}"
            ) from exc

    def list_files(self) -> list[str]:
        return self._git("ls-tree", "-r", "--name-only", "-z", self.revision).decode().split("\0")[:-1]

    def read(self, path: str) -> bytes:
        return self._git("show", f"{self.revision}:{path}")


class DirReader:
    """A plain directory (development only: no revision to pin)."""

    revision = None

    def __init__(self, root: pathlib.Path):
        self.root = root

    def list_files(self) -> list[str]:
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(self.root).parts
        )

    def read(self, path: str) -> bytes:
        return (self.root / path).read_bytes()


def open_source(source: Source, root: pathlib.Path, allow_unpinned: bool) -> Reader:
    is_git = (root / ".git").exists()
    if source.commit:
        if not is_git:
            raise WorkspaceError(f"{source.name} is pinned to {source.commit}; {root} is not a git clone")
        return GitReader(root, source.commit)
    if not allow_unpinned:
        raise WorkspaceError(
            f"{source.name} has no pinned commit in bench/modes.yaml; pin it, or pass "
            "--allow-unpinned for a development build"
        )
    return GitReader(root, "HEAD") if is_git else DirReader(root)


def plan(config: dict, mode: str, readers: dict[str, Reader]) -> dict[str, tuple[str, str]]:
    """Workspace path -> (source name, source path) for one mode."""
    if mode not in config["modes"]:
        raise WorkspaceError(f"unknown mode {mode!r}; known: {sorted(config['modes'])}")
    layout: dict[str, tuple[str, str]] = {}
    for name in config["modes"][mode]["sources"]:
        source = config["sources"][name]
        if name not in readers:
            raise WorkspaceError(f"mode {mode} needs source {name}: pass --{name}")
        for dest, src in select(readers[name].list_files(), source).items():
            layout[f"{source.mount}/{dest}"] = (name, src)
    return dict(sorted(layout.items()))


def build(
    config: dict,
    mode: str,
    out: pathlib.Path,
    readers: dict[str, Reader],
    golds: set[str] | None = None,
) -> dict:
    if out.exists() and any(out.iterdir()):
        raise WorkspaceError(f"{out} is not empty; a workspace starts fresh")
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for dest, (name, src) in plan(config, mode, readers).items():
        data = readers[name].read(src)
        target = out / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append({"path": dest, "source": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})

    findings = scan_workspace(out, gold_values() if golds is None else golds)
    if findings:
        raise LeakageError(findings)

    used = config["modes"][mode]["sources"]
    return {
        "bench_version": config["bench_version"],
        "mode": mode,
        "warehouse": config["warehouse"],
        "preamble": config["preamble"],
        "sources": [
            {
                "name": name,
                "repo": config["sources"][name].repo,
                "commit": readers[name].revision,
                "pinned": bool(config["sources"][name].commit),
            }
            for name in used
        ],
        "files": files,
        "workspace_sha256": hashlib.sha256(
            "".join(f"{f['path']}\0{f['sha256']}\n" for f in files).encode()
        ).hexdigest(),
    }


def check_ablation(manifests: dict[str, dict], config: dict) -> list[str]:
    """Each mode must be the previous one plus exactly its extra source's files."""
    errors = []
    order = list(config["modes"])
    for smaller, larger in zip(order, order[1:]):
        small = {f["path"]: f["sha256"] for f in manifests[smaller]["files"]}
        large = {f["path"]: f["sha256"] for f in manifests[larger]["files"]}
        changed = [p for p in small if large.get(p) != small[p]]
        if changed:
            errors.append(f"{larger} does not contain {smaller} unchanged: {changed[:5]}")
        added_sources = set(config["modes"][larger]["sources"]) - set(config["modes"][smaller]["sources"])
        mounts = tuple(f"{config['sources'][s].mount}/" for s in added_sources)
        stray = [p for p in large if p not in small and not p.startswith(mounts)]
        if stray:
            errors.append(f"{larger} adds files outside {mounts}: {stray[:5]}")
    return errors


def _readers(args: argparse.Namespace, config: dict, names: set[str]) -> dict[str, Reader]:
    readers = {}
    for name in sorted(names):
        root = getattr(args, name, None)
        if root is not None:
            readers[name] = open_source(config["sources"][name], pathlib.Path(root), args.allow_unpinned)
    return readers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bench.workspace")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "check"):
        p = sub.add_parser(command)
        p.add_argument("--dbt", help="local clone of shorelane-dbt")
        p.add_argument("--context", help="local clone of shorelane-analytics-context")
        p.add_argument("--allow-unpinned", action="store_true")
        p.add_argument("--config", type=pathlib.Path, default=MODES_PATH)
        if command == "build":
            p.add_argument("--mode", required=True)
            p.add_argument("--out", type=pathlib.Path, required=True)
            p.add_argument("--manifest", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        if args.command == "build":
            readers = _readers(args, config, set(config["modes"].get(args.mode, {}).get("sources", [])))
            manifest = build(config, args.mode, args.out, readers)
            args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"{args.mode}: {len(manifest['files'])} files -> {args.out} "
                  f"(workspace {manifest['workspace_sha256'][:12]})")
            return 0

        readers = _readers(args, config, set(config["sources"]))
        manifests = {}
        golds = gold_values()
        with tempfile.TemporaryDirectory() as tmp:
            for mode in config["modes"]:
                manifests[mode] = build(config, mode, pathlib.Path(tmp) / mode, readers, golds)
        errors = check_ablation(manifests, config)
        for mode, m in manifests.items():
            size = sum(f["bytes"] for f in m["files"])
            pins = ", ".join(f"{s['name']}@{(s['commit'] or 'dir')[:10]}{'' if s['pinned'] else ' (unpinned)'}"
                             for s in m["sources"]) or "-"
            print(f"  {mode:<12} {len(m['files']):>4} files {size:>9,} bytes  {pins}")
        if errors:
            raise WorkspaceError("ablation check failed:\n  " + "\n  ".join(errors))
        print(f"all {len(manifests)} modes build, pass the leakage scan, and nest cleanly")
        return 0
    except WorkspaceError as exc:
        print(f"bench.workspace {args.command} FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
