WITH monthly AS (
  SELECT substr(purchase_ts, 1, 7) AS month,
         SUM(order_value) AS revenue
  FROM mart_order_summary
  WHERE order_status = 'delivered' AND purchase_ts IS NOT NULL
  GROUP BY substr(purchase_ts, 1, 7)
),
with_previous AS (
  SELECT month, revenue,
         LAG(revenue) OVER (ORDER BY month) AS previous_month_revenue
  FROM monthly
)
SELECT month, revenue, previous_month_revenue,
       ROUND(100.0 * (revenue - previous_month_revenue) / NULLIF(previous_month_revenue, 0), 2) AS growth_pct
FROM with_previous
ORDER BY month;
