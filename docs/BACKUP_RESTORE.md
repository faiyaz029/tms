# PostgreSQL backup and restore

Backups contain customer contact information and financial records. Store them
encrypted with access limited to authorized operators, and define retention
according to the business's legal requirements. Never commit backup files.

## Create a manual backup

From the repository root, with the Compose database healthy:

```bash
mkdir -p backups
backup_file="backups/turfpool-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U turf -Fc turfpool > "$backup_file"
test -s "$backup_file"
shasum -a 256 "$backup_file"
```

Record the checksum in the protected backup system.

## Nightly cron example

This example writes to a directory outside the repository. Provision and secure
that directory before enabling the job:

```cron
0 2 * * * cd /srv/turf-pool-manager && docker compose exec -T db pg_dump -U turf -Fc turfpool > "/secure/backups/turfpool-$(date -u +\%Y\%m\%dT\%H\%M\%SZ).dump"
```

Monitor the exit status, free disk space, backup age, and off-host replication.
The example is not a substitute for encrypted storage or tested retention.

## Restore drill

Restore into a separate database first. Do not overwrite the live database for a
drill.

```bash
docker compose exec -T db createdb -U turf turfpool_restore
docker compose exec -T db pg_restore -U turf -d turfpool_restore --no-owner < backups/turfpool-example.dump
docker compose exec -T db psql -U turf -d turfpool_restore -c "SELECT version_num FROM alembic_version"
```

Verify expected table counts and sample records against an approved checklist.
After the drill, remove only the named restore database:

```bash
docker compose exec -T db dropdb -U turf --if-exists turfpool_restore
```

## Production recovery

1. Announce maintenance and stop backend writes.
2. Take a final backup of the current database before recovery.
3. Restore the selected backup to a clean database or host.
4. Run `alembic upgrade head` using the deployment's normal release process.
5. Verify health, login, booking availability, payment and expense totals, report
   snapshots, and audit history with authorized operators.
6. Re-enable writes only after the owner approves the recovery checklist.

The local Compose database credentials are demonstration credentials. Replace
them and use a managed secret store before any production deployment.
