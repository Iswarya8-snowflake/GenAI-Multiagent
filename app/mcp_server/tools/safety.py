"""Safety tools: PII / entity redactor, URL validator, and web text sanitizer."""

import ipaddress
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# The four synthetic services from PROJECT_SPEC.md
SERVICES = ["calc-engine", "feed-gateway", "orders-db", "msg-queue"]

# Error code pattern to protect: e.g. DB-1205, MQ-2041, FEED-7002, JOB-5003
ERROR_CODE_REGEX = re.compile(r"\b(?:DB|MQ|FEED|JOB)-\d{4}\b|\b[A-Z]{2,5}-\d{4}\b")

# Regex patterns for redaction
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TICKET_ID_REGEX = re.compile(r"\b(?:INC\d+|INC-\d+|TICKET-\d+|JIRA-[A-Z0-9]+)\b", re.IGNORECASE)
IPV4_REGEX = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
INTERNAL_HOST_REGEX = re.compile(r"\b[A-Za-z0-9_\-\.]+\.(?:corp|internal|local)\b", re.IGNORECASE)
TIMESTAMP_REGEX = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")
SERVICE_REGEX = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in SERVICES) + r")\b", re.IGNORECASE)

# File paths: Windows and Unix style
WIN_PATH_REGEX = re.compile(r"\b[A-Za-z]:\\[A-Za-z0-9_\-\.\\]+")
UNIX_PATH_REGEX = re.compile(r"(?:^|[\s\"'=])(\/(?:var|etc|usr|home|tmp|opt|root|app|data)\/[A-Za-z0-9_\-\.\/]+)")

# Prompt injection phrases to neutralize
INJECTION_PATTERNS = [
    re.compile(r"\b(?:ignore|disregard|forget|bypass)\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions|prompts|rules|commands)\b", re.IGNORECASE),
    re.compile(r"\b(?:system\s+prompt|new\s+system\s+instruction|override\s+system\s+rules|jailbreak)\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\s+(?:an?\s+)?unrestricted\b", re.IGNORECASE),
]


def redact(text: str) -> str:
    """
    Redact emails, ticket IDs, IP addresses, internal hostnames, file paths,
    timestamps, and service names with placeholders, while preserving error codes.
    """
    if not text:
        return ""

    # Step 1: Protect error codes with temporary placeholders
    preserved_codes = {}
    def _protect_code(match):
        token = f"__PRESERVED_ERR_CODE_{len(preserved_codes)}__"
        preserved_codes[token] = match.group(0)
        return token

    protected_text = ERROR_CODE_REGEX.sub(_protect_code, text)

    # Step 2: Redact emails
    redacted = EMAIL_REGEX.sub("[EMAIL]", protected_text)

    # Step 3: Redact ticket IDs
    redacted = TICKET_ID_REGEX.sub("[TICKET_ID]", redacted)

    # Step 4: Redact internal hostnames (.corp, .internal, .local)
    redacted = INTERNAL_HOST_REGEX.sub("[INTERNAL_HOST]", redacted)

    # Step 5: Redact IP addresses
    redacted = IPV4_REGEX.sub("[IP_ADDRESS]", redacted)

    # Step 6: Redact timestamps
    redacted = TIMESTAMP_REGEX.sub("[TIMESTAMP]", redacted)

    # Step 7: Redact file paths
    redacted = WIN_PATH_REGEX.sub("[FILE_PATH]", redacted)
    redacted = UNIX_PATH_REGEX.sub(lambda m: m.group(0).replace(m.group(1), "[FILE_PATH]"), redacted)

    # Step 8: Redact synthetic service names
    redacted = SERVICE_REGEX.sub("[SERVICE_NAME]", redacted)

    # Step 9: Restore protected error codes
    for token, original_code in preserved_codes.items():
        redacted = redacted.replace(token, original_code)

    return redacted


def is_safe_url(url: str) -> bool:
    """
    Validate that a URL is public HTTPS only. Blocks private IPs, loopbacks,
    internal domain extensions, and non-https schemes.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        hostname_lower = hostname.lower()

        # Reject loopback and internal hostname suffixes
        if hostname_lower in {"localhost", "127.0.0.1", "::1"}:
            return False
        if any(hostname_lower.endswith(sfx) for sfx in [".local", ".internal", ".corp", ".onion", ".lan"]):
            return False

        # If hostname is an IP, verify it is not private, loopback, or reserved
        try:
            ip = ipaddress.ip_address(hostname_lower)
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_multicast:
                return False
        except ValueError:
            # Hostname is a domain name, not a numeric IP
            pass

        return True
    except Exception:
        return False


def sanitize_web_text(html: str) -> str:
    """
    Strip HTML markup and neutralize prompt injection attempts.
    """
    if not html:
        return ""

    # Parse HTML and extract clean text
    soup = BeautifulSoup(html, "html.parser")
    # Remove script, style, and svg tags
    for tag in soup(["script", "style", "svg", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    # Neutralize prompt injection phrases
    for pattern in INJECTION_PATTERNS:
        text = pattern.sub("[NEUTRALIZED_PROMPT_INJECTION]", text)

    # Normalize excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()

    return text

