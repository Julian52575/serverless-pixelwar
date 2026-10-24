#!/usr/bin/env python3
"""Read-only comparison of Terraform config and live GCP.

Never runs terraform, never reads Terraform state, never mutates GCP.
JSON goes to stdout, diagnostics to stderr. See scripts/README.md for the schema.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 2
IGNORE_FILE = Path(__file__).resolve().parent / "ignore.json"

# CLI environment name -> file stem used by tfvars/backends and CI.
ENVIRONMENTS = {"dev": "dev", "prod": "prod"}

EXIT_OK, EXIT_DIFF, EXIT_USAGE, EXIT_INCOMPLETE = 0, 1, 2, 3

DIFF_STATUSES = {"missing_in_cloud", "drifted", "untracked"}
UNSET = object()
VERBOSE = False


def log(msg: str) -> None:
    if VERBOSE:
        print(f"check.py: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- HCL subset

class HclError(ValueError):
    pass


_TOKEN = re.compile(
    r"""(?P<ws>[ \t\r]+)
      |(?P<comment>\#[^\n]*|//[^\n]*|/\*.*?\*/)
      |(?P<nl>\n)
      |(?P<heredoc><<-?(?P<tag>[A-Za-z_]\w*)\n.*?\n[ \t]*(?P=tag)(?=\n|$))
      |(?P<str>"(?:[^"\\]|\\.)*")
      |(?P<num>\d+(?:\.\d+)?)
      |(?P<ident>[A-Za-z_][\w-]*)
      |(?P<op>==|!=|<=|>=|&&|\|\||=>|\.\.\.|[{}\[\]()=,.:?!<>+\-*/%])""",
    re.VERBOSE | re.DOTALL,
)


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            line = text.count("\n", 0, pos) + 1
            raise HclError(f"unexpected character {text[pos]!r} at line {line}")
        kind = m.lastgroup
        if kind not in ("ws", "comment"):
            tokens.append((kind, m.group(0)))
        pos = m.end()
    return tokens


@dataclass
class Block:
    type: str
    labels: list[str]
    attrs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)


def parse_hcl(text: str) -> Block:
    """Parse blocks and attributes; attribute values are kept as raw token lists."""
    tokens = tokenize(text)
    pos = 0

    def body(end: str | None) -> Block:
        nonlocal pos
        blk = Block("", [])
        while pos < len(tokens):
            kind, val = tokens[pos]
            if kind == "nl":
                pos += 1
                continue
            if end and val == end:
                pos += 1
                return blk
            if kind != "ident":
                raise HclError(f"expected identifier, got {val!r}")
            pos += 1
            if pos < len(tokens) and tokens[pos][1] == "=":
                pos += 1
                blk.attrs[val] = expression()
                continue
            labels = []
            while pos < len(tokens) and tokens[pos][0] in ("str", "ident"):
                labels.append(tokens[pos][1].strip('"'))
                pos += 1
            if pos >= len(tokens) or tokens[pos][1] != "{":
                raise HclError(f"expected '{{' after block {val!r}")
            pos += 1
            child = body("}")
            child.type, child.labels = val, labels
            blk.blocks.append(child)
        if end:
            raise HclError("unterminated block")
        return blk

    def expression() -> list[tuple[str, str]]:
        nonlocal pos
        out, depth = [], 0
        while pos < len(tokens):
            kind, val = tokens[pos]
            if depth == 0 and (kind == "nl" or val == "}"):
                break
            if val in "([{" and kind == "op":
                depth += 1
            elif val in ")]}" and kind == "op":
                depth -= 1
            if kind != "nl":
                out.append((kind, val))
            pos += 1
        if not out:
            raise HclError("empty expression")
        return out

    return body(None)


@dataclass(frozen=True)
class Ref:
    """Reference to another resource, e.g. google_compute_network.vpc.id."""

    type: str
    name: str
    attr: str


class Unresolved(Exception):
    pass


_INTERP = re.compile(r"\$\{\s*([^}]*?)\s*\}")


def evaluate(expr: list[tuple[str, str]], variables: dict[str, Any]) -> Any:
    """Evaluate literals, var.* and resource references; raise Unresolved otherwise."""
    if len(expr) == 1:
        kind, val = expr[0]
        if kind == "str":
            return _template(json.loads(val), variables)
        if kind == "num":
            return float(val) if "." in val else int(val)
        if kind == "ident" and val in ("true", "false"):
            return val == "true"
        if kind == "ident" and val == "null":
            return None
    if expr[0][1] == "[" and expr[-1][1] == "]":
        items, current = [], []
        for tok in expr[1:-1]:
            if tok[1] == "," and tok[0] == "op":
                if current:
                    items.append(evaluate(current, variables))
                current = []
            else:
                current.append(tok)
        if current:
            items.append(evaluate(current, variables))
        return items
    if len(expr) % 2 and all((k == "ident") if i % 2 == 0 else v == "." for i, (k, v) in enumerate(expr)):
        return _traversal([v for _, v in expr[::2]], variables)
    raise Unresolved(" ".join(v for _, v in expr))


def _traversal(parts: list[str], variables: dict[str, Any]) -> Any:
    if parts[0] == "var" and len(parts) == 2:
        if parts[1] not in variables or variables[parts[1]] is UNSET:
            raise Unresolved(f"var.{parts[1]} has no value")
        return variables[parts[1]]
    if len(parts) == 3 and parts[0] not in ("local", "module", "data", "each", "count", "path", "terraform"):
        return Ref(*parts)
    raise Unresolved(".".join(parts))


def _template(s: str, variables: dict[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        val = _traversal(m.group(1).split("."), variables)
        if isinstance(val, Ref):
            raise Unresolved(m.group(0))
        return str(val)

    return _INTERP.sub(sub, s)


# ------------------------------------------------------- Terraform config

@dataclass
class Declared:
    address: str
    type: str
    name: str
    attrs: dict[str, Any]
    unresolved: dict[str, str]
    depends_on: list[str]


@dataclass
class Config:
    resources: list[Declared]
    provider: dict[str, Any]
    warnings: list[str]


def load_config(root: Path, env: str) -> Config:
    files = sorted(root.glob("*.tf"))
    if not files:
        raise FileNotFoundError(f"no *.tf files in {root}")
    top = Block("", [])
    for f in files:
        parsed = parse_hcl(f.read_text())
        top.blocks.extend(parsed.blocks)

    tfvars_path = root / f"{ENVIRONMENTS[env]}.tfvars"
    if not tfvars_path.is_file():
        raise FileNotFoundError(f"missing {tfvars_path.name}")
    tfvars = parse_hcl(tfvars_path.read_text()).attrs

    variables: dict[str, Any] = {}
    for b in top.blocks:
        if b.type == "variable":
            variables[b.labels[0]] = evaluate(b.attrs["default"], {}) if "default" in b.attrs else UNSET
    for name, expr in tfvars.items():
        variables[name] = evaluate(expr, {})

    warnings = []
    unset = sorted(k for k, v in variables.items() if v is UNSET)
    if unset:
        warnings.append(f"variables without value: {','.join(unset)}")

    resources, provider = [], {}
    for b in top.blocks:
        if b.type == "resource":
            attrs, unresolved = {}, {}
            for k, expr in b.attrs.items():
                if k in ("depends_on", "count", "for_each", "lifecycle", "provider"):
                    continue
                try:
                    attrs[k] = evaluate(expr, variables)
                except Unresolved as e:
                    unresolved[k] = str(e)
            if "count" in b.attrs or "for_each" in b.attrs:
                warnings.append(f"{b.labels[0]}.{b.labels[1]}: count/for_each not expanded")
            refs = sorted({f"{v.type}.{v.name}" for v in attrs.values() if isinstance(v, Ref)})
            resources.append(Declared(f"{b.labels[0]}.{b.labels[1]}", b.labels[0], b.labels[1],
                                      attrs, unresolved, refs))
        elif b.type == "provider" and b.labels == ["google"]:
            for k, expr in b.attrs.items():
                try:
                    provider[k] = evaluate(expr, variables)
                except Unresolved:
                    pass
        elif b.type in ("module", "data"):
            warnings.append(f"{b.type} {'.'.join(b.labels)} not inspected")
    resources.sort(key=lambda r: r.address)
    return Config(resources, provider, warnings)


# ------------------------------------------------------------ Live GCP

def _basename(v: Any) -> Any:
    return v.rsplit("/", 1)[-1] if isinstance(v, str) else v


@dataclass(frozen=True)
class AttrSpec:
    tf: str
    live: str
    normalize: Callable[[Any], Any] = lambda v: v


@dataclass(frozen=True)
class TypeSpec:
    api: str
    list_args: tuple[str, ...]
    regional: bool
    attrs: tuple[AttrSpec, ...]


# Only types declared in the config are listed; add a spec to support a new type.
TYPE_SPECS: dict[str, TypeSpec] = {
    "google_compute_network": TypeSpec(
        "compute.googleapis.com", ("compute", "networks", "list"), False,
        (AttrSpec("name", "name"),
         AttrSpec("auto_create_subnetworks", "autoCreateSubnetworks"),
         AttrSpec("routing_mode", "routingConfig.routingMode"))),
    "google_compute_subnetwork": TypeSpec(
        "compute.googleapis.com", ("compute", "networks", "subnets", "list"), True,
        (AttrSpec("name", "name"),
         AttrSpec("region", "region", _basename),
         AttrSpec("ip_cidr_range", "ipCidrRange"),
         AttrSpec("network", "network", _basename),
         AttrSpec("private_ip_google_access", "privateIpGoogleAccess"))),
}


class GcloudError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_SECRET = re.compile(r"(ya29\.[\w.-]+|Bearer\s+\S+|\"?(access_token|refresh_token|private_key)\"?\s*[:=]\s*\S+)", re.IGNORECASE)

# Disables interactive prompts, notably "enable API? (y/N)", which would mutate the project.
GCLOUD_ENV = {
    "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
    "CLOUDSDK_CORE_SHOULD_PROMPT_TO_ENABLE_API": "false",
    "CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK": "true",
    "CLOUDSDK_CORE_DISABLE_USAGE_REPORTING": "true",
}


def classify(stderr: str) -> str:
    s = stderr.lower()
    if "permission_denied" in s or "permission denied" in s or "403" in s or "does not have" in s:
        return "permission_denied"
    if "service_disabled" in s or "has not been used" in s or "is disabled" in s:
        return "api_disabled"
    if "reauth" in s or "credential" in s or "gcloud auth login" in s or "unauthenticated" in s:
        return "auth_required"
    if "not found" in s or "404" in s:
        return "not_found"
    return "command_failed"


def run_gcloud(args: list[str], timeout: int = 60) -> Any:
    exe = shutil.which("gcloud")
    if not exe:
        raise GcloudError("missing_tool", "gcloud not found on PATH")
    try:
        proc = subprocess.run([exe, *args, "--format=json", "--quiet"], check=False, capture_output=True,
                              text=True,
                              timeout=timeout, env={**os.environ, **GCLOUD_ENV}, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise GcloudError("timeout", f"gcloud {' '.join(args[:3])} timed out after {timeout}s") from None
    except OSError as e:
        raise GcloudError("missing_tool", str(e)) from None
    if proc.returncode != 0:
        msg = _SECRET.sub("[redacted]", proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "")
        raise GcloudError(classify(proc.stderr), msg[:300])
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        raise GcloudError("malformed_output", f"gcloud {' '.join(args[:3])} returned non-JSON") from None


@dataclass
class Live:
    project: dict[str, Any] | None = None
    services: list[str] | None = None
    # type -> list of live items, or None when listing failed.
    items: dict[str, list[dict[str, Any]] | None] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)


def inspect_cloud(project_id: str, types: list[str], gcloud: Callable[[list[str]], Any] = run_gcloud) -> Live:
    live = Live()

    def call(source: str, args: list[str]) -> Any:
        try:
            return gcloud(args)
        except GcloudError as e:
            live.errors.append({"source": source, "code": e.code, "message": str(e)})
            return e

    res = call("project", ["projects", "describe", project_id])
    if isinstance(res, GcloudError):
        if res.code == "missing_tool":
            for t in types:
                live.items[t], live.failures[t] = None, "missing_tool"
            return live
    elif isinstance(res, dict):
        live.project = {k: res.get(k) for k in ("projectId", "projectNumber", "lifecycleState")}

    res = call("services", ["services", "list", "--enabled", f"--project={project_id}"])
    if isinstance(res, list):
        live.services = sorted(s.get("config", {}).get("name") or _basename(s.get("name")) for s in res)

    for t in types:
        spec = TYPE_SPECS.get(t)
        if not spec:
            live.items[t], live.failures[t] = None, "unsupported_type"
            continue
        res = call(t, [*spec.list_args, f"--project={project_id}"])
        if isinstance(res, GcloudError):
            live.items[t], live.failures[t] = None, res.code
        elif not isinstance(res, list):
            live.items[t], live.failures[t] = None, "malformed_output"
            live.errors.append({"source": t, "code": "malformed_output", "message": "expected a JSON list"})
        else:
            live.items[t] = res
    return live


def _get(item: dict[str, Any], path: str) -> Any:
    cur: Any = item
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


# -------------------------------------------------------------- Comparison

def _ident(type_: str, name: Any, region: Any) -> str:
    spec = TYPE_SPECS.get(type_)
    return f"{region}/{name}" if spec and spec.regional else str(name)


def _expected(value: Any, by_address: dict[str, Declared]) -> Any:
    """References compare by the referenced resource's name (live APIs return its URL)."""
    if isinstance(value, Ref):
        target = by_address.get(f"{value.type}.{value.name}")
        if target and isinstance(target.attrs.get("name"), str):
            return target.attrs["name"]
        raise Unresolved(f"{value.type}.{value.name}.{value.attr}")
    return value


