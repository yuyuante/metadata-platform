# EMIP Issue #9 Production Scan Performance Optimization

## Scope

Issue #9 extends Milestone-008 in PR #8 with measured production-scan
optimization. Parser behavior, metadata identity, source locations, and relation
semantics remain unchanged. No concurrency or repository redesign was added.

## Production baseline

The recursive Informatica scan used `D:\workplace\infa_fs2\xml` with
`--profile` and processed 673 files.

| Measurement | Before | After | Change |
| --- | ---: | ---: | ---: |
| Profiled total | 1,358.413 sec | 480.114 sec | -64.66% |
| Batch elapsed | 1,386.538 sec | 492.649 sec | -64.47% |
| Relation resolution | 851.586 sec | 0.409 sec | -99.95% |
| Relation persistence | 924.523 sec | 58.836 sec | -93.64% |
| Repository persistence | 1,327.529 sec | 436.441 sec | -67.11% |
| Console log size | 13.8 MB | 192 KB | -98.61% |

The optimized scan completed in approximately 8.2 minutes, satisfying the
30-percent acceptance target and the 15-minute stretch target.

## Measured hotspots and changes

The baseline's three slowest nested stages were Repository persistence,
Relation persistence, and Relation resolution. The following changes address
those measured costs:

- Build normalized parent/name and object-ID indexes once for relation endpoint
  resolution instead of repeatedly scanning all metadata objects.
- Load existing relations once and reuse an in-memory edge index during the
  persistence pass.
- Batch relation inserts with one values operation instead of issuing one
  database round trip per row.
- Throttle successful object progress messages for large scans while retaining
  the first, final, periodic, and every failure message.

Profiling now records repository lookup, object persistence, source-location
persistence, relation lookup, relation resolution, query count, round-trip
count, and source-location insert count in the existing text and stable JSON
reports.

## Correctness and idempotency

The before and after production scans reported identical repository-visible
content:

| Statistic | Before | After |
| --- | ---: | ---: |
| Files scanned/supported | 673 / 673 | 673 / 673 |
| Parser failures | 0 | 0 |
| Repository failures | 0 | 0 |
| Objects failed | 0 | 0 |
| MetadataObjects | 110,810 | 110,810 |
| Relations | 88,786 | 88,786 |
| Objects skipped | 96,296 | 96,296 |
| Objects merged | 14,514 | 14,514 |
| Cross-provider links | 2,889 | 2,889 |

The after scan was idempotent: it created no metadata or relation rows and used
one repository transaction and one commit. Structural tests assert that relation
lookup is performed once and shorthand session-child resolution uses the
prepared index; they do not rely on wall-clock thresholds.

## XML source-context blocker

Informatica source excerpts now resolve with persisted object type and complete
qualified ancestry. Duplicate names in different workflows select the correct
workflow-specific element. A same-named `SESSION` definition and
`TASKINSTANCE` select the definition for a Session object. Truly indistinguishable
duplicates remain explicit ambiguities and produce no guessed excerpt or
fabricated line number.

Production validation covered Workflow, Session, Mapping, Source Definition,
and Target Definition examples from `wf_MBAH_SYNC`, including
`s_m_MBAHSYNC_STKOUT`; each resolved to its intended XML element without an
ambiguity warning.
