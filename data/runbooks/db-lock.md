# Runbook: DB Lock Wait Timeout

## Symptoms
- Applications receive timeout errors when writing to the database.
- Service `orders-db` emits error `DB-1205`: lock wait timeout exceeded.
- Transaction queue length increases and downstream updates stall.

## Likely causes
- Long-running uncommitted read/write transactions holding row locks.
- Deadlocks caused by out-of-order table updates across concurrent threads.
- Missing index causing table scans during updates.

## Diagnosis steps
1. Check current lock contention in `orders-db`: run `SHOW ENGINE INNODB STATUS;`.
2. Identify blocking transaction IDs and client processes.
3. Inspect `orders-db` metrics for active connections and waiting queries.

## Resolution
1. Terminate the blocking transaction session holding the stale lock.
2. Restart any failed caller transaction with backoff retry.
3. If caused by a runaway batch job, pause the job until lock cleared.

## Escalation
- Escalate to the Database Engineering team if lock contention recurs within 15 minutes.
