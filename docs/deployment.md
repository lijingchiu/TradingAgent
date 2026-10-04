# Deployment and unattended paper trading

## What this environment currently supplies

The Codex cloud workspace is a development machine, not a verified permanent
hosting service. Publishing its prepared filesystem snapshot does not preserve
live processes, network connections, or runtime authentication. A local server
or process started during this task must not be described as a permanent public
dashboard or a durable scheduler.

On 2026-10-04, the environment configuration exposed a restricted network policy
with package-manager/GitHub Git presets. `GH_TOKEN` was present; its value was
not inspected. No Vercel, Netlify, or Cloudflare credential binding was present.
HTTPS requests to `api.github.com`, `docs.github.com`, and the candidate GitHub
Pages hostname failed with proxy CONNECT 403 before reaching those services.
These errors do not establish missing GitHub credentials or repository write
permission. Native Git reads and API administration are separate capabilities.

## Suggested durable deployment

For a low-frequency paper strategy, use GitHub Actions to run the simulator and
GitHub Pages to host an immutable static dashboard snapshot. This requires:

1. Source and workflow files committed to the repository's default branch.
2. GitHub Actions enabled, with repository write permission for the state job.
3. GitHub Pages enabled with **GitHub Actions** as its publishing source.
4. `pages: write` and `id-token: write` permissions for the deployment job.
5. Reachable approved market-data endpoints from the hosted runner.
6. A successful workflow run and a successful request to its reported page URL.

The repository may be private. Do not change its visibility as a deployment
workaround. GitHub Pages availability for private repositories depends on the
owner's plan and repository configuration. Publish only simulated balances,
positions, audit events, and backtest evidence; never publish authentication
material or confidential account data.

Save the actual `actions/deploy-pages` output `page_url` as the dashboard URL
only after deployment succeeds. A URL built from an owner and repository name
is a candidate address, not evidence of a live website.

## Scheduler requirements

A simulator job must serialize runs, persist state durably, and process each
market bar once. Commit paper state to a dedicated state branch or use another
durable store; runner disks and expiring workflow artifacts alone are not a
ledger. Record last successful update time and show stale state visibly in the
dashboard. Use explicit workflow concurrency and idempotent bar identifiers to
avoid duplicate simulated orders after retries.

GitHub Actions cron is suitable for periodic polling, not guaranteed execution
at the opening second. Official documentation says jobs can be delayed or even
dropped during high load, the shortest schedule interval is five minutes,
scheduled workflows run only from the default branch, and public repository
schedules may be disabled after 60 days without repository activity. Use a
nonzero minute and catch up only on completed data without inventing fills at
prices unavailable when an order decision was made.

An intraday strategy that needs continuous stop monitoring requires an always-on
worker or actual broker-native practice-account stop orders. A daily cron job
and a static dashboard do not provide that capability. Do not report local
simulator orders as broker practice-account orders.

## Remaining access checks

Add `api.github.com` and the verified dashboard hostname to the environment
network allowlist while preserving existing destinations. Then test the
required read-only API operation using existing authentication. Check repository
permissions, Pages support/source, and Actions settings before requesting a new
credential. The current CONNECT 403 result is a network prerequisite, not an
authentication diagnosis.

Publishing externally is authorized by the user's request for a dashboard URL,
but the deployment still depends on actual accessible hosting permissions.
Until that is established, report the local working artifact and precise
deployment blocker instead of claiming an unattended public service is active.

## Official references

- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub Actions schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

The corresponding current Markdown sources in the official `github/docs`
repository were reachable through `raw.githubusercontent.com` and were used to
verify these requirements when the rendered documentation host was blocked.
