### Added

- \[Server API\] Quality reports are now bound to the complete effective rules
  generation they were computed from, including the inheritance source. Each
  report carries a `status` (`current`, `superseded`, or `legacy` for reports
  created before this change) and a `generation_id`. Report lists accept a
  repeatable `status` filter, and task/project/job conflict browsing is scoped
  to the current report family.

- Quality settings and requirements changes (edits, bulk additions, deletes,
  toggled inheritance, or moving a task between projects) advance an immutable
  rules version with a content fingerprint. Workers whose computation started
  under an older generation can no longer publish a mixed snapshot: stale
  task, job, or ground truth timestamps reject the publication, and the report
  is deterministically recomputed under the current generation or discarded.

- \[cvat-core\] `QualityReport` exposes `status` and `generationId`, and the
  quality reports filter accepts `status`/`includeLegacy`. The UI conflict view
  selects only the current report family, falling back to legacy reports until
  a generation-bound report exists.

### Changed

- Manual report calculation, permissions, historical report reads, report data
  and confusion matrix downloads, and legacy data-format reports keep their
  existing behavior; only one current report family per task, job, or project
  can be served as the current result regardless of concurrent or duplicate
  computation requests.
