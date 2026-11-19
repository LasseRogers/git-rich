-- When each kind of data last arrived and how long ago, to see at a glance whether loading has stalled.
SELECT data, latest, date_trunc('minute', now() - latest) AS age
FROM (
              SELECT 'game played'            AS data, max(played_at)   AS latest FROM lol.games
    UNION ALL SELECT 'match data file loaded',         max(loaded_at)   FROM lol.source_files
    UNION ALL SELECT 'live odds captured',             max(captured_at) FROM core.odds_snapshots WHERE NOT backfilled
    UNION ALL SELECT 'prediction made',                max(created_at)  FROM core.predictions
    UNION ALL SELECT 'paper bet placed',               max(placed_at)   FROM core.bets WHERE mode = 'paper'
    UNION ALL SELECT 'bet settled',                    max(settled_at)  FROM core.bets
) latest_by_kind;
