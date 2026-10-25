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

## Incremental growth preparation (2026-10-25)

- The user reported successful Google login on the deployed site. This was not independently repeated with their account.
- The importer accepts the shared JSON/CSV format, previews records and stores external job findings as pending. The bounded direct-URL verifier checks official structured postings, source/company relationship, redirects, expiry and paused monitoring; unsupported records remain pending. It does not accept supplied scores/verification as authoritative. Company monitoring can be enabled/paused, and automatic onboarding respects explicit pauses.
- All 56 Python tests, 24 Node/PostgreSQL/import-format tests and 6 browser tests passed. Browser checks include duplicate imports, persistence, unverified status, monitoring preferences and rollback after failed feedback saves. PostgreSQL tests cover owner-only RPCs, atomic invalid-import rejection, additive upgrade repeatability and migration of queue/preferences.
- Production build passed in Vercel/Supabase mode. The importer handles a missing upgrade gracefully so existing jobs/feedback remain accessible. Production traces exclude private local data.
- A real refresh of all eight original sources completed: seven returned records and one returned an authoritative empty list. The local database now holds 266 raw records (one newly discovered); none meets the recommendation threshold. No credentials or TLS checks were bypassed. The managed HTTPS proxy was reused for reviewed hosts when local DNS was unavailable; unknown imports still require public DNS and reject private addresses.
- A private 1.8MB SQL transfer artifact was generated under ignored `.local/`, combining the additive upgrade with all retained local records. Applying it twice to PostgreSQL succeeded with exactly 138 companies/266 jobs and preserved the existing owner. It was not executed on the user's Supabase project or committed to Git.
- After the user reported the SQL Editor size rejection, the exporter was changed to produce ordered, private parts capped at 700,000 UTF-8 bytes each. The actual data produced three parts of 693,720, 694,579 and 396,062 bytes. Sequential execution and a complete retry in PGlite PostgreSQL both retained exactly 138 companies, 266 jobs, 266 events and 40 scans, with the existing owner unchanged. All 15 targeted Python cloud tests passed, including whole-record byte bounds and dependency order. These checks do not execute the files against the external Supabase project.
- The Actions schedule is gated by `ENABLE_SCHEDULED_SCANS=true`. Enabled runs use Israeli-local time, add at most one supported relevant source from the existing company pool, and scan at most 20 oldest sources. No schedule activation, real Telegram sends or automated chat-task writes were performed by the agent.
- Remaining external actions: apply the private SQL transfer (or the upgrade plus a fresh cloud scan), configure/verify collector access and activate the schedule. The chat task requires an explicitly supported authorized write capability for fully automatic delivery; a shared format alone is not a connection.

## Location display filter (2026-10-25)

- The opportunities list defaults to Israel, independently of recommendation/saved/all filters, and offers explicit abroad, location-review and all-location views. The displayed counts distinguish raw collected records from Israeli jobs. Existing application history stays visible across locations.
- Classification uses only the posting's location. Missing, unrecognized, worldwide/EMEA and mixed Israel/foreign locations require review; remote work alone does not establish an Israeli location. This is a text-based display classification, not an independent address or commuting-time verification. Recommendations additionally require an Israeli classification, including for previously scored records.
- The retained snapshot classifies as 67 Israeli, 198 abroad and one requiring location review. No records were deleted and no database migration is required for the display change.
- All four location classifier tests and seven browser tests passed, including explicit location selection, recommendation exclusion despite legacy high scores, clearing a failed search while keeping Israel selected, and mobile layout. TypeScript checking and the production build in Vercel/Supabase mode passed. The authenticated external deployment was not independently inspected.
