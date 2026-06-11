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

omactl uses `systemd-run` to establish a systemd transient unit. The default
unit name is `oma-task-<timestamp>-<rand>.service`. You can modify it by passing
`--unit=<name>` in the legacy human command form or `--unit <name>` in the JSON
operation form.

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
