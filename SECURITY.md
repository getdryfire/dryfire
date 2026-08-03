# Security Policy

## Supported versions

`dryfire` follows the latest release on PyPI. Security fixes land on the newest minor
version; please upgrade to the latest `dryfire` before reporting.

| Version | Supported |
| ------- | --------- |
| latest `0.3.x` | ✅ |
| older | ❌ (please upgrade) |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's **[Private Vulnerability Reporting](https://github.com/getdryfire/dryfire/security/advisories/new)**
(Security → Advisories → *Report a vulnerability*). This is enabled on the repo and keeps
the report confidential until a fix is released.

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal YAML suite or command line is ideal).
- The `dryfire` version (`dryfire --version`) and your OS / Python version.

## What to expect

- We'll acknowledge your report within a few days.
- We'll work with you on a fix and a coordinated disclosure timeline.
- With your permission, we'll credit you in the advisory once it's published.

## Scope notes

`dryfire` is a **local-first, zero-infra CLI** — no server, no database, no account, no
network calls except to the LLM provider you configure. The most relevant classes of issue:

- Handling of untrusted YAML suites / cassettes (parsing, `$ref`/env expansion).
- Leakage of provider API keys or secrets into cassettes, traces, or reports.
- Any code path that executes or evaluates untrusted input.

Thanks for helping keep dryfire and its users safe.
