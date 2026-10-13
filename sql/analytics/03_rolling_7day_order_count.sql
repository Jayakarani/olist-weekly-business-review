WITH RECURSIVE
daily AS (
  SELECT date(purchase_ts) AS order_date, COUNT(*) AS order_count
  FROM mart_order_summary
  WHERE purchase_ts IS NOT NULL
  GROUP BY date(purchase_ts)
),
date_spine(order_date) AS (
  SELECT MIN(order_date) FROM daily
  UNION ALL
  SELECT date(order_date, '+1 day') FROM date_spine
  WHERE order_date < (SELECT MAX(order_date) FROM daily)
),
dense_daily AS (
  SELECT d.order_date, COALESCE(x.order_count, 0) AS order_count
  FROM date_spine d LEFT JOIN daily x USING(order_date)
)
SELECT order_date, order_count,
       ROUND(AVG(order_count) OVER (
         ORDER BY order_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
       ), 2) AS rolling_7_calendar_day_avg
FROM dense_daily
ORDER BY order_date;
