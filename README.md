# omactl
systemd-run wrap for oma package manager.

## Run tasks

```
./src/omactl run -- install --yes htop
```

Wait and Track(blocking execution):

```
./src/omactl run --wait --follow -- upgrade --yes
```

## Control and Logs

```
./src/omactl list
./src/omactl list
./src/omactl status <unit>
./src/omactl logs <unit>
./src/omactl result <unit>
./src/omactl cancel <unit>
```

## NOTE

omactl uses systemd-run to establish a systemd transient unit, the preset unit name is `oma-task-<timestamp>-<rand>`.
You can modify it by passing argument `--unit=<name>`.

## Requirements

- systemd >= 239
- bash
- oma
