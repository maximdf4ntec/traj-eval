"""UrlParser — detects HTTP/HTTPS URLs.

Detection logic recognizes values that start with ``http://`` or ``https://``
and contain a valid-looking domain. URLs are atomic values with no internal
structure that needs decomposition (no sub_parameters).
"""

from __future__ import annotations

import re
from typing import Any

from trajectory_eval.models.tool import ParameterType, ToolParameter
from trajectory_eval.parsers.parameter.base import ParameterParser

# Matches http:// or https:// followed by at least a domain-like segment.
# Intentionally permissive: we only need to distinguish URLs from plain text,
# not validate RFC 3986 compliance.
_RE_URL = re.compile(
    r"^https?://[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)+",
)


def _is_url(value: str) -> bool:
    """Return True when *value* looks like an HTTP(S) URL."""
    stripped = value.strip()
    if not stripped:
        return False
    # Reject multi-line values — a single URL parameter shouldn't span lines.
    if "\n" in stripped:
        return False
    return bool(_RE_URL.match(stripped))


class UrlParser(ParameterParser):
    """Detects HTTP and HTTPS URLs.

    Produces a ToolParameter with ``detected_type=url`` and empty
    ``sub_parameters`` — URLs are atomic values with no internal structure
    that needs decomposition.
    """

    parameter_type: ParameterType = ParameterType.url

    def can_parse(self, value: Any) -> bool:
        """Return True when *value* is an HTTP or HTTPS URL."""
        if not isinstance(value, str):
            return False
        return _is_url(value)

    def parse(self, key: str, value: Any) -> ToolParameter:
        """Return a ToolParameter with detected_type=url, empty sub_parameters."""
        return ToolParameter(
            key=key,
            raw_value=value,
            detected_type=ParameterType.url,
            sub_parameters=[],
        )
