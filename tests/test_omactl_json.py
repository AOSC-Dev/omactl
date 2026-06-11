import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OMACTL = REPO / "src" / "omactl"


def write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class OmactlJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.log"
        self.systemd_args = self.root / "systemd.args"
        self.env = os.environ.copy()
        self.env["PATH"] = f"{self.bin}:{self.env.get('PATH', '')}"
        self.env["OMA_BIN"] = str(self.bin / "oma")
        self.env["OMACTL_UNIT_SEED"] = "test"
        self.env["OMACTL_DISABLE_BUSY_CHECK"] = "1"
        self.env["OMACTL_STATE_DIR"] = str(self.root / "state")
        owned = self.root / "state" / "units"
        owned.mkdir(parents=True)
        (owned / "oma-task-test.service").write_text(
            "unit=oma-task-test.service\noperation=install\ninvocation_id=invocation-oma-task-test.service\n",
            encoding="utf-8",
        )
        self._write_fakes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_fakes(self) -> None:
        write_exe(
            self.bin / "oma",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            echo "oma:$*" >> {self.calls!s}
            if [[ "${{OMA_FAKE_MODE:-}}" == "bad-json" ]]; then
              echo '{{'
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "pretty-json" ]]; then
              python3 - <<'PY'
import json
print(json.dumps([
    dict(
        name="nano",
        branches=["stable"],
        current_version="7.2",
        new_version=None,
        architecture="amd64",
        status=["installed"],
    )
], indent=2))
PY
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "missing-field" ]]; then
              echo '{{"name":"broken"}}'
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "missing-branches" ]]; then
              echo '{{"name":"broken","current_version":"1","architecture":"amd64","status":["installed"]}}'
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "bad-new-version" ]]; then
              echo '{{"name":"broken","branches":["stable"],"current_version":"1","architecture":"amd64","new_version":42,"status":["installed"]}}'
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "empty-new-version" ]]; then
              echo '{{"name":"nano","branches":["stable"],"current_version":"7.2","new_version":"","architecture":"amd64","status":["installed"]}}'
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "scalar" ]]; then
              echo '"not-an-object"'
              exit 0
            fi
            if [[ "${{OMA_FAKE_MODE:-}}" == "nonzero" ]]; then
              echo 'delegated failure' >&2
              exit 42
            fi
            if [[ "${{1:-}}" == "--version" ]]; then
              echo "oma 1.25.0"
              exit 0
            fi
            if [[ "${{1:-}}" == "list" && "${{2:-}}" == "--installed" && "${{3:-}}" == "--json" ]]; then
              echo '{{"name":"nano","branches":["stable"],"current_version":"7.2","new_version":null,"architecture":"amd64","status":["installed"]}}'
              echo '{{"name":"htop","branches":["stable"],"current_version":"3.3","new_version":"3.4","architecture":"amd64","status":["installed","upgradable","automatic"]}}'
              exit 0
            fi
            if [[ "${{1:-}}" == "list" && "${{2:-}}" == "--upgradable" && "${{3:-}}" == "--json" ]]; then
              echo '{{"name":"htop","branches":["stable"],"current_version":"3.3","new_version":"3.4","architecture":"amd64","status":["installed","upgradable"]}}'
              exit 0
            fi
            if [[ "${{1:-}}" == "show" && "${{2:-}}" == "--json" ]]; then
              shift 2
              for pkg in "$@"; do
                echo '{{"name":"'"$pkg"'","version":"1.0","architecture":"amd64","summary":"demo package","description":"demo desc"}}'
              done
              exit 0
            fi
            if [[ "${{1:-}}" == "search" && "${{2:-}}" == "--json" ]]; then
              echo '[{{"name":"nano","new_version":"7.2","status":"Avail","desc":"editor"}}]'
              exit 0
            fi
            exit 0
            """,
        )
        write_exe(
            self.bin / "systemd-run",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            echo "systemd-run:$*" >> {self.calls!s}
            python3 - "$@" > {self.systemd_args!s} <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]))
PY
            exit 0
            """,
        )
        write_exe(
            self.bin / "systemctl",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            echo "systemctl:$*" >> {self.calls!s}
            if [[ "${{1:-}}" == "show" ]]; then
              unit="${{2:-}}"
              echo "Id=$unit"
              case "${{SYSTEMD_FAKE_MODE:-}}" in
                mismatch)
                  echo 'LoadState=loaded'
                  echo "InvocationID=foreign-$unit"
                  echo 'ActiveState=active'
                  echo 'SubState=running'
                  echo 'Result=success'
                  echo 'ExecMainStatus=0'
                  ;;
                not-found)
                  echo 'LoadState=not-found'
                  echo "InvocationID=invocation-$unit"
                  echo 'ActiveState=inactive'
                  echo 'SubState=dead'
                  echo 'Result='
                  echo 'ExecMainStatus=0'
                  ;;
                terminal)
                  echo 'LoadState=loaded'
                  echo "InvocationID=invocation-$unit"
                  echo 'ActiveState=inactive'
                  echo 'SubState=dead'
                  echo 'Result=success'
                  echo 'ExecMainStatus=0'
                  ;;
                failed)
                  echo 'LoadState=loaded'
                  echo "InvocationID=invocation-$unit"
                  echo 'ActiveState=failed'
                  echo 'SubState=failed'
                  echo 'Result=exit-code'
                  echo 'ExecMainStatus=1'
                  ;;
                unknown)
                  echo 'LoadState=loaded'
                  echo "InvocationID=invocation-$unit"
                  echo 'ActiveState=inactive'
                  echo 'SubState=dead'
                  echo 'Result='
                  echo 'ExecMainStatus=0'
                  ;;
                *)
                  echo 'LoadState=loaded'
                  echo "InvocationID=invocation-$unit"
                  echo 'ActiveState=active'
                  echo 'SubState=running'
                  echo 'Result=success'
                  echo 'ExecMainStatus=0'
                  ;;
              esac
              exit 0
            fi
            if [[ "${{1:-}}" == "stop" ]]; then
              exit 0
            fi
            if [[ "${{1:-}}" == "list-units" ]]; then
              echo 'oma-task-test.service loaded active running demo'
              exit 0
            fi
            exit 0
            """,
        )
        write_exe(
            self.bin / "journalctl",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            echo "journalctl:$*" >> {self.calls!s}
            follow=0
            for arg in "$@"; do
              if [[ "$arg" == "-f" ]]; then follow=1; fi
            done
            if [[ "$follow" == "1" && "${{JOURNAL_FAKE_MODE:-}}" == "follow-hang" ]]; then
              echo 'line one'
              sleep 5
              exit 0
            fi
            echo 'line one'
            echo 'line two'
            exit 0
            """,
        )

    def run_omactl(self, *args: str, timeout=None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(OMACTL), *args],
            cwd=REPO,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )

    def load_json(self, proc: subprocess.CompletedProcess[str]):
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"stdout was not JSON: {proc.stdout!r}; stderr={proc.stderr!r}; {exc}")

    def remove_tool_from_path(self, tool: str) -> None:
        no_tool = self.root / f"no-{tool}"
        no_tool.mkdir()
        for name in ["bash", "python3", "oma", "systemd-run", "journalctl"]:
            source = self.bin / name
            if source.exists() and name != tool:
                (no_tool / name).symlink_to(source)
        (no_tool / "bash").unlink(missing_ok=True)
        (no_tool / "bash").symlink_to("/bin/bash")
        (no_tool / "python3").unlink(missing_ok=True)
        (no_tool / "python3").symlink_to("/usr/bin/python3")
        self.env["PATH"] = str(no_tool)

    def test_capabilities_json_envelope(self):
        proc = self.run_omactl("capabilities", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "omactl.capabilities")
        self.assertIn("query.installed.v1", payload["data"]["capabilities"])
        self.assertNotIn("query.search.v1", payload["data"]["capabilities"])
        self.assertNotIn("plan.upgrade.v1", payload["data"]["capabilities"])
        self.assertIn("run.upgrade.selected.v1", payload["data"]["capabilities"])

    def test_capabilities_do_not_advertise_oma_backed_queries_when_oma_missing(self):
        self.env["OMA_BIN"] = str(self.bin / "missing-oma")
        proc = self.run_omactl("capabilities", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertNotIn("query.installed.v1", payload["data"]["capabilities"])
        self.assertNotIn("run.install.v1", payload["data"]["capabilities"])

    def test_capabilities_do_not_advertise_run_or_logs_without_systemctl(self):
        self.remove_tool_from_path("systemctl")
        proc = self.run_omactl("capabilities", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        caps = payload["data"]["capabilities"]
        self.assertNotIn("run.install.v1", caps)
        self.assertNotIn("run.upgrade.selected.v1", caps)
        self.assertNotIn("unit.logs.v1", caps)

    def test_capabilities_empty_set_returns_valid_json(self):
        no_tools = self.root / "no-tools"
        no_tools.mkdir()
        (no_tools / "bash").symlink_to("/bin/bash")
        self.env["PATH"] = str(no_tools)
        self.env["OMA_BIN"] = str(no_tools / "missing-oma")
        proc = self.run_omactl("capabilities", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["data"]["capabilities"], [])

    def test_query_installed_wraps_json_lines(self):
        proc = self.run_omactl("query", "installed", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.query.installed")
        self.assertEqual([p["name"] for p in payload["data"]["packages"]], ["nano", "htop"])
        self.assertEqual(payload["data"]["packages"][0]["branches"], ["stable"])
        self.assertIsInstance(payload["data"]["packages"][0]["status"], str)
        self.assertEqual(payload["data"]["packages"][0]["status"], "installed")
        self.assertNotIn("new_version", payload["data"]["packages"][0])
        self.assertEqual(
            payload["data"]["packages"][1]["status"],
            "automatic,installed,upgradable",
        )
        self.assertTrue(payload["data"]["packages"][0]["installed"])
        self.assertTrue(payload["data"]["packages"][1]["upgradable"])
        self.assertTrue(payload["data"]["packages"][1]["automatic"])
        self.assertFalse(payload["data"]["packages"][0]["held"])

    def test_query_installed_wraps_pretty_single_json_document(self):
        self.env["OMA_FAKE_MODE"] = "pretty-json"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.query.installed")
        self.assertEqual(payload["data"]["packages"][0]["name"], "nano")
        self.assertNotIn("new_version", payload["data"]["packages"][0])

    def test_query_installed_omits_empty_new_version(self):
        self.env["OMA_FAKE_MODE"] = "empty-new-version"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertNotIn("new_version", payload["data"]["packages"][0])
        self.assertFalse(payload["data"]["packages"][0]["upgradable"])

    def test_query_upgradable_wraps_json_lines(self):
        proc = self.run_omactl("query", "upgradable", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.query.upgradable")
        self.assertEqual(payload["data"]["packages"][0]["name"], "htop")
        self.assertEqual(payload["data"]["packages"][0]["new_version"], "3.4")

    def test_query_package_detail_wraps_json_lines(self):
        proc = self.run_omactl("query", "package-detail", "--json", "nano", "htop")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.query.package-detail")
        self.assertEqual([p["name"] for p in payload["data"]["packages"]], ["nano", "htop"])

    def test_query_malformed_delegate_output_returns_single_error_envelope(self):
        self.env["OMA_FAKE_MODE"] = "bad-json"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "MALFORMED_DELEGATE_OUTPUT")

    def test_query_missing_required_field_returns_malformed_delegate_output(self):
        self.env["OMA_FAKE_MODE"] = "missing-field"
        proc = self.run_omactl("query", "upgradable", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "MALFORMED_DELEGATE_OUTPUT")

    def test_query_installed_missing_branches_returns_malformed_delegate_output(self):
        self.env["OMA_FAKE_MODE"] = "missing-branches"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "MALFORMED_DELEGATE_OUTPUT")

    def test_query_scalar_delegate_output_returns_malformed_delegate_output(self):
        self.env["OMA_FAKE_MODE"] = "scalar"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "MALFORMED_DELEGATE_OUTPUT")

    def test_query_invalid_new_version_returns_malformed_delegate_output(self):
        self.env["OMA_FAKE_MODE"] = "bad-new-version"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "MALFORMED_DELEGATE_OUTPUT")

    def test_query_nonzero_delegate_returns_oma_exec_failed(self):
        self.env["OMA_FAKE_MODE"] = "nonzero"
        proc = self.run_omactl("query", "installed", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "OMA_EXEC_FAILED")

    def test_run_install_rejects_empty_package_list(self):
        proc = self.run_omactl("run", "install", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")

    def test_invalid_run_request_does_not_create_state_or_schedule_unit(self):
        isolated_state = self.root / "empty-state"
        self.env["OMACTL_STATE_DIR"] = str(isolated_state)
        proc = self.run_omactl("run", "install", "--json", "--unit", "oma-task-noop.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")
        self.assertFalse(isolated_state.exists())
        self.assertFalse(self.systemd_args.exists())

    def test_run_install_schedules_systemd_unit_with_structured_argv(self):
        hostile_pkg = "nano;touch /tmp/pwned"
        proc = self.run_omactl("run", "install", "--json", "--unit", "oma-task-new.service", "--yes", hostile_pkg)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.operation.started")
        self.assertEqual(payload["data"]["unit"], "oma-task-new.service")
        self.assertEqual(payload["data"]["operation"], "install")
        argv = json.loads(self.systemd_args.read_text(encoding="utf-8"))
        self.assertEqual(argv[-4:], [self.env["OMA_BIN"], "install", "--yes", hostile_pkg])
        self.assertNotIn("--collect", argv)

    def test_run_rejects_missing_unit_value(self):
        proc = self.run_omactl("run", "install", "--json", "--unit")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")
        self.assertFalse(self.systemd_args.exists())

    def test_run_rejects_retained_unit_collision(self):
        proc = self.run_omactl("run", "install", "--json", "--unit", "oma-task-test.service", "nano")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")

    def test_run_requires_systemctl_before_scheduling(self):
        self.remove_tool_from_path("systemctl")
        proc = self.run_omactl("run", "install", "--json", "--unit", "oma-task-nosystemctl.service", "nano")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "SYSTEMD_FAILED")
        self.assertFalse(self.systemd_args.exists())

    def test_legacy_run_still_accepts_oma_args_without_json_mode(self):
        proc = self.run_omactl("run", "install", "--yes", "nano")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("unit=oma-task-test.service", proc.stdout)

    def test_run_refresh_requires_valid_purpose(self):
        proc = self.run_omactl("run", "refresh", "--json", "--unit", "oma-task-test.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")

    def test_run_refresh_schedules_with_explicit_purpose(self):
        proc = self.run_omactl(
            "run",
            "refresh",
            "--json",
            "--unit",
            "oma-task-refresh.service",
            "--purpose",
            "check-updates",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.operation.started")
        self.assertEqual(payload["data"]["operation"], "refresh")
        self.assertEqual(payload["data"]["purpose"], "check-updates")

    def test_run_remove_schedules_package_operation(self):
        proc = self.run_omactl("run", "remove", "--json", "--unit", "oma-task-remove.service", "--yes", "nano")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["data"]["operation"], "remove")

    def test_run_upgrade_schedules_all_upgrade(self):
        proc = self.run_omactl("run", "upgrade", "--json", "--unit", "oma-task-upgrade.service", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["data"]["operation"], "upgrade")

    def test_run_upgrade_selected_preencodes_selection_before_scheduling(self):
        write_exe(
            self.bin / "python3",
            """
            #!/usr/bin/env bash
            exit 42
            """,
        )
        proc = self.run_omactl("run", "upgrade", "--json", "--unit", "oma-task-selected.service", "nano")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INTERNAL_ERROR")
        self.assertFalse(self.systemd_args.exists())
        self.assertFalse(self.systemd_args.exists())

    def test_run_upgrade_selected_reports_selection(self):
        proc = self.run_omactl("run", "upgrade", "--json", "--unit", "oma-task-selected.service", "nano")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["data"]["operation"], "upgrade")
        self.assertEqual(payload["data"]["selection"]["requested"], ["nano"])

    def test_run_json_unsupported_operation_returns_json_error(self):
        proc = self.run_omactl("run", "bogus", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNSUPPORTED_COMMAND")
        self.assertFalse(self.systemd_args.exists())

    def test_plan_group_returns_structured_unsupported_command(self):
        proc = self.run_omactl("plan", "upgrade", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNSUPPORTED_COMMAND")

    def test_status_json_maps_systemd_state(self):
        proc = self.run_omactl("status", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.unit.status")
        self.assertEqual(payload["data"]["state"], "running")
        self.assertEqual(payload["data"]["systemd"]["ActiveState"], "active")

    def test_result_json_maps_systemd_state(self):
        proc = self.run_omactl("result", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.unit.result")
        self.assertEqual(payload["data"]["state"], "running")

    def test_status_json_rejects_mismatched_invocation_record(self):
        self.env["SYSTEMD_FAKE_MODE"] = "mismatch"
        proc = self.run_omactl("status", "--json", "oma-task-test.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_UNIT")

    def test_status_json_rejects_collected_or_not_found_unit(self):
        self.env["SYSTEMD_FAKE_MODE"] = "not-found"
        proc = self.run_omactl("status", "--json", "oma-task-test.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_UNIT")

    def test_status_json_maps_failed_state(self):
        self.env["SYSTEMD_FAKE_MODE"] = "failed"
        proc = self.run_omactl("status", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["data"]["state"], "failed")

    def test_status_json_maps_inactive_empty_result_to_unknown(self):
        self.env["SYSTEMD_FAKE_MODE"] = "unknown"
        proc = self.run_omactl("status", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["data"]["state"], "unknown")

    def test_status_json_rejects_unknown_oma_task_unit(self):
        proc = self.run_omactl("status", "--json", "oma-task-unknown.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_UNIT")

    def test_status_json_rejects_non_omactl_unit_as_unknown(self):
        proc = self.run_omactl("status", "--json", "ssh.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_UNIT")

    def test_forged_non_omactl_unit_record_never_reaches_systemd_or_journal(self):
        record = Path(self.env["OMACTL_STATE_DIR"]) / "units" / "ssh.service"
        record.write_text(
            "unit=ssh.service\noperation=install\ninvocation_id=invocation-ssh.service\n",
            encoding="utf-8",
        )

        for args in [
            ("status", "--json", "ssh.service"),
            ("result", "--json", "ssh.service"),
            ("logs", "--json", "ssh.service"),
            ("cancel", "--json", "ssh.service"),
        ]:
            with self.subTest(args=args):
                self.calls.write_text("", encoding="utf-8")
                proc = self.run_omactl(*args)
                self.assertNotEqual(proc.returncode, 0)
                payload = self.load_json(proc)
                self.assertEqual(payload["error"]["code"], "UNKNOWN_UNIT")
                calls = self.calls.read_text(encoding="utf-8")
                self.assertNotIn("systemctl:", calls)
                self.assertNotIn("journalctl:", calls)

    def test_logs_json_returns_lines(self):
        proc = self.run_omactl("logs", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.unit.logs")
        self.assertEqual(payload["data"]["lines"], ["line one", "line two"])

    def test_follow_logs_closes_after_terminal_state(self):
        self.env["SYSTEMD_FAKE_MODE"] = "terminal"
        self.env["JOURNAL_FAKE_MODE"] = "follow-hang"
        proc = self.run_omactl("logs", "--json", "--follow", "oma-task-test.service", timeout=3)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(lines[0]["kind"], "omactl.unit.log-line")
        self.assertEqual(lines[0]["data"]["line"], "line one")

    def test_symlink_state_dir_is_rejected(self):
        target = self.root / "unsafe-target"
        target.mkdir()
        link = self.root / "unsafe-link"
        link.symlink_to(target, target_is_directory=True)
        self.env["OMACTL_STATE_DIR"] = str(link)
        proc = self.run_omactl("run", "install", "--json", "--unit", "oma-task-unsafe.service", "nano")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INTERNAL_ERROR")

    def test_cancel_json_returns_unit_cancel(self):
        proc = self.run_omactl("cancel", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.unit.cancel")
        self.assertEqual(payload["data"]["unit"], "oma-task-test.service")
        self.assertEqual(payload["data"]["state"], "cancelled")

    def test_invalid_unit_name_returns_invalid_arguments(self):
        proc = self.run_omactl("status", "--json", "../../bad")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")

    def test_missing_unit_returns_invalid_arguments(self):
        proc = self.run_omactl("status", "--json")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")


if __name__ == "__main__":
    unittest.main()
