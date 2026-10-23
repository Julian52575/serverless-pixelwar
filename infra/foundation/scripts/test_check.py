"""Unit tests for check.py. No gcloud, terraform or credentials needed:
python3 -m unittest discover -s infra/foundation/scripts"""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import check

MAIN_TF = """
# comment
variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west1"
  validation {
    condition     = can(regex("^[a-z]+$", var.region))
    error_message = "bad"
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "${var.project_id}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}
resource "google_compute_subnetwork" "subnet" {
  project                  = var.project_id
  name                     = "sub"
  region                   = var.region
  ip_cidr_range            = "10.0.1.0/24"
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true
}
"""

NET = {"name": "p-dev-vpc", "autoCreateSubnetworks": False, "routingConfig": {"routingMode": "REGIONAL"},
       "selfLink": "https://x/projects/p-dev/global/networks/p-dev-vpc"}
SUB = {"name": "sub", "region": "https://x/regions/europe-west1", "ipCidrRange": "10.0.1.0/24",
       "network": "https://x/global/networks/p-dev-vpc", "privateIpGoogleAccess": True}
DEFAULT_NET = {"name": "default", "autoCreateSubnetworks": True}


def fake_gcloud(nets: Any = None, subs: Any = None, fail: dict[str, str] | None = None):
    fail = fail or {}

    def run(args: list[str]) -> Any:
        key = " ".join(a for a in args if not a.startswith("--"))
        for k, code in fail.items():
            if key.startswith(k):
                raise check.GcloudError(code, "boom")
        if key.startswith("projects describe"):
            return {"projectId": "p-dev", "projectNumber": "1", "lifecycleState": "ACTIVE", "labels": {"x": 1}}
        if key.startswith("services list"):
            return [{"config": {"name": "compute.googleapis.com"}}]
        if key == "compute networks list":
            return [NET] if nets is None else nets
        if key == "compute networks subnets list":
            return [SUB] if subs is None else subs
        raise AssertionError(key)

    return run


_TMPDIRS: list[tempfile.TemporaryDirectory[str]] = []


def tearDownModule() -> None:
    for t in _TMPDIRS:
        t.cleanup()


class Repo:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        _TMPDIRS.append(self.tmp)
        self.root = Path(self.tmp.name)
        (self.root / "main.tf").write_text(MAIN_TF)
        (self.root / "dev.tfvars").write_text('project_id = "p-dev"\n')

    def run(self, mode: str = "all", **kw: Any) -> dict[str, Any]:
        with mock.patch.object(check, "IGNORE_FILE", self.root / "ignore.json"):
            return check.inspect_env("dev", self.root, mode, fake_gcloud(**kw))


def by_addr(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["address"] or r["id"]: r for r in out["resources"]}


class ParseTests(unittest.TestCase):
    def test_config_resolves_vars_templates_and_refs(self):
        cfg = check.load_config(Repo().root, "dev")
        net, sub = cfg.resources
        self.assertEqual(net.address, "google_compute_network.vpc")
        self.assertEqual(net.attrs["name"], "p-dev-vpc")
        self.assertEqual(sub.attrs["region"], "europe-west1")
        self.assertEqual(sub.attrs["network"], check.Ref("google_compute_network", "vpc", "id"))
        self.assertEqual(sub.depends_on, ["google_compute_network.vpc"])
        self.assertEqual(cfg.provider, {"project": "p-dev", "region": "europe-west1"})

    def test_unresolvable_expression_is_reported_not_guessed(self):
        r = Repo()
        (r.root / "extra.tf").write_text('resource "google_compute_network" "x" {\n  name = lower("A")\n}\n')
        x = next(d for d in check.load_config(r.root, "dev").resources if d.name == "x")
        self.assertIn("name", x.unresolved)

    def test_lists_heredoc_and_comments(self):
        blk = check.parse_hcl('a = [1, "b", true]\n/* c */ b = <<EOT\nhi\nEOT\n')
        self.assertEqual(check.evaluate(blk.attrs["a"], {}), [1, "b", True])
        self.assertIn("b", blk.attrs)

    def test_malformed_config(self):
        with self.assertRaises(check.HclError):
            check.parse_hcl('resource "x" "y" {\n')

    def test_missing_tfvars_fails_env(self):
        r = Repo()
        (r.root / "dev.tfvars").unlink()
        out = r.run()
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["sources"]["terraform_config"], "error")


