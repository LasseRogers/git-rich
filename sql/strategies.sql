-- Paper bets per strategy: how many, how they ended, profit and average closing line value.
SELECT strategy,
       count(*)                                                AS bets,
       count(*) FILTER (WHERE result = 'pending')              AS pending,
       count(*) FILTER (WHERE result = 'won')                  AS won,
       count(*) FILTER (WHERE result = 'lost')                 AS lost,
       sum(stake) FILTER (WHERE result IN ('won', 'lost'))     AS staked,
       sum(pnl)                                                AS profit,
       round(100 * sum(pnl) / nullif(sum(stake) FILTER (WHERE result IN ('won', 'lost')), 0), 1) AS roi_pct,
       round(100 * avg(clv)::numeric, 2)                       AS avg_clv_pct
FROM core.bets
WHERE mode = 'paper'
GROUP BY strategy
ORDER BY strategy;
