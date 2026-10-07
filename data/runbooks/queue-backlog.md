# Runbook: Message Queue Consumer Lag Backlog

## Symptoms
- Processing latency spikes on downstream services.
- Service `msg-queue` reports lag alerts with error `MQ-2041`.
- Queue depth steadily increases without consumption matching publish rate.

## Likely causes
- Downstream consumer pods crashed or hung.
- Slow consumer processing due to unhandled exceptions or remote timeout.
- Sudden burst in message ingress volume exceeding consumer throughput.

## Diagnosis steps
1. Check consumer lag metrics for service `msg-queue` on active topics.
2. Inspect consumer group status to verify active consumer thread counts.
3. Review consumer service logs for unhandled errors or slow third-party calls.

## Resolution
1. Restart dead or unresponsive consumer worker instances.
2. Scale up consumer worker replicas to drain accumulated backlog.
3. If poisoned messages block partitions, route invalid payloads to dead-letter queue.

## Escalation
- Escalate to the Messaging Platform team if consumers do not recover after restart.

