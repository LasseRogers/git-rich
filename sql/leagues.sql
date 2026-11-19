-- Leagues in the match data: the seasons they span, games in all and in the last twelve months.
SELECT league,
       min(year)                                                 AS first_season,
       max(year)                                                 AS last_season,
       count(*)                                                  AS games,
       count(*) FILTER (WHERE played_at > now() - interval '1 year') AS games_last_year
FROM lol.games
GROUP BY league
ORDER BY games_last_year DESC, games DESC;
