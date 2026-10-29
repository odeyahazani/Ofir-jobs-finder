# Ofir Jobs Finder

**An engineering-focused job discovery, matching, and application-tracking platform for an early-career Electrical Engineer and Physicist.**

[Live application](https://ofir-jobs-finder.vercel.app) · [Deployment guide](docs/cloud-deployment.he.md) · [Candidate profile](docs/candidate-profile.he.md) · [Project roadmap](docs/plan.he.md)

> **Portfolio / project context:** This is a collaborative, AI-assisted software engineering project built to solve a real job-search workflow. It combines product requirements, system architecture, third-party integrations, collection reliability, data validation, and iterative UI/UX development. It should not be presented as evidence that every component was independently implemented by Ofir.

## Why this project exists

Relevant junior engineering positions can be difficult to find: they are spread across company career pages, advertised under inconsistent job titles, and often require a closer look at responsibilities rather than title alone. Ofir Jobs Finder centralizes those opportunities and helps distinguish genuinely relevant openings from unsuitable, stale, duplicate, or unverified listings.

The platform is designed around Ofir's background in **electrical engineering and physics**, with an emphasis on **systems integration, R&D, lab testing, validation, electro-optics, sensing, medical devices, and signal/image processing**. Academic laboratory and project experience is not misrepresented as industry employment.

## What it does

- **Discovers engineering jobs** from supported official company career pages and applicant-tracking systems.
- **Tracks a company database** and records source coverage, scan results, and failures rather than silently treating unreadable websites as empty.
- **Evaluates relevance** with an explainable, rule-based scoring model, using professional fit, experience level, skills, industry, location, and growth potential.
- **Separates verified and unverified findings.** A newly discovered URL is not automatically a confirmed open vacancy.
- **Tracks job and application state** in a Hebrew, right-to-left dashboard; supports CSV imports and records previously encountered opportunities.
- **Provides source and match context** for reviewing jobs rather than relying on a score alone.
- **Supports scheduled collection** with durable state, bounded retries, and restart-safe checkpoints, subject to deployment configuration.
- **Includes optional Telegram digest functionality** in the codebase; it requires credentials and deliberate activation.

## Product and technology

| Layer | Implementation |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Hebrew/RTL |
| Hosting | Vercel |
| Authentication | Google sign-in through Supabase Auth |
| Production storage | Supabase PostgreSQL, protected by Row Level Security |
| Local development | SQLite |
| Collection and matching | Python, official ATS adapters, rule-based matching |
| Automation | GitHub Actions with scheduled/manual operations |
| Tests | Python unit tests, Node tests, PGlite-based PostgreSQL/RLS tests, Playwright browser tests |
| Notifications | Optional Telegram digest |

The application avoids paid LLM and maps API dependencies. **AI-assisted development** describes the development workflow, not a claim that the live matching engine uses a large language model. Matching is currently rules-based and intentionally inspectable.

## Architecture

```text
Official company career pages / ATS
                |
                v
        Python collector
      verification + parsing
                |
                v
      Job records and events
       Supabase PostgreSQL
                |
         +------+------+
         |             |
         v             v
  Matching / status   Next.js app
  and source history  Hebrew / RTL UI
         |             |
         +------+------+
                |
                v
       Job review / tracking

GitHub Actions -> scheduled or manual cloud collection
Google OAuth   -> authenticated dashboard
Telegram       -> optional digest (if configured)
```

**Source integrity matters:** supported adapters include Greenhouse, Comeet, a dedicated Spectrum Dynamics flow, and selected official pages exposing structured job data. Unsupported JavaScript-only pages, access blocks, robots restrictions, and networking errors are reported explicitly; the collector does not bypass logins or CAPTCHA.

## Matching principles

The matching model is designed for an entry-level engineering search rather than generic keyword matching. The documented weight distribution is:

| Factor | Weight |
| --- | ---: |
| Responsibilities / professional fit | 30 |
| Experience and entry-level suitability | 25 |
| Technical skill fit | 20 |
| Industry and technology | 10 |
| Location and commute | 10 |
| Professional growth potential | 5 |
| **Total** | **100** |

Scores are guidance, **not guarantees of eligibility**. The scorer in [`collector/scoring.py`](collector/scoring.py) is a conservative rule-based implementation, not a complete natural-language requirements parser. Unknown commute or growth information does not receive full credit. Only sufficiently scored, verified, active, eligible opportunities can enter recommendations or digests; the broader view retains excluded and unverified results for inspection.

## Collection reliability and automation

The repository includes [a GitHub Actions collector workflow](.github/workflows/collector.yml), with manual operations for scanning, auditing, checking, rescoring, previewing matches, and previewing or sending digests.

The scheduled workflow wakes hourly at minute 17; database-side logic targets **08:17 and 17:17 Asia/Jerusalem** collection windows. Reliability measures include:

- Durable claims / 30-minute leases to prevent overlapping writes.
- Frozen per-window company selection (up to 20 enabled sources plus limited expansion).
- Per-company save checkpoints, bounded retries, and a 24-hour recovery horizon.
- Explicit reporting of completed, failed, skipped, and waiting-for-retry states.
- No automatic interpretation of a blocked or incomplete source as a verified empty result.

**Important operational distinction:** the workflow's scheduled job is gated behind the GitHub repository variable `ENABLE_SCHEDULED_SCANS=true`. The presence of a cron definition, or a successful workflow run, is **not proof** that a live collection occurred. Verify the variable, applied migrations, Actions logs, and run summaries before claiming operational coverage. See [scheduled collection and rollout](docs/scheduled-collection.he.md).

## Project status and known gaps

The system has a deployed web application and a working codebase for collection, matching, and tracking. A prior project snapshot reported **138 tracked companies, 419 stored job records, and only 14 of 138 companies checked**; these are historical diagnostic figures, **not current live metrics or verified active-job counts**. Check the database and scan reports for current numbers.

Areas still requiring continued validation or product work include:

- Increasing successful coverage of official company job sources, particularly unsupported and blocked sites.
- Verifying that scheduled runs performed actual scans rather than skipped wake-ups.
- Importing and reconciling existing application history where it has not yet been loaded.
- Completing notification setup if Telegram delivery is wanted.
- Improving the job-details experience, particularly an explicit, evidence-based **“Why this job matches Ofir”** explanation. Do not treat that planned enhancement as shipped without checking the application.

External chat-based job discovery and company expansion workflows can supply CSV/JSON findings, but they **do not automatically update the application solely by sharing a format**. Import and validation steps are required. See [growth setup](docs/growth-setup.he.md) and [shared discovery format](docs/chat-task-output.he.md).

## Run locally

Prerequisites: **Node.js 24+**, npm, **Python 3.12+**. The project was documented for Linux/macOS development.

```bash
git clone https://github.com/odeyahazani/Ofir-jobs-finder.git
cd Ofir-jobs-finder
npm ci
cp .env.example .env.local
npm run db:init
npm run dev
```

Access requires repository permission while the repository is private. Configure environment variables as described in [cloud deployment](docs/cloud-deployment.he.md). The local app binds to loopback; `LOCAL_DEV_MODE=1` is **development-only** and never a production authentication bypass. Do not commit `.env.local`.

Useful development commands:

```bash
npm run scan                        # Scan enabled local sources
python -m collector.cli scan --company Augury
npm run digest                      # Preview; no message sent
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Playwright's browser tests require Chromium. The test suite uses isolated fixtures; passing it does not confirm external ATS connectivity or production OAuth/Telegram setup. For production cloud collection, see `python -m collector.cloud` and the documented workflow.

## Production deployment and access control

- **Vercel** hosts the Next.js app; use `OFIR_STORAGE=supabase`, not ephemeral SQLite, in production.
- **Supabase** stores the durable production records and enforces RLS. Deployment requires the setup SQL and relevant additive migrations; follow [cloud deployment](docs/cloud-deployment.he.md) and [growth setup](docs/growth-setup.he.md).
- **Google sign-in** must have a correctly configured OAuth provider, site URL, callback, and allowed email. The web application does not require exposing a service-role key.
- **GitHub Actions** can run the separate collector with appropriate repository variables and secrets.
- **Telegram** is optional; set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` securely only if delivery is desired. Sending is intentional, not implied by deployment.

Do not commit credentials, `.local/`, application-history exports, personal candidate data, database backups, or production secrets. Production access and actual integrations must be verified independently.

## Collaboration and ownership

This repository is currently hosted under **`odeyahazani`** and is **private**. The goal is to make it a collaborative project in which Ofir can participate directly, document engineering decisions, validate changes, and contribute through branches and pull requests. Repository access or transfer of ownership must be managed explicitly in GitHub; this README does not itself change permissions.

The candidate-specific data, external integrations, and source code should be reviewed before any decision to make the repository public as a portfolio project.

## Further documentation

- [Cloud deployment and authentication](docs/cloud-deployment.he.md)
- [Reliable scheduled collection](docs/scheduled-collection.he.md)
- [Growth and discovery imports](docs/growth-setup.he.md)
- [Shared discovery format](docs/chat-task-output.he.md)
- [Candidate profile and job-search scope](docs/candidate-profile.he.md)
- [Scope and roadmap](docs/plan.he.md)

---

*Ofir Jobs Finder is a personal engineering project and job-search tool, not a commercial recruitment product.*
