# omactl

systemd-run wrapper for the oma package manager.

omactl keeps oma package-management semantics in `oma` while providing a small
systemd/process boundary for GUI consumers such as aoska.

## Machine-readable API

The aoska-facing API is available with explicit `--json` flags.

```sh
./src/omactl capabilities --json
./src/omactl query installed --json
./src/omactl query upgradable --json
./src/omactl query package-detail --json oma
./src/omactl run install --json --yes htop
./src/omactl status --json oma-task-example.service
./src/omactl result --json oma-task-example.service
./src/omactl logs --json oma-task-example.service
./src/omactl cancel --json oma-task-example.service
```

All JSON document outputs use a schema-v1 envelope:

```json
{
  "schema_version": 1,
  "ok": true,
  "kind": "omactl.capabilities",
  "data": {}
}
```

Error outputs use the same envelope shape with `ok: false` and a stable
`error.code`.

omactl delegates package facts to oma. The current JSON API advertises only the
capabilities that can be implemented from these delegated oma JSON commands:

- `oma list --installed --json` with at least `name`, `architecture`, and
  `current_version`, and `branches`.
- `oma list --upgradable --json` with at least `name`, `architecture`,
  `current_version`, and `new_version`.
- `oma show --json <package>...` with at least `name`.

Planning, selected-upgrade planning capability discovery, storage, and TUM APIs are
intentionally not advertised yet. Until oma exposes the required
machine-readable data, unsupported JSON requests return an
`UNSUPPORTED_COMMAND` error envelope instead of scraping human output.

`omactl` does not provide aoska app-store search. aoska discovery/search is
catalog-driven and should consume ASMR (`aosc-os-asmr`) metadata so curated and
manual entries that are not in AOSC package repositories can appear in the store.

## Run human-oriented tasks

```sh
./src/omactl run -- install --yes htop
```

Wait and follow logs, blocking the caller:

```sh
./src/omactl run --wait --follow -- upgrade --yes
```

## Control and logs

```sh
./src/omactl list
./src/omactl status <unit>
./src/omactl logs <unit>
./src/omactl result <unit>
./src/omactl cancel <unit>
```

omactl itself is a command-line wrapper, not a long-running service unit.
Operation commands use `systemd-run` to establish a systemd transient unit. The
default unit name is `oma-task-<timestamp>-<rand>.service`. You can modify it by
passing `--unit=<name>` in the legacy human command form or `--unit <name>` in
the JSON operation form.

When called from a graphical session, `systemd-run` may ask polkit to authorize
starting the transient system unit; the desktop polkit agent is expected to
present the password prompt. Headless sessions such as SSH may not have such an
agent, so run commands can fail with a structured `SYSTEMD_FAILED` JSON error.
`capabilities --json` reports the command surface without triggering an
authorization prompt.

JSON-mode inspection, logs, and cancellation are limited to units retained in
the omactl state directory and whose current systemd `InvocationID` still
matches the retained record.

## Requirements

- systemd >= 239
- bash
- python3
- oma

## Development checks

```sh
bash -n src/omactl
python3 -m unittest discover -s tests -v
govctl check
```
