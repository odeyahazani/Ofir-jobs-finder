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
