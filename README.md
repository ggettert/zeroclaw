# chrono-free feasibility probe

Standalone experimental library and differential tests against ZeroClaw revision
cda933e6b9937deacbcc0d4d2cd7f1ae5bb4500e. Not a workspace migration or production
API. Jiff 0.2.46 handles timestamp/timezone boundaries; Croner 4.0.3 with its Jiff
backend skips shifted nonmatching spring-gap results; raw Croner remains available
for comparison. This is NOT a drop-in compatibility claim.

## Run on an approved isolated Rust 1.96 runner

```sh
bash validation/run-hosted.sh
```

Tests require TZ=America/Los_Angeles before the test process starts. The validation
script resolves a first lockfile, saves the normal/build graph separately from
oracle dev dependencies, compiles only two integration harnesses, checks nonempty
expected test counts, then executes once. No full application workspace build.

Pinned old chrono/chrono-tz/cron are dev-only oracles, so the test project's lock
will intentionally contain them. No claim of full advisory removal follows from
this probe. A first hosted resolution must capture Cargo.lock and its hash;
transitive versions are not frozen until then.

## What the assertions mean

- 8 historical timestamp cases compare exact store AutoSi/+00:00, serde AutoSi/Z,
  log milliseconds/Z, offset input and pre-epoch behavior.
- Scheduler fixtures characterize both the old result and candidate result.
  Some are intentionally different. A green characterization suite is NOT a
  green migration acceptance suite.
- The adapted candidate skips nonexistent fixed-time spring occurrences using
  Croner's complete wall-time match predicate, then resumes from the rejected
  transition instant. It retains valid boundary/wildcard and later same-day runs.
  The raw probe still demonstrates Croner's shifted-first-valid behavior.
- Fall-back behavior is deliberately unchanged. The old one-shot scheduler
  discards cron iterator fold state; a second-half query can return an earlier
  instant. The candidate does not reproduce that past-time result.
- 23 schedule fixture rows plus exhaustion/fold tests use the real old oracle;
  LA one-hour and Lord Howe half-hour transitions are covered. Library search
  limits still propagate as errors; this wrapper adds no search horizon or scan.
- No bespoke cron engine, public production signature change, or database migration.
- Leap seconds, extended years, broader parser forms, full cron grammar rejection,
  platform-local fallback and actual database integration remain outside this slice.

See tests and fixtures for exact assertions. Source/API citations, status, resource
permissions and unpublished issue-comment proposal are retained in the task report,
not in the production repository.
