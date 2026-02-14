"""
Secret detection for environment variables.

Scans environment variables for potential secrets using keyword+regex approach.
Based on TruffleHog/Secrets-Patterns-DB patterns with 15-20% false positive rate.
"""

import re

from src.utils.logger import Logger


# Keyword patterns to match in env var names
SECRET_KEYWORDS = [
    'API_KEY', 'APIKEY', 'API-KEY',
    'SECRET', 'SECRET_KEY',
    'PASSWORD', 'PASSWD', 'PWD',
    'TOKEN', 'ACCESS_TOKEN', 'AUTH_TOKEN',
    'PRIVATE_KEY'
]

# Safe prefixes to whitelist (testing/example values)
SAFE_PREFIXES = [
    'TEST_', 'EXAMPLE_', 'DEMO_',
    'MOCK_', 'FAKE_', 'DUMMY_'
]

# Value pattern: 16+ chars of alphanumeric/special chars
# Reduces false positives by filtering out short/simple values
SECRET_VALUE_PATTERN = re.compile(r'^[A-Za-z0-9_\-+=/.]{16,}$')


class SecretDetector:
    """
    Environment variable secret scanner.

    Uses keyword+regex approach with whitelist filtering to detect
    potential secrets in environment variables. Blocks sync by default
    with allow_secrets override.

    CRITICAL: Never logs or displays actual secret values.
    """

    def __init__(self):
        """Initialize SecretDetector with Logger instance."""
        self.logger = Logger()

    def scan(self, env_vars: dict[str, str]) -> list[dict]:
        """
        Scan environment variables for potential secrets.

        Args:
            env_vars: Dict mapping var_name -> var_value

        Returns:
            List of detection dicts with keys:
                - var_name: Environment variable name
                - keywords_matched: List of matched keywords
                - confidence: 'medium' (regex+keyword approach)
                - reason: Human-readable detection reason

            Empty list if no secrets detected.
        """
        detections = []

        for var_name, var_value in env_vars.items():
            # Skip if var has safe prefix (TEST_, EXAMPLE_, etc.)
            var_upper = var_name.upper()
            if any(var_upper.startswith(prefix) for prefix in SAFE_PREFIXES):
                continue

            # Check if var name contains any secret keyword
            matched_keywords = [
                keyword for keyword in SECRET_KEYWORDS
                if keyword in var_upper
            ]

            if not matched_keywords:
                # No secret keywords in name
                continue

            # Check if value matches complexity pattern (16+ chars)
            if not SECRET_VALUE_PATTERN.match(var_value):
                # Value too short or not complex enough
                continue

            # All checks passed - potential secret detected
            detections.append({
                "var_name": var_name,
                "keywords_matched": matched_keywords,
                "confidence": "medium",
                "reason": f"Contains keywords: {', '.join(matched_keywords)}"
            })

        return detections

    def scan_mcp_env(self, mcp_servers: dict) -> list[dict]:
        """
        Extract and scan environment variables from MCP server configs.

        Args:
            mcp_servers: Dict of MCP server configurations, each with optional 'env' dict

        Returns:
            List of detection dicts (same format as scan())
        """
        # Extract env vars from all MCP servers
        all_env_vars = {}

        for server_name, server_config in mcp_servers.items():
            if not isinstance(server_config, dict):
                continue

            env = server_config.get("env", {})
            if isinstance(env, dict):
                all_env_vars.update(env)

        # Scan extracted env vars
        return self.scan(all_env_vars)

    def should_block(self, detections: list[dict], allow_secrets: bool = False) -> bool:
        """
        Determine if sync should be blocked based on detections.

        Args:
            detections: List of detection dicts from scan()
            allow_secrets: Override flag to allow sync despite detections

        Returns:
            True if sync should be blocked (detections present and not overridden)
            False if sync should proceed
        """
        if not detections:
            return False

        if allow_secrets:
            return False

        return True

    def format_warnings(self, detections: list[dict]) -> str:
        """
        Format secret detection warnings for user output.

        CRITICAL: Never includes actual secret values in output.

        Args:
            detections: List of detection dicts from scan()

        Returns:
            Formatted warning string with variable names (values masked)
        """
        if not detections:
            return ""

        lines = []
        lines.append(f"\n⚠ Detected {len(detections)} potential secret(s) in environment variables:")

        for detection in detections:
            var_name = detection["var_name"]
            reason = detection["reason"]
            lines.append(f"  · {var_name} — {reason}")

        lines.append("\nSecrets should not be synced to target configs.")
        lines.append("Use --allow-secrets to override this warning (NOT recommended).")

        return "\n".join(lines)
