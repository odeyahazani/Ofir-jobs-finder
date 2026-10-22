# Validation of the first local milestone

Validated in this cloud instance on 2026-10-22; these observations do not prove a public deployment or restoration in a new task.

- Node 24.19.0 and Python 3.12.14. Frozen `npm ci` installation and repeated database initialization succeeded.
- All 138 company rows imported, no duplicate company names; 8 selected for initial collection. Imported historical results remain separate from current scan state.
- A real scan of all 8 sources completed successfully: Alma Lasers 40, Augury 13, Eitan Medical 7, ForSight Robotics 3, H2Pro 0, Orbit Communication Systems 15, Spectrum Dynamics Medical 10, Astera Labs 177. Total 265 records, including excluded and international jobs. Zero duplicate company/source-ID pairs. A second scan did not generate duplicate new-job events.
- Seven sources returned records and one returned a verified empty official list. Public Comeet JSON bootstrap, Greenhouse read API and Spectrum's official job pages were exercised. TLS and source restrictions remained enabled.
- No current records qualify for the recommended feed (eligible, recently verified, score >=70). This is not a claim that the remaining 130 companies have no matching roles. The All tab exposes the collected records for review.
- 33 Python tests passed, covering source parsing, exclusion criteria, canonicalization, preserving feedback on rescans, reopening events, application imports, notification deduplication/failure handling, and Israeli-local scheduling. Telegram network calls in these tests were mocked; no real messages were sent.
- Four Playwright browser tests passed using an isolated test database: filtering/company search, persistence of all four feedback fields after reload, mutation validation/origin checks, and mobile layout.
- TypeScript checking and the production build passed.
- The production server was started and checked with `LOCAL_DEV_MODE=1`: unauthenticated root redirected to login (307), protected mutation returned 401, unconfigured Google login returned 503 and login rendered without job data (200). The development bypass did not apply in production.
- The local development server rendered the real database: 265 job cards on All, specific job details visible, and no horizontal overflow at a 390px mobile viewport. No data was modified by this real-data browser check.
- Digest preview ran without sending. Real notification-attempt count remained zero. Scheduling was not installed or activated.
- `install_script`, `start_skill`, allowed source domains and external-configuration requirements were saved in the environment draft. Draft save does not publish, apply runtime settings or deploy this application.

Not yet validated: real Google OAuth login/account rejection, Telegram delivery, host scheduling, persistent hosting/backups and a new-task snapshot restore. These require the chosen hosting/provider settings and secure credentials. The implementation is a working local milestone; public operation remains a later step.

## Vercel/Supabase preparation (2026-10-22)

- Next now supports Supabase PostgreSQL storage using the authenticated Google user's session. Vercel disallows the SQLite fallback and uses Supabase by default in production. No service-role key is needed by the web app.
- The SQL setup was applied to PostgreSQL through PGlite, including an owner allowlist, RLS policies and worker functions. All 11 SQL tests passed: anonymous/other-account access is denied, only the allowed Google account reads records and edits feedback, collected fields cannot be edited by that account, repeated sync/import is safe, newer cloud data wins and notification reservations persist.
- All 44 Python tests passed, including cloud snapshot restoration, preserving application progress, paginated reads, cloud digest reservations and uncertain delivery. Network delivery remains mocked in those tests.
- All 4 local browser workflow tests passed after converting the web storage API to asynchronous operations. They use the isolated SQLite test database, not the external Supabase project.
- Production build passed with `VERCEL=1 OFIR_STORAGE=supabase`. File-trace inspection verified that local databases, docs, tests and setup SQL are excluded from the server bundles.
- `supabase/setup.sql` includes a single email placeholder and seeds 138 companies. It does not contain real owner credentials, collected jobs or personal feedback. Existing local data was not removed or uploaded.
- A manual-only GitHub Actions collector workflow is prepared. It has not been executed against the user's project, and no scheduled scans or real Telegram delivery were activated.

Outstanding external checks: apply SQL to the actual Supabase project, configure Vercel variables/deploy, verify actual Google sign-in/owner restriction, migrate the retained local database and run a real cloud scan. The project's publishable key, allowed email and worker key were not available to this process during preparation; saved UI settings were not treated as failed or re-entered.
