# Ofir Jobs Finder

Personal Hebrew/RTL job tracker for Ofir Cohen. Next.js 16 + React, Supabase storage for deployment and SQLite for local development, a standard-library Python collector, optional Google sign-in via Supabase Auth, and a Telegram daily digest. No paid LLM or maps API is required.

## Cloud deployment

Vercel is supported with `OFIR_STORAGE=supabase` and a Supabase PostgreSQL database protected by RLS. See [step-by-step cloud deployment](docs/cloud-deployment.he.md). Apply `supabase/setup.sql` with the owner email placeholder filled first. The web server uses the signed-in Google user and publishable key; no service-role key is used by the website. The durable collector runs separately with `python -m collector.cloud`, with a manual GitHub Actions workflow provided. Real Google/Supabase/Telegram operation still requires provider settings and credentials. Automatic scheduling is not activated.

## Gradual growth and shared discovery format

The authenticated website now accepts CSV/JSON findings with a preview and an unverified inbox. Users can enable or pause company monitoring. Apply `supabase/upgrade-growth.sql` to an existing installation; it preserves the configured owner and all existing data. See [growth setup](docs/growth-setup.he.md) and [the shared chat-task output format](docs/chat-task-output.he.md). A chat task is not automatically connected by sharing a format. Scheduled cloud scans are gated by the repository variable `ENABLE_SCHEDULED_SCANS=true`; until it is configured, scheduled jobs skip. Monitoring expands by at most one relevant supported source per run, scanning up to 20 of the oldest sources and respecting user opt-outs. No scheduled Telegram messages are enabled by this change.

## Development

Requirements: Node 24+, npm, Python 3.12+, Linux/macOS. Use the existing checkout; cloud tasks already have an isolated workspace, so do not create a worktree.

```bash
cd /workspace/Ofir-jobs-finder
npm ci --cache /workspace/.npm-cache
cp .env.example .env.local  # only if .env.local does not already exist
npm run db:init
npm run dev
```

The development server binds to loopback. `LOCAL_DEV_MODE=1` bypasses auth only on loopback in development, with no conflicting forwarded host. Production never permits this bypass. The initial dashboard has real imported companies and zero placeholder jobs. Python and Next share `.local/ofir.sqlite`; set the same absolute `OFIR_DB_PATH` for both if relocating it. `.env.local` is loaded by Next and the Python CLI; use simple `KEY=value` entries with quotes if needed, without interpolation or shell commands. Never commit it.

```bash
npm run scan                              # enabled companies only; failure => nonzero exit
python -m collector.cli scan --company Augury
npm run digest                            # preview only; sends nothing
python -m collector.cli import-applications /path/to/applications.csv
```

Import CSV columns: `url,status,applied_at`; `url` is a specific HTTPS job URL, `status` defaults to `applied`; allowed values are `not_applied,planned,applied,interviewing,rejected,withdrawn`. Dates are optional metadata. A malformed row rejects the whole import. Import before discovery is supported, and repeated imports are safe. Exact canonical URLs match existing jobs; unknown URLs are retained for future scans. Imports from other ATS URL aliases may require manual reconciliation; no fuzzy application history matches are inferred.

## Validation

```bash
npm test                                # Python + real PostgreSQL SQL/RLS tests (PGlite)
npm run typecheck
npm run build
npm run test:e2e
```

SQL permission tests exercise PostgreSQL via PGlite, with test Google claims and no external Supabase connection. They verify owner-only access, column restrictions, repeatable imports/syncs and durable digest reservations.

Browser tests use a separate `.local/e2e.sqlite`, test-only job fixtures and port 3100; they do not send network requests to ATS sites or Telegram. They require Chromium: the config uses `/usr/bin/chromium` when available, otherwise run `npx playwright install chromium`. Override the executable with `PLAYWRIGHT_CHROMIUM_PATH` when needed. Stop any development server first; Next development servers share a build lock. Real source connectivity is checked separately with `npm run scan` and is never inferred from fixture tests.

## Sources and limitations

All 138 rows are retained in `data/companies.json`, including original Active, priority, last-result and check-time metadata. Those values are not trusted as new checks. Eight initial sources are enabled. Source results distinguish pending, success, verified-empty (complete official API/bootstrap list only), blocked, unsupported and error; failures never close existing jobs or become zero-job results.

