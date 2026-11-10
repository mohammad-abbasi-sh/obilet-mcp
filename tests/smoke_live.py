"""Daily live smoke test for obilet-mcp — no mocks, hits obilet.com.

Calls health_check() (one polite probe of the homepage) and exits 0
only when the site reports status "ok". Run by .github/workflows/
smoke.yml every day; a non-zero exit means the site is blocked/down
or the transport broke, and the workflow fails visibly.
"""
import sys

from obilet_mcp.http import health_check


def main() -> int:
    result = health_check()
    print(result)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
