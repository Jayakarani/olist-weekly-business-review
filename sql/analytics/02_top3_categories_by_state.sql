WITH category_revenue AS (
  SELECT m.customer_state, p.category_english,
         SUM(i.price) AS revenue
  FROM stg_orders o
  JOIN mart_order_summary m ON m.order_id = o.order_id
  JOIN stg_order_items i ON i.order_id = o.order_id
  JOIN stg_products p ON p.product_id = i.product_id
  WHERE m.customer_state IS NOT NULL
  GROUP BY m.customer_state, p.category_english
),
ranked AS (
  SELECT customer_state, category_english, revenue,
         DENSE_RANK() OVER (PARTITION BY customer_state ORDER BY revenue DESC) AS revenue_rank
  FROM category_revenue
)
SELECT customer_state, category_english, revenue, revenue_rank
FROM ranked WHERE revenue_rank <= 3
ORDER BY customer_state, revenue_rank, category_english;
