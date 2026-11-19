-- Teams whose name contains the argument, with the leagues they played in and their first and last game.
-- Usage: scripts/query.sh team <part of the name>
SELECT t.id, t.name,
       string_agg(DISTINCT g.league, ', ' ORDER BY g.league) AS leagues,
       min(g.played_at)::date                                AS first_game,
       max(g.played_at)::date                                AS last_game,
       count(DISTINCT g.game_id)                             AS games
FROM core.teams t
LEFT JOIN lol.team_stats s ON s.team_id = t.id
LEFT JOIN lol.games g ON g.game_id = s.game_id
WHERE t.name ILIKE '%' || :'arg' || '%'
GROUP BY t.id, t.name
ORDER BY last_game DESC NULLS LAST;