class CompareTests(unittest.TestCase):
    def test_in_sync(self):
        out = Repo().run(nets=[NET])
        self.assertEqual({r["status"] for r in out["resources"]}, {"in_sync"})
        self.assertEqual(out["status"], "complete")
        self.assertEqual(check.exit_code([out]), check.EXIT_OK)

    def test_state_file_is_never_read(self):
        r = Repo()
        (r.root / "dev.tfstate").write_text("{not json")
        out = r.run(nets=[NET])
        self.assertEqual(out["status"], "complete")
        self.assertEqual(sorted(out["sources"]), ["gcloud", "terraform_config"])

    def test_untracked_live_resource(self):
        out = Repo().run(nets=[NET, DEFAULT_NET])
        self.assertEqual(by_addr(out)["p-dev/default"]["status"], "untracked")
        self.assertEqual(check.exit_code([out]), check.EXIT_DIFF)

    def test_missing_in_cloud(self):
        out = Repo().run(nets=[], subs=[])
        r = by_addr(out)["google_compute_network.vpc"]
        self.assertEqual(r["status"], "missing_in_cloud")
        self.assertFalse(r["in"]["cloud"])

    def test_drifted_with_evidence(self):
        out = Repo().run(nets=[{**NET, "routingConfig": {"routingMode": "GLOBAL"}}])
        r = by_addr(out)["google_compute_network.vpc"]
        self.assertEqual(r["status"], "drifted")
        self.assertEqual(r["evidence"], [{"field": "routing_mode", "sources": "config/cloud",
                                          "config": "REGIONAL", "cloud": "GLOBAL"}])

    def test_reference_compared_by_name(self):
        out = Repo().run(subs=[{**SUB, "network": "https://x/global/networks/other"}])
        r = by_addr(out)["google_compute_subnetwork.subnet"]
        self.assertEqual(r["status"], "drifted")
        self.assertEqual(r["evidence"][0]["field"], "network")

    def test_unobservable_attribute_is_unverified(self):
        out = Repo().run(nets=[{k: v for k, v in NET.items() if k != "routingConfig"}])
        r = by_addr(out)["google_compute_network.vpc"]
        self.assertEqual(r["status"], "in_sync")
        self.assertEqual(r["unverified"], ["routing_mode"])
        self.assertEqual(out["status"], "partial")

    def test_unsupported_type_is_unknown(self):
        r = Repo()
        (r.root / "b.tf").write_text('resource "google_storage_bucket" "b" {\n  name = "b"\n}\n')
        out = r.run()
        self.assertEqual(by_addr(out)["google_storage_bucket.b"]["status"], "unknown")
        self.assertEqual(out["status"], "partial")


class IgnoreTests(unittest.TestCase):
    def repo(self, rules: Any) -> Repo:
        r = Repo()
        (r.root / "ignore.json").write_text(json.dumps(rules) if not isinstance(rules, str) else rules)
        return r

    def test_ignored_live_resource_is_counted_not_a_difference(self):
        rules = {"rules": [{"type": "google_compute_network", "name": "default", "reason": "gcp default"}]}
        out = self.repo(rules).run(nets=[NET, DEFAULT_NET])
        self.assertNotIn("p-dev/default", by_addr(out))
        self.assertEqual(out["ignored"], [{"type": "google_compute_network", "name": "default",
                                           "reason": "gcp default", "count": 1}])
        self.assertEqual(check.exit_code([out]), check.EXIT_OK)

    def test_ignore_never_hides_declared_resource(self):
        rules = {"rules": [{"type": "google_compute_network", "name": "p-dev-vpc", "reason": "x"}]}
        out = self.repo(rules).run(nets=[])
        self.assertEqual(by_addr(out)["google_compute_network.vpc"]["status"], "missing_in_cloud")
        self.assertEqual(out["ignored"], [])

    def test_malformed_ignore_reports_error_and_ignores_nothing(self):
        out = self.repo('{"rules": [{"type": "x"}]}').run(nets=[NET, DEFAULT_NET])
        self.assertEqual(out["errors"][0]["source"], "ignore")
        self.assertEqual(by_addr(out)["p-dev/default"]["status"], "untracked")
        self.assertEqual(out["status"], "partial")


