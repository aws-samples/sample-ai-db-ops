# PostgreSQL DDL Tracking — Setup

The Change Feed's `database` source captures live schema changes
(ALTER / TRUNCATE / CREATE / DROP / GRANT / …) executed against the
PostgreSQL cluster. It is fed by Postgres' own statement log, exported
to CloudWatch Logs, and parsed by
`src/admin_ops/changefeed/ingest/pg_ddl.py`.

## One-time cluster setup (logging only — no data risk, reversible)

1. **Turn on DDL logging** on the cluster parameter group. `log_statement`
   is a dynamic parameter, so no reboot is required:

   ```bash
   aws rds modify-db-cluster-parameter-group \
     --db-cluster-parameter-group-name <cluster-param-group> \
     --parameters "ParameterName=log_statement,ParameterValue=ddl,ApplyMethod=immediate"
   ```

   Values: `ddl` logs schema changes only (recommended), `mod` also logs
   data-modifying statements, `all` logs everything (noisy).

2. **Export the postgresql log to CloudWatch Logs**:

   ```bash
   aws rds modify-db-cluster \
     --db-cluster-identifier <cluster-id> \
     --cloudwatch-logs-export-configuration EnableLogTypes=postgresql \
     --apply-immediately
   ```

   This creates the log group `/aws/rds/cluster/<cluster-id>/postgresql`.

## Ingestion

**Production:** a CloudWatch Logs subscription filter on the log group
invokes a Lambda that calls
`pg_ddl.handle_cloudwatch_logs_event(decoded_payload)` for each batch.
The Lambda only needs to gzip+base64-decode `awslogs.data` and hand the
dict to that function.

**Local / demo:** run the puller, which reads recent log events directly
and ingests them into the dev Change Feed:

```bash
ADMIN_DEV_BYPASS=1 .venv/bin/python scripts/ingest_pg_ddl_from_cloudwatch.py --minutes 180
```

## Privacy / redaction

The ingester stores only the DDL verb, the target object name, and the
`user@db` actor. It deliberately does **not** store client IP addresses,
ports, PIDs, or the raw log line — so no internal network identifiers
enter the Change Feed. (Verified by the redaction guard, property P14.)

## Revert

```bash
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <cluster-param-group> \
  --parameters "ParameterName=log_statement,ParameterValue=none,ApplyMethod=immediate"

aws rds modify-db-cluster \
  --db-cluster-identifier <cluster-id> \
  --cloudwatch-logs-export-configuration DisableLogTypes=postgresql \
  --apply-immediately
```
