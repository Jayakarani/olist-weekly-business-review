-- Standalone examples. The Python pipeline executes equivalent checks and raises an alarm.
SELECT 'null_order_id' AS check_name, COUNT(*) AS failing_rows
FROM stg_orders WHERE order_id IS NULL
UNION ALL
SELECT 'delivered_before_purchase', COUNT(*)
FROM stg_orders WHERE delivered_ts < purchase_ts
UNION ALL
SELECT 'orders_without_customer', COUNT(*)
FROM stg_orders o LEFT JOIN stg_customers c USING(customer_id)
WHERE c.customer_id IS NULL
UNION ALL
SELECT 'invalid_review_score', COUNT(*)
FROM stg_reviews WHERE review_score NOT BETWEEN 1 AND 5 OR review_score IS NULL;
