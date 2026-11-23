-- Read-only against the independent monitoring Lakehouse SQL endpoint.
-- Results describe tenant state/history; keep them private.
SELECT
    [status],
    COUNT_BIG(*) AS RunCount,
    MAX(completed_at) AS LatestCompletion,
    MAX(source_calendar_max) AS LatestSourceCalendar
FROM dbo.capacity_collection_runs
GROUP BY [status];

SELECT
    COUNT_BIG(*) AS SuccessfulSnapshots,
    COUNT(DISTINCT s.capacity_id) AS ObservedCapacities,
    MIN(s.observed_at) AS FirstObserved,
    MAX(s.observed_at) AS LastObserved
FROM dbo.capacity_state_snapshots s
JOIN dbo.capacity_collection_runs r ON s.run_id = r.run_id
WHERE r.[status] = 'Succeeded';

SELECT COUNT_BIG(*) AS PersistedEvents FROM dbo.capacity_system_events;

SELECT 'duplicate_runs' AS CheckName, COUNT_BIG(*) AS FailingGroups
FROM (
    SELECT run_id FROM dbo.capacity_collection_runs
    GROUP BY run_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_snapshots', COUNT_BIG(*)
FROM (
    SELECT snapshot_id FROM dbo.capacity_state_snapshots
    GROUP BY snapshot_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'duplicate_events', COUNT_BIG(*)
FROM (
    SELECT event_id FROM dbo.capacity_system_events
    GROUP BY event_id HAVING COUNT_BIG(*) > 1
) d
UNION ALL
SELECT 'invalid_successful_runs', COUNT_BIG(*)
FROM dbo.capacity_collection_runs
WHERE [status] = 'Succeeded'
    AND (
        started_at IS NULL OR completed_at IS NULL
        OR completed_at < started_at OR window_start IS NULL OR window_end IS NULL
        OR window_start >= window_end OR source_calendar_max IS NULL
        OR snapshot_count IS NULL OR snapshot_count <> 1
        OR event_count IS NULL OR event_count < 0
        OR failure_stage IS NOT NULL OR error_type IS NOT NULL
    )
UNION ALL
SELECT 'invalid_snapshot_run_links', COUNT_BIG(*)
FROM dbo.capacity_state_snapshots s
LEFT JOIN dbo.capacity_collection_runs r ON s.run_id = r.run_id
WHERE r.run_id IS NULL OR s.capacity_id <> r.capacity_id
UNION ALL
SELECT 'invalid_successful_snapshots', COUNT_BIG(*)
FROM dbo.capacity_state_snapshots s
JOIN dbo.capacity_collection_runs r ON s.run_id = r.run_id
WHERE r.[status] = 'Succeeded'
    AND (
        s.observed_at IS NULL OR s.observed_at < r.started_at
        OR s.observed_at > r.completed_at OR s.[state] IS NULL OR s.sku IS NULL
    )
UNION ALL
SELECT 'successful_snapshot_count_mismatch', COUNT_BIG(*)
FROM dbo.capacity_collection_runs r
WHERE r.[status] = 'Succeeded'
    AND r.snapshot_count <> (
        SELECT COUNT_BIG(*) FROM dbo.capacity_state_snapshots s
        WHERE s.run_id = r.run_id
    )
UNION ALL
SELECT 'invalid_run_source_offset', COUNT_BIG(*)
FROM dbo.capacity_collection_runs
WHERE source_utc_offset_minutes NOT BETWEEN -720 AND 840
UNION ALL
SELECT 'invalid_event_source_provenance', COUNT_BIG(*)
FROM dbo.capacity_system_events
WHERE (source_event_time IS NULL AND source_utc_offset_minutes IS NOT NULL)
    OR (source_event_time IS NOT NULL AND source_utc_offset_minutes IS NULL)
    OR source_utc_offset_minutes NOT BETWEEN -720 AND 840
    OR (source_event_time IS NOT NULL
        AND TRY_CONVERT(datetimeoffset, source_event_time) IS NULL)
UNION ALL
SELECT 'invalid_event_first_observation', COUNT_BIG(*)
FROM dbo.capacity_system_events e
LEFT JOIN dbo.capacity_collection_runs r ON e.first_observed_run_id = r.run_id
WHERE r.run_id IS NULL OR e.capacity_id IS NULL OR e.capacity_id <> r.capacity_id
    OR e.event_time IS NULL OR e.event_time < r.window_start
    OR e.event_time >= r.window_end OR e.first_observed_at IS NULL
    OR e.first_observed_at < r.started_at
    OR (r.[status] = 'Succeeded' AND e.first_observed_at > r.completed_at);
