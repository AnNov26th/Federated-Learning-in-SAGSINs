# Delay-Aware FL and Paired Comparison Design

## Goal

Add a reproducible Delay-Aware FedAvg scheduler and an auditable paired
comparison against FedAvg, then verify backend tests and the actual UI/database
flow.

## Selection policy

- Candidate pool is the selected participants for the requested scenario when
  any are selected; otherwise it is all ACTIVE nodes in that scenario.
- Reject the run before queuing if there are fewer than `client_count` ACTIVE
  candidates. Never fall back to inactive nodes.
- Snapshot candidate IDs, status, latency, bandwidth and scenario at experiment
  creation. Workers use this snapshot so queued runs remain reproducible if the
  live topology changes later.
- For each round, FedAvg samples `client_count` candidates uniformly without
  replacement using a deterministic round seed.
- For each round, Delay-Aware ranks ACTIVE candidates by modeled two-way
  communication time: `2 * latency + 2 * model_size_bits / bandwidth`, after
  applying the selected network profile. Select the lowest-time K; break ties
  by node ID.
- Store a stable partition for every candidate and derive local-training and
  dropout seeds from the global seed, round number and client ID. The two arms
  therefore share data assignment and per-client randomness.

## Paired experiment record

- `POST /api/fl/comparisons` creates FedAvg and DelayAware experiments with one
  `comparison_id`, the same candidate snapshot and common configuration.
- Persist the pair ID, common config, candidate snapshot and scheduler policy
  in each experiment's existing `config_json`; no relational schema migration
  is needed.
- `GET /api/fl/comparisons/{comparison_id}` returns the shared configuration,
  experiment summaries, per-round metrics and selected client outcomes. The
  candidate IDs and per-round client rows make the pairing auditable.
- Existing single-run detail remains backward-compatible. Legacy experiments
  with a fixed `clients` list continue to execute with that cohort.

## Round outcomes and metric semantics

- Only COMPLETED clients are aggregated. DROPPED clients incur zero
  communication wait; TIMEOUT clients wait until the configured deadline.
- Persist every selected client's outcome for an attempted round. If nobody
  completes, save an unaggregated round with the unchanged global model's test
  metrics, then fail the experiment with a clear reason.
- Keep existing metric columns. The stored `packet_loss_ratio` is currently a
  client failure ratio (timeout/dropout), so comparison responses expose an
  explicitly named `client_failure_ratio` derived from client outcomes.
- Label communication and energy as estimates. `round_duration_s` is modeled
  parallel completion time (max client local train duration plus modeled
  communication wait); experiment start/end timestamps provide actual worker
  wall-clock duration separately.

## User experience

- FL Training can start FedAvg, Delay-Aware, or one paired comparison.
- A paired run provides a direct comparison link. Results displays both runs
  over the same round axis, shared configuration/candidate pool, accuracy,
  loss, modeled completion/communication time, estimated energy, participant
  counts and client failure ratio.
- If results are still running, the comparison view polls both runs and shows
  their current statuses. Missing metrics remain unavailable rather than
  displaying fabricated zeroes.

## Verification

- Unit-test deterministic selection, ranking/ties, status filtering and
  communication-time estimation.
- Integration-test creation/detail of a paired run, shared candidate/config
  snapshots, per-round outcomes, all-client failure persistence, and result
  metric labels using isolated SQLite and a tiny deterministic dataset.
- Run the existing backend suite.
- Connect to the configured project database read-only first, then run the app
  and inspect Network, Participants, FL Training, Experiments and Results in a
  browser. Start one small paired run only after confirming the selected
  scenario and node pool; compare stored API/database results with the UI.

## Constraints

- Use existing FastAPI, SQLAlchemy, Pydantic, PyTorch and static frontend stack.
- Do not add external packages or modify existing node/participant topology
  data during UI verification.
- Never describe modeled network/energy estimates as physical measurements.
