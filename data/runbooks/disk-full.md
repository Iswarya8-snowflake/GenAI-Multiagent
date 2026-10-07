# Runbook: Disk Space Exhaustion

## Symptoms
- Services log `No space left on device` (ENOSPC).
- Database write operations fail and tables switch to read-only mode.
- System agents stop logging and health checks report unhealthy status.

## Likely causes
- Unrotated log files accumulating on host root or data volume.
- Core dumps or crash dumps written to `/tmp` or var directory.
- Database WAL / transaction log retention period set too high.

## Diagnosis steps
1. Check filesystem usage: run `df -h` on the affected host or pod.
2. Locate largest directories: run `du -sh /* 2>/dev/null | sort -hr | head -n 10`.
3. Check open deleted file handles holding disk: run `lsof +L1`.

## Resolution
1. Purge or archive unrotated log files older than 7 days.
2. Truncate stale temporary files and remove old core dumps.
3. Restart process holding deleted file handles if disk space is not reclaimed.

## Escalation
- Escalate to the Cloud Infrastructure / SysOps team if persistent volume resizing is needed.

