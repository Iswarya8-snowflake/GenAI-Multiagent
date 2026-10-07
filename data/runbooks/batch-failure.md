# Runbook: Batch Calculation Failure

## Symptoms
- Scheduled end-of-batch calculation jobs exit with non-zero status.
- Service `calc-engine` throws error `JOB-5003`: calculation batch failure.
- Downstream reporting feeds delayed and missing settlement data.

## Likely causes
- Corrupted input record or division-by-zero during calculation aggregation.
- Out of memory (OOM) error during large batch aggregation.
- Stale database lock or dropped connection during intermediate writes.

## Diagnosis steps
1. Review `calc-engine` job logs for error `JOB-5003` and failing batch ID.
2. Inspect input batch dataset for schema anomalies or null values.
3. Check memory limits and GC pause metrics on the batch host node.

## Resolution
1. Quarantine the corrupted input record and re-queue clean batch partition.
2. Increase JVM heap space or split large batch partition into smaller chunks.
3. Trigger re-run of failed batch via `calc-engine` admin interface.

## Escalation
- Escalate to the Batch Processing / Analytics team if rerun fails on validated data.
