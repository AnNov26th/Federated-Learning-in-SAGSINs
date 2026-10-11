# SAGSIN Function Pages Implementation Plan

## Goal

Implement the already agreed Network, Participants, FL Training, Experiments,
and Results responsibilities. Keep the 3D Simulation and Dashboard entry points.

## File map

- `frontend/js/app.js`: route sidebar items to unique pages and preserve the
  single globe instance.
- `frontend/html/network.html`, `frontend/js/network.js`: node inventory,
  filters, details, and stored-link inventory.
- `frontend/html/participants.html`, `frontend/js/participants.js`: participant
  inventory, node creation into the FL pool, and selection/local-epoch updates.
- `frontend/html/experiments.html`, `frontend/js/experiments.js`: searchable
  experiment history and detail navigation.
- `frontend/html/results.html`, `frontend/js/results.js`: selected experiment
  metrics by round and client.
- `frontend/html/fl.html`, `frontend/js/fl.js`: keep run creation/progress and
  add clear navigation to history/results.
- `frontend/css/function-pages.css`: shared responsive styles for the four new
  data pages.
- `frontend/html/index.html`: load shared page styles for iframe pages only via
  each page's own stylesheet reference; keep root simulation styling intact.
- `backend/routers/network.py`: expose persisted network links.
- `backend/routers/participants.py`: validate participant creation and patch
  selected/local epochs.
- `backend/schemas/participant.py`: add partial-update schema.
- `backend/routers/federated_learning.py` and `backend/schemas/fl.py`: include
  saved aggregate metrics in experiment detail for Results.

## Tasks

1. [x] Implement backend link list, participant create validation/update, and
   round-metric fields in experiment details.
2. [x] Add shared page layout and independent Network/Participants pages backed by
   the real APIs, with loading, empty, error, and filter states.
3. [x] Add Experiments list and Results experiment selector/detail views; link
   records across these pages.
4. [x] Fix sidebar routing and make FL Training focus on creation/progress with
   clear links to Experiments and Results.
5. [x] Review diffs and perform non-test syntax/static checks. Do not seed fake
   rows or claim backend metrics that are not stored.

## Acceptance

- Every sidebar item opens its own responsibility; no duplicate FL routes.
- Network reads nodes/links and reports no links when none are stored.
- Participant selection and local epochs persist via API and selected nodes are
  the pool used by FL creation.
- Experiments list/detail and Results round/client tables use persisted API
  data, including aggregate metrics.
- Pages work at desktop and narrow widths, and expose loading/error/empty states.
