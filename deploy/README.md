# Hosted ClaimBack (Supabase + Modal)

```
Browser: docs/app/ (GitHub Pages) ── supabase-js ──▶ Supabase
   │  sign-in (guest or email) · reads own rows (RLS) ·      Auth, Postgres (runs, events, cases, jobs),
   │  live timeline (Realtime) · uploads to own folder       Storage (uploads, packets: private), Realtime
   │                                                              ▲ secret key, server side only
   └── HTTPS + session token ──▶ Modal app "claimback" (deploy/modal_app.py)
                                 api ─ checks the session, quotas, ownership → jobs row → spawns:
                                 start_run (agent team, ≤60 min, checkpointed on Volume "claimback-data")
                                 case_ops  (approve · upload · confirm · simulate insurer · mailbox; one at a time)
                                 poll      (cron every 2 min: mailbox safety net + heartbeat)
```

The worker keeps writing `runs/` and `casefiles/` exactly as the local CLI does (on the Modal Volume).
`claimback/cloud/bridge.py` hooks `log.emit` and `atomic_write_json` and mirrors events, run state, case
state and the finished packet to Supabase. Without `SUPABASE_URL` nothing changes locally.

## Never leaves the worker
`phi_map.json` (identifier map), raw inbound email (`inbox/*.eml`), stage outputs, all secrets.

## Safeguards in the hosted app
- Synthetic documents only: the worker refuses any document without `SYNTHETIC TEST DOCUMENT`
  (real PHI would need Supabase's HIPAA add-on with a signed BAA, Team plan or above).
- Every action re-checks that the case belongs to the caller; Storage paths must start with the caller's id.
- Approve & send stays a human click, to the case's insurer allow-list only.
- Live Claude runs are capped per user per day (`LIVE_RUNS_PER_USER`, default 2) and globally
  (`LIVE_RUNS_PER_DAY`, default 20); actions are rate-limited (`JOBS_PER_USER_PER_HOUR`, 40). Rehearsal runs are free.
- **Delete my data** removes a user's runs, cases, files and rows.

## Setup
1. Supabase: apply `supabase/migrations/*.sql`; in Authentication, allow anonymous sign-ins and add
   `https://neolorenzo.github.io/claimback/app/` to the redirect URLs.
2. Put `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` in `.env` next to the Anthropic key, then
   `python -m modal secret create claimback --from-dotenv .env --force`
3. `python -m modal deploy deploy/modal_app.py` and put the printed `api` URL, the Supabase URL and the
   publishable key in `docs/app/config.js`.
4. Merge to main: GitHub Pages serves the app at `/claimback/app/`.
