# Storage preset browser coverage

| # | Behaviour (test name) | Category | Precondition / input | Observable outcome asserted | Tier | Status |
|---|---|---|---|---|---|---|
| P1 | persists a hosted WebDAV preset as a read-only Library source | Happy | Koofr preset points at a real loopback WebDAV server with an existing G-code file | Reload preserves provider ID and transport; connection probe succeeds; scan links an Artifact and downloads unchanged bytes; credentials remain redacted | Playwright | ✅ |

This verifies the named preset over the actual WebDAV transport. It does not
certify a hosted Koofr account, appliance firmware, or other provider families.

Validation: Chromium real-backend flow passed (1 test, 27 seconds). Frontend lint
and workspace typecheck passed. The runner uses private worktree dependencies.
