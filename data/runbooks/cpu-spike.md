# Runbook: CPU Spike and Thread Pool Saturation

## Symptoms
- Inbound API requests return HTTP 503 / 504 gateway timeouts.
- Service `feed-gateway` CPU utilization reaches 98-100%.
- Service `feed-gateway` logs error `FEED-7002`: thread pool saturated.

## Likely causes
- Heavy request burst exceeding gateway thread allocation.
- Blocking I/O or downstream latency causing worker threads to remain occupied.
- Spin-lock or unoptimized regex parsing on payload evaluation.

## Diagnosis steps
1. Check CPU and thread pool metrics for `feed-gateway`.
2. Inspect active thread dump to check thread states (RUNNABLE vs BLOCKED).
3. Check response time of downstream upstream dependencies.

## Resolution
1. Temporarily enable rate limiting / shedding at the edge load balancer.
2. Scale out `feed-gateway` container instances to distribute inbound connections.
3. Restart instances that remain stuck in unrecoverable thread starvation.

## Escalation
- Escalate to the API Gateway Platform team if thread exhaustion persists after scaling.
