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
    path.write_text(textwrap.dedent(body), encoding="utf-8")
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
        (owned / "oma-task-test.service").write_text("operation=install\n", encoding="utf-8")
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
            if [[ "${{OMA_FAKE_MODE:-}}" == "missing-field" ]]; then
              echo '{{"name":"broken"}}'
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
              echo 'Id=oma-task-test.service'
              echo 'ActiveState=active'
              echo 'SubState=running'
              echo 'Result=success'
              echo 'ExecMainStatus=0'
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
            echo 'line one'
            echo 'line two'
            exit 0
            """,
        )

    def run_omactl(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(OMACTL), *args],
            cwd=REPO,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def load_json(self, proc: subprocess.CompletedProcess[str]):
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"stdout was not JSON: {proc.stdout!r}; stderr={proc.stderr!r}; {exc}")

    def test_capabilities_json_envelope(self):
        proc = self.run_omactl("capabilities", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "omactl.capabilities")
        self.assertIn("query.installed.v1", payload["data"]["capabilities"])
        self.assertNotIn("plan.upgrade.v1", payload["data"]["capabilities"])
        self.assertNotIn("run.upgrade.selected.v1", payload["data"]["capabilities"])

    def test_capabilities_do_not_advertise_oma_backed_queries_when_oma_missing(self):
        self.env["OMA_BIN"] = str(self.bin / "missing-oma")
        proc = self.run_omactl("capabilities", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertNotIn("query.installed.v1", payload["data"]["capabilities"])
        self.assertNotIn("run.install.v1", payload["data"]["capabilities"])

    def test_query_installed_wraps_json_lines(self):
        proc = self.run_omactl("query", "installed", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.query.installed")
        self.assertEqual([p["name"] for p in payload["data"]["packages"]], ["nano", "htop"])
        self.assertTrue(payload["data"]["packages"][0]["installed"])
        self.assertTrue(payload["data"]["packages"][1]["upgradable"])
        self.assertTrue(payload["data"]["packages"][1]["automatic"])

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

    def test_run_rejects_retained_unit_collision(self):
        proc = self.run_omactl("run", "install", "--json", "--unit", "oma-task-test.service", "nano")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")

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

    def test_status_json_rejects_unknown_oma_task_unit(self):
        proc = self.run_omactl("status", "--json", "oma-task-unknown.service")
        self.assertNotEqual(proc.returncode, 0)
        payload = self.load_json(proc)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_UNIT")

    def test_logs_json_returns_lines(self):
        proc = self.run_omactl("logs", "--json", "oma-task-test.service")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = self.load_json(proc)
        self.assertEqual(payload["kind"], "omactl.unit.logs")
        self.assertEqual(payload["data"]["lines"], ["line one", "line two"])

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
