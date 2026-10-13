SELECT
  CASE
    WHEN delivery_delay_days < 0 THEN 'Early'
    WHEN delivery_delay_days = 0 THEN 'On estimate'
    ELSE 'Late'
  END AS delivery_timing,
  COUNT(*) AS reviewed_delivered_orders,
  ROUND(AVG(delivery_delay_days), 2) AS average_delay_days,
  ROUND(AVG(review_score), 2) AS average_review_score,
  ROUND(100.0 * SUM(CASE WHEN review_score <= 2 THEN 1 ELSE 0 END) / NULLIF(COUNT(review_score), 0), 2) AS low_review_rate_pct
FROM mart_order_summary
WHERE order_status = 'delivered'
  AND delivery_delay_days IS NOT NULL
  AND review_score IS NOT NULL
GROUP BY delivery_timing
ORDER BY CASE delivery_timing WHEN 'Early' THEN 1 WHEN 'On estimate' THEN 2 ELSE 3 END;
