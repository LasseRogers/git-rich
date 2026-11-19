-- Odds team names from the last 30 days that aren't linked to a team, the candidates for team_aliases.csv.
SELECT name, count(*) AS events, max(start_time)::date AS latest_event
FROM (
    SELECT home_name AS name, start_time FROM core.odds_events WHERE home_team_id IS NULL
    UNION ALL
    SELECT away_name, start_time FROM core.odds_events WHERE away_team_id IS NULL
) unlinked
WHERE start_time > now() - interval '30 days'
GROUP BY name
ORDER BY latest_event DESC, events DESC;