def load_ignore(path: Path) -> list[dict[str, str]]:
    """Rules matching undeclared live resources by exact type and name."""
    if not path.is_file():
        return []
    rules = json.loads(path.read_text())["rules"]
    if not all(isinstance(r, dict) and {"type", "name", "reason"} <= r.keys() for r in rules):
        raise ValueError("each rule needs type, name and reason")
    return rules


def compare(env: str, project_id: str, config: Config | None, live: Live | None, default_region: Any,
            ignore: list[dict[str, str]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results = []
    ignored = [{**r, "count": 0} for r in ignore or []]
    declared = config.resources if config else []
    by_address = {d.address: d for d in declared}
    claimed: set[tuple[str, str]] = set()

    for d in declared:
        r: dict[str, Any] = {"address": d.address, "type": d.type, "id": None, "status": "unknown",
                             "in": {"config": True, "cloud": None},
                             "evidence": [], "unverified": [], "reason": None}
        spec = TYPE_SPECS.get(d.type)

        project = d.attrs.get("project", project_id)
        region = d.attrs.get("region", default_region)
        name = d.attrs.get("name")
        if isinstance(name, str):
            r["id"] = f"{project}/{_ident(d.type, name, region)}"

        expected: dict[str, Any] = {}
        for k in sorted(d.attrs):
            try:
                expected[k] = _expected(d.attrs[k], by_address)
            except Unresolved:
                r["unverified"].append(k)
        r["unverified"].extend(sorted(d.unresolved))

        live_item = None
        if live is None:
            r["reason"] = "cloud inspection skipped"
        elif not spec:
            r["reason"] = f"no live inspector for {d.type}"
        elif project != project_id:
            r["reason"] = f"declared project {project} differs from environment project"
        elif not isinstance(name, str):
            r["reason"] = "name not resolvable from config"
        elif live.items.get(d.type) is None:
            r["reason"] = f"live listing failed: {live.failures.get(d.type, 'unknown')}"
        else:
            key = _ident(d.type, name, region)
            matches = [i for i in live.items[d.type]
                       if _ident(d.type, i.get("name"), _basename(i.get("region"))) == key]
            r["in"]["cloud"] = bool(matches)
            if matches:
                live_item = matches[0]
                claimed.add((d.type, key))

        if live_item is not None:
            compared = []
            for a in spec.attrs:  # type: ignore[union-attr]
                if a.tf not in expected:
                    continue
                lv = a.normalize(_get(live_item, a.live))
                if lv is None:
                    r["unverified"].append(a.tf)
                    continue
                compared.append(a.tf)
                if lv != expected[a.tf]:
                    r["evidence"].append({"field": a.tf, "sources": "config/cloud",
                                          "config": expected[a.tf], "cloud": lv})
            r["unverified"].extend(k for k in expected if k not in compared and k != "project")

        kinds = {e["sources"] for e in r["evidence"]}
        if r["in"]["cloud"] is False:
            r["status"] = "missing_in_cloud"
            r["reason"] = "listing succeeded and has no matching resource"
        elif "config/cloud" in kinds:
            r["status"] = "drifted"
        elif r["in"]["cloud"]:
            r["status"] = "in_sync"
        elif r["reason"] is None:
            r["reason"] = "insufficient evidence"
        r["unverified"] = sorted(set(r["unverified"]))
        results.append(r)

    if live is not None:
        for t in sorted(live.items):
            for item in live.items[t] or []:
                key = _ident(t, item.get("name"), _basename(item.get("region")))
                if (t, key) in claimed:
                    continue
                rule = next((r for r in ignored if r["type"] == t and r["name"] == item.get("name")), None)
                if rule:
                    rule["count"] += 1
                    continue
                results.append({"address": None, "type": t, "id": f"{project_id}/{key}",
                                "status": "untracked" if config else "unknown",
                                "in": {"config": False if config else None, "cloud": True},
                                "evidence": [], "unverified": [],
                                "reason": "live resource not declared in config" if config
                                else "comparison skipped"})

    results.sort(key=lambda r: (r["type"], r["address"] or "", r["id"] or ""))
    return results, sorted((r for r in ignored if r["count"]), key=lambda r: (r["type"], r["name"]))


# ---------------------------------------------------------------- Driver

def inspect_env(env: str, root: Path, mode: str, gcloud: Callable[[list[str]], Any] = run_gcloud) -> dict[str, Any]:
    out: dict[str, Any] = {"environment": env, "project_id": None, "status": "complete",
                           "sources": {"terraform_config": "ok", "gcloud": "skipped"},
                           "project": None, "services": None, "resources": [], "ignored": [], "errors": [],
                           "warnings": []}
    config = None
    try:
        config = load_config(root, env)
        out["warnings"].extend(config.warnings)
        out["project_id"] = config.provider.get("project")
    except (OSError, HclError, Unresolved, KeyError) as e:
        out["sources"]["terraform_config"] = "error"
        out["errors"].append({"source": "terraform_config", "code": "parse_failed", "message": str(e)})

    if not isinstance(out["project_id"], str):
        out["status"] = "failed"
        out["errors"].append({"source": "terraform_config", "code": "no_project",
                              "message": "project_id not resolvable; nothing inspected"})
        return out
    project_id = out["project_id"]

    live = None
    if mode != "terraform":
        types = sorted({r.type for r in config.resources}) if config else []
        log(f"{env}: inspecting {project_id} ({', '.join(types) or 'project only'})")
        live = inspect_cloud(project_id, types, gcloud)
        out["project"], out["services"], out["errors"] = live.project, live.services, out["errors"] + live.errors
        out["sources"]["gcloud"] = "error" if live.errors else "ok"
        if live.services is not None:
            for t in sorted(live.items):
                spec = TYPE_SPECS.get(t)
                if spec and spec.api not in live.services:
                    out["warnings"].append(f"{spec.api} not enabled; {t} cannot exist")

    ignore = []
    if mode != "cloud":
        try:
            ignore = load_ignore(IGNORE_FILE)
        except (OSError, ValueError, KeyError, TypeError) as e:
            out["errors"].append({"source": "ignore", "code": "parse_failed", "message": str(e)})
    out["resources"], out["ignored"] = compare(env, project_id, config if mode != "cloud" else None,
                                               live, config.provider.get("region") if config else None,
                                               ignore)
    if mode == "cloud":
        out["sources"]["terraform_config"] = "discovery_only"

    failed_sources = any(v in ("error", "unavailable") for v in out["sources"].values())
    real_unknown = any(r["status"] == "unknown" and r["reason"] != "comparison skipped"
                       and r["reason"] != "cloud inspection skipped" for r in out["resources"])
    if failed_sources or out["errors"] or real_unknown or any(r["unverified"] for r in out["resources"]):
        out["status"] = "partial"
    return out


def exit_code(envs: list[dict[str, Any]]) -> int:
    if any(r["status"] in DIFF_STATUSES for e in envs for r in e["resources"]):
        return EXIT_DIFF
    if any(e["status"] != "complete" for e in envs):
        return EXIT_INCOMPLETE
    return EXIT_OK


def main(argv: list[str] | None = None, gcloud: Callable[[list[str]], Any] = run_gcloud) -> int:
    p = argparse.ArgumentParser(
        description="Read-only comparison of Terraform config and live GCP. "
                    "Exit codes: 0 in sync, 1 differences, 2 usage error, 3 inspection incomplete.")
    p.add_argument("--env", choices=["dev", "prod", "all"], default="all", help="default: all")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--terraform-only", action="store_true", help="parse the config only; no gcloud calls")
    mode.add_argument("--cloud-only", action="store_true",
                      help="list live resources only; config is read just to pick the project and types")
    p.add_argument("--verbose", action="store_true", help="progress on stderr")
    args = p.parse_args(argv)
    global VERBOSE
    VERBOSE = args.verbose

    m = "terraform" if args.terraform_only else "cloud" if args.cloud_only else "all"
    envs = list(ENVIRONMENTS) if args.env == "all" else [args.env]
    results = []
    for env in envs:
        try:
            results.append(inspect_env(env, ROOT, m, gcloud))
        except Exception as e:  # noqa: BLE001 -- keep stdout valid JSON whatever happens
            results.append({"environment": env, "project_id": None, "status": "failed", "sources": {},
                            "project": None, "services": None, "resources": [], "ignored": [],
                            "errors": [{"source": "internal", "code": type(e).__name__, "message": str(e)}],
                            "warnings": []})
    code = exit_code(results)
    json.dump({"schema": SCHEMA_VERSION, "exit_code": code, "environments": results},
              sys.stdout, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
