# Runbook: TLS Certificate Expiry

## Symptoms
- Clients and services fail with SSL/TLS handshake errors (`CERT_HAS_EXPIRED`).
- Interservice RPC calls or external ingress connections terminate abruptly.
- Ingress monitoring alerts fire on invalid certificate dates.

## Likely causes
- Automatic certificate renewal cron or ACME bot failed.
- Keystore bundle was not reloaded after certificate renewal.
- Outdated root CA or intermediate certificate chain.

## Diagnosis steps
1. Inspect endpoint certificate: run `openssl s_client -connect host:port -servername host`.
2. Check certbot or renewal automation logs for failure reasons.
3. Verify certificate expiry dates on local secret mounts.

## Resolution
1. Force manual issuance and validation of new TLS certificate.
2. Update TLS secret in container vault / secret manager.
3. Reload or restart gateway ingress proxies to pick up renewed certificate.

## Escalation
- Escalate to the Security & Infrastructure team if domain validation fails.