Greenhouse: documented public board API and application-page check. Comeet: public JSON bootstrap records and per-job validation on the official detail page, with JSON-LD fallback. Spectrum Dynamics: a dedicated public careers/detail-page adapter with application-instruction checks. Other sources can use public JobPosting JSON-LD. Only potentially eligible roles receive extra detail-page requests; other records are retained as unverified/excluded. JavaScript-only or unsupported schemas require another adapter and are explicitly reported as unsupported. HTTP/TLS verification and robots restrictions remain enabled. No scraping behind logins or CAPTCHA bypasses. New source URLs reject local/private hosts; the collector validates resolved public addresses. Managed HTTPS-proxy environments may resolve the reviewed seed/ATS hosts through the existing proxy when local DNS is unavailable; arbitrary imported hosts fail closed when public DNS cannot be verified.

The rule-based scorer is deliberately inspectable and conservative; see `collector/scoring.py`. It is not a general natural-language requirements parser. Read the gaps before applying. Academic experience is never described as industrial experience. Publication dates are separate from first seen / source updated / last verified; unknown dates stay unknown. Scores follow the supplied weights but unverified commute and growth information earn no full credit. Only verified active eligible jobs score >=70 appear in recommendations/digests. The All tab exposes excluded, unverified and closed records for review.

## Google sign-in

1. Create a Supabase project and enable the Google OAuth provider with a Google OAuth web application. Register Supabase's callback URL in Google as shown in Supabase's provider settings. Do not put the Google client secret in this repository.
2. Configure Supabase's site URL and redirect allowlist for the exact public HTTPS origin and `/auth/callback` route.
3. Set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `OFIR_ALLOWED_EMAIL` and `APP_URL` securely. The publishable key is intended to be public; no Supabase service-role key is needed. Set `LOCAL_DEV_MODE=0`.
4. Build and run. Verify a real Google login, reject a different email, and verify logged-out requests redirect to login. The server validates the user with Supabase on every protected request. A missing configuration fails closed. Authentication code alone does not establish that your provider setup works.

## Telegram and scheduling

Create a bot using BotFather and have Ofir start a conversation with it. Store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` securely; never paste them into chat or commit them. Configure an HTTPS `APP_URL` linking back to the deployed dashboard. No Telegram interaction is performed during setup or tests.

```bash
python -m collector.cli digest             # inspect preview
python -m collector.cli digest --send      # intentional real delivery, only with eligible events
```

Digests exclude familiar/applied/not-fit/unverified/stale records, cover all qualifying pending events with a count, and link the top five. One daily send reservation prevents repeat delivery. An uncertain send is not automatically retried: inspect Telegram and `digest_runs` before manually clearing a reservation. Truncation should be avoided by reasonable job title lengths; links to the dashboard provide the full list.

On the deployed host, invoke `python -m collector.scheduler` once per minute through cron/systemd with this repository as the working directory and the same environment/database. Example cron entry (adjust absolute Python path; cron does not activate virtual environments):

```cron
* * * * * cd /workspace/Ofir-jobs-finder && /absolute/path/to/python -m collector.scheduler >> /workspace/Ofir-jobs-finder/.local/scheduler.log 2>&1
```

The scheduler computes Asia/Jerusalem time itself, runs scans once at 08:00/17:00 and a digest at 18:00, with a 15-minute catch-up window, persisting daily task reservations. It does not catch up after that window or automatically retry failed/uncertain sends. The local-host scheduler is not installed by this repository; verify the host task runner and review its logs after activation. Add log rotation on the deployed host.

## Deployment and data

For Vercel, use the Supabase storage mode described above and the independent cloud collector workflow. GitHub Actions runners rebuild temporary SQLite state from Supabase and persist their results using restricted database operations; they do not rely on runner disks or caches for durable data. Never use SQLite storage on Vercel. For a single Linux host, local SQLite remains available with a persistent volume. Free service tiers are subject to current usage limits. Run `npm ci`, `npm run build`, `npm run db:init`, then `npm start` behind an HTTPS reverse proxy that preserves the public Host/Origin and forwards to loopback. Configure a process manager for Next plus the scheduler. Keep the repository and database private; candidate and application history are personal data.

Back up with SQLite's online backup API, not by copying only the live main file (WAL may contain recent writes):

```bash
python -c "from collector.store import connect; import sqlite3; source=connect(); target=sqlite3.connect('/secure/persistent/path/ofir-backup.sqlite'); source.backup(target); target.close(); source.close()"
```

Do not commit `.local/`, imported application CSVs, secrets or backups. Source discovery/network domains must be permitted in the runtime. Initially required: `boards-api.greenhouse.io`, `job-boards.greenhouse.io`, `job-boards.eu.greenhouse.io`, `boards.greenhouse.io`, `www.augury.com`, `www.comeet.com`, `www.comeet.co`, `spectrum-dynamics.com`. Google/Supabase and Telegram require their configured service hosts in the deployed network policy. A saved environment draft does not apply networking, start processes or publish the project.

See [the Hebrew scope and roadmap](docs/plan.he.md) and [candidate profile](docs/candidate-profile.he.md).
