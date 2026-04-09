# SYSTEM_FLOW_EXPLAINED.md

## What This System Does

This project simulates the infrastructure needed to run mobile app missions safely and at scale.

A **mission** is a list of user goals (for example: search flight, then make payment).
The platform:
1. Checks if the user's app session is still valid.
2. Allocates emulator(s) from a warm pool.
3. Executes tasks with dependency rules.
4. Pauses at identity checkpoints (OTP/biometric/payment approval) when required.
5. Resumes and completes the mission.

## Service-by-Service Architecture

## 1) Emulator Service (`:8001`)

Responsibility:
- Maintain emulator pool (`warm` idle capacity + on-demand creation).
- Create/restore layered snapshots (`base`, `app`, `session`).
- Run health checks and replace unhealthy emulators.

Key behavior:
- On startup it reconciles stale records and ensures warm-pool target is met.
- `POST /emulators` allocates from warm pool first, then provisions if needed.
- `GET /emulators/{id}/status` is available for assignment-compatible status checks.

## 2) Session Service (`:8002`)

Responsibility:
- Store user/app session records.
- Track `health`, `tier` (`hot/warm/cold`), `login_method`, `snapshot_id`.
- Verify session health using mocked classifier (`alive` ~80%, `expired` ~20%).
- Keep health history events and periodic tiered checks.

Key behavior:
- `POST /users/{id}/sessions/{app}/verify` returns:
  - `re_auth_required`
  - `login_method` (when expired)
  - `snapshot_id` for faster mission allocation.

## 3) Mission Service (`:8003`)

Responsibility:
- Accept mission payload and create task graph.
- Infer sequential dependency for payment-like tasks when not explicitly provided.
- Run task state machine with observability events.

Task states:
- `queued -> allocating -> executing -> identity_gate -> completing -> done/failed`
- `re_auth_required` when session verification says login is needed.

Identity checkpoint flow:
1. Task enters `identity_gate`.
2. External caller approves via `POST /missions/{id}/tasks/{taskId}/approve`.
3. Task resumes and continues.
4. If not approved before timeout (`GATE_TIMEOUT_SECONDS`), timeout policy applies.

## End-to-End Runtime Flow (From Actual Run)

Reference run log: [RUN_OUTPUT.md](./RUN_OUTPUT.md)

Observed sequence:
1. All services healthy.
2. Sessions created for `u-demo` apps.
3. Mission submitted with two tasks:
   - task-1: search
   - task-2: complete payment
4. Mission decomposition set task-2 dependency on task-1.
5. Task-1 executed first and hit `identity_gate` (biometric).
6. Approval endpoint called; task resumed.
7. Task-1 completed (`done`).
8. Dependent task-2 started after task-1 success.
9. Mission completed with final status `done`.

## Why This Architecture Works for the Assignment

- Emulator lifecycle + warm pool + health replacement: covered.
- Session lifecycle + health history + tiered monitoring: covered.
- Mission orchestration + parallel/sequential logic + gate pause/resume: covered.
- Observability of transitions and outcomes: covered through structured task/mission transition logging and optional webhook emission.

## Important Configuration Knobs

Configured via `docker-compose.yml`:
- Session monitor intervals/freshness:
  - `HOT_CHECK_INTERVAL_SECONDS`
  - `WARM_CHECK_INTERVAL_SECONDS`
  - `REBALANCE_INTERVAL_SECONDS`
  - `HOT_FRESHNESS_HOURS`
  - `WARM_FRESHNESS_DAYS`
- Mission gate handling:
  - `GATE_TIMEOUT_SECONDS`
  - `GATE_TIMEOUT_POLICY` (`fail` or `skip`)

## Known Prototype Limits

- Emulator runtime is mocked (not real AOSP/Genymotion runtime).
- No authn/authz layer for API endpoints.
- No schema migration tool yet (current schema via SQLAlchemy `create_all`).
- Dependency inference is heuristic (keyword-based), not NLP planner-driven.
