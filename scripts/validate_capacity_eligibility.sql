-- Evidence diagnostic only, not an availability calculator.
-- Results describe tenant state/usage and must remain private.
-- Set a half-open UTC window explicitly, or use the stored-metric default below.
DECLARE @WindowEnd datetime2 = (
    SELECT DATEADD(day, 1, CAST(MAX([Date]) AS date))
    FROM FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day
);
DECLARE @WindowStart datetime2 = DATEADD(day, -14, @WindowEnd);
IF @WindowStart IS NULL OR @WindowEnd IS NULL OR @WindowStart >= @WindowEnd
    THROW 50001, 'A positive UTC window is required; metric dates are unavailable or invalid.', 1;

WITH capacities AS (
    SELECT UPPER(TRIM(CapacityId)) AS capacity_id
    FROM FUAM_Lakehouse.dbo.capacity_metrics_by_item_by_operation_by_day
    UNION SELECT capacity_id FROM dbo.capacity_state_snapshots
), snapshots AS (
    SELECT s.*, LEAD(s.observed_at) OVER (
        PARTITION BY s.capacity_id ORDER BY s.observed_at, s.snapshot_id
    ) AS next_observed_at
    FROM dbo.capacity_state_snapshots s
    JOIN dbo.capacity_collection_runs r ON s.run_id = r.run_id
    WHERE r.[status] = 'Succeeded'
)
SELECT c.capacity_id, @WindowStart AS WindowStartInclusive, @WindowEnd AS WindowEndExclusive,
    (SELECT MIN(observed_at) FROM snapshots s WHERE s.capacity_id = c.capacity_id)
        AS FirstObservedAt,
    (SELECT MAX(observed_at) FROM snapshots s WHERE s.capacity_id = c.capacity_id)
        AS LastObservedAt,
    (SELECT COUNT_BIG(*) FROM snapshots s WHERE s.capacity_id = c.capacity_id
        AND s.observed_at <= @WindowStart) AS BaselineObservationCount,
    (SELECT COUNT_BIG(*) FROM snapshots s WHERE s.capacity_id = c.capacity_id
        AND s.observed_at >= @WindowStart AND s.observed_at < @WindowEnd)
        AS WindowSnapshotCount,
    (SELECT MAX(DATEDIFF_BIG(second, s.observed_at, s.next_observed_at))
     FROM snapshots s WHERE s.capacity_id = c.capacity_id
        AND s.next_observed_at IS NOT NULL
        AND s.observed_at < @WindowEnd AND s.next_observed_at > @WindowStart)
        AS LargestIntersectingSnapshotGapSeconds,
    (SELECT MAX(source_calendar_max) FROM dbo.capacity_collection_runs r
     WHERE r.capacity_id = c.capacity_id AND r.[status] = 'Succeeded')
        AS LatestSourceCalendar,
    (SELECT COUNT_BIG(*) FROM dbo.capacity_collection_runs r
     WHERE r.capacity_id = c.capacity_id AND r.[status] = 'Succeeded'
        AND r.window_start <= @WindowStart AND r.window_end >= @WindowEnd)
        AS EventQueryWindowsContainingPeriod,
    (SELECT COUNT_BIG(*) FROM dbo.capacity_system_events e
     WHERE e.capacity_id = c.capacity_id AND e.availability_effect IS NOT NULL
        AND e.event_time >= @WindowStart AND e.event_time < @WindowEnd)
        AS ObservedLifecycleEvents,
    CAST('Blocked_UnvalidatedLifecycleAndSKUIntervals' AS varchar(60)) AS DenominatorStatus,
    CAST(NULL AS float) AS AvailableCUSeconds,
    CAST(NULL AS float) AS BillingCapacityPercentage
FROM capacities c;
