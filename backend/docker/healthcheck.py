#!/usr/bin/env python3
"""Container healthcheck: exit 0 when ``GET <url>`` answers 2xx within the timeout.

Usage: orbit-healthcheck [URL]  (default: http://127.0.0.1:${ORBIT_API_PORT:-8000}/health)
       orbit-healthcheck worker  (http://127.0.0.1:${ORBIT_METRICS_PORT:-9464}/healthz)
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request


def _target(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1] == "worker":
        return f"http://127.0.0.1:{os.environ.get('ORBIT_METRICS_PORT', '9464')}/healthz"
    if len(argv) > 1:
        return argv[1]
    return f"http://127.0.0.1:{os.environ.get('ORBIT_API_PORT', '8000')}/health"


def main() -> int:
    url = _target(sys.argv)
    try:
        with urllib.request.urlopen(url, timeout=float(os.environ.get("ORBIT_HEALTHCHECK_TIMEOUT", "3"))) as response:
            return 0 if 200 <= response.status < 300 else 1
    except (urllib.error.URLError, OSError, ValueError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