class FailureTests(unittest.TestCase):
    def test_permission_denied_never_reports_missing(self):
        out = Repo().run(fail={"compute networks list": "permission_denied"})
        r = by_addr(out)["google_compute_network.vpc"]
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["in"]["cloud"])
        self.assertIn("permission_denied", r["reason"])
        self.assertEqual(out["sources"]["gcloud"], "error")
        self.assertEqual(check.exit_code([out]), check.EXIT_INCOMPLETE)

    def test_malformed_listing(self):
        out = Repo().run(nets={"not": "a list"})
        self.assertEqual(by_addr(out)["google_compute_network.vpc"]["status"], "unknown")
        self.assertEqual(out["errors"][-1]["code"], "malformed_output")

    def test_missing_gcloud(self):
        with mock.patch("shutil.which", return_value=None), self.assertRaises(check.GcloudError) as e:
            check.run_gcloud(["projects", "list"])
        self.assertEqual(e.exception.code, "missing_tool")

    def test_gcloud_failure_classified_and_redacted(self):
        proc = subprocess.CompletedProcess([], 1, "", "ERROR: PERMISSION_DENIED token ya29.secret")
        with mock.patch("shutil.which", return_value="/bin/gcloud"), \
                mock.patch("subprocess.run", return_value=proc), self.assertRaises(check.GcloudError) as e:
            check.run_gcloud(["compute", "networks", "list"])
        self.assertEqual(e.exception.code, "permission_denied")
        self.assertNotIn("ya29", str(e.exception))

    def test_gcloud_non_json_and_timeout(self):
        with mock.patch("shutil.which", return_value="/bin/gcloud"):
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "nope", "")):
                with self.assertRaises(check.GcloudError) as e:
                    check.run_gcloud(["x"])
                self.assertEqual(e.exception.code, "malformed_output")
            with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("g", 1)):
                with self.assertRaises(check.GcloudError) as e:
                    check.run_gcloud(["x"])
                self.assertEqual(e.exception.code, "timeout")

    def test_gcloud_runs_without_prompts_or_shell(self):
        proc = subprocess.CompletedProcess([], 0, "[]", "")
        with mock.patch("shutil.which", return_value="/bin/gcloud"), \
                mock.patch("subprocess.run", return_value=proc) as run:
            check.run_gcloud(["compute", "networks", "list"])
        argv, kw = run.call_args.args[0], run.call_args.kwargs
        self.assertIsInstance(argv, list)
        self.assertNotIn("shell", kw)
        self.assertEqual(kw["env"]["CLOUDSDK_CORE_SHOULD_PROMPT_TO_ENABLE_API"], "false")


class CliTests(unittest.TestCase):
    def run_main(self, argv: list[str], repo: Repo, **kw: Any) -> tuple[int, str]:
        buf = io.StringIO()
        with mock.patch.object(check, "ROOT", repo.root), mock.patch.dict(check.ENVIRONMENTS, {"dev": "dev"}, clear=True), \
                mock.patch.object(check, "IGNORE_FILE", repo.root / "ignore.json"), redirect_stdout(buf):
            code = check.main(argv, fake_gcloud(**kw))
        return code, buf.getvalue()

    def test_output_is_compact_deterministic_json(self):
        repo = Repo()
        code1, out1 = self.run_main([], repo)
        _, out2 = self.run_main([], repo)
        self.assertEqual(out1, out2)
        doc = json.loads(out1)
        self.assertEqual(doc["exit_code"], code1)
        self.assertNotIn(": ", out1)
        self.assertEqual(code1, check.EXIT_OK)

    def test_terraform_only_never_calls_gcloud(self):
        repo = Repo()
        buf = io.StringIO()
        with mock.patch.object(check, "ROOT", repo.root), mock.patch.dict(check.ENVIRONMENTS, {"dev": "dev"}, clear=True), \
                redirect_stdout(buf):
            code = check.main(["--terraform-only"], lambda a: self.fail("gcloud called"))
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["environments"][0]["sources"]["gcloud"], "skipped")
        self.assertEqual(code, check.EXIT_OK)

    def test_cloud_only_lists_without_comparing(self):
        code, out = self.run_main(["--cloud-only"], Repo(), nets=[NET, DEFAULT_NET])
        env = json.loads(out)["environments"][0]
        self.assertEqual({r["status"] for r in env["resources"]}, {"unknown"})
        self.assertEqual(code, check.EXIT_OK)

    def test_internal_error_still_valid_json(self):
        with mock.patch.object(check, "inspect_env", side_effect=RuntimeError("x")):
            code, out = self.run_main([], Repo())
        self.assertEqual(json.loads(out)["environments"][0]["status"], "failed")
        self.assertEqual(code, check.EXIT_INCOMPLETE)

    def test_usage_error(self):
        with self.assertRaises(SystemExit) as e, redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            check.main(["--env", "staging"])
        self.assertEqual(e.exception.code, check.EXIT_USAGE)

    def test_real_repo_config_parses(self):
        for env in check.ENVIRONMENTS:
            cfg = check.load_config(Path(check.__file__).resolve().parent.parent, env)
            self.assertTrue(cfg.resources)
            self.assertTrue(cfg.provider["project"].startswith("masterpoulet-"))


if __name__ == "__main__":
    unittest.main()
