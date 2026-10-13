from pathlib import Path
import logging
import os
import sqlite3
import sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = Path(__file__).resolve().parent
RAW = BASE / "data" / "raw"
DB = BASE / "data" / "warehouse.db"
REPORTS = BASE / "reports"
LOG = BASE / "pipeline.log"

REQUIRED = {
    "olist_orders_dataset.csv": ["order_id", "customer_id", "order_status", "order_purchase_timestamp",
        "order_delivered_customer_date", "order_estimated_delivery_date"],
    "olist_order_items_dataset.csv": ["order_id", "product_id", "seller_id", "price", "freight_value"],
    "olist_order_payments_dataset.csv": ["order_id", "payment_value"],
    "olist_order_reviews_dataset.csv": ["order_id", "review_score"],
    "olist_customers_dataset.csv": ["customer_id", "customer_unique_id", "customer_state"],
    "olist_products_dataset.csv": ["product_id", "product_category_name"],
    "olist_sellers_dataset.csv": ["seller_id", "seller_state"],
    "product_category_name_translation.csv": ["product_category_name", "product_category_name_english"],
    "olist_geolocation_dataset.csv": ["geolocation_zip_code_prefix", "geolocation_state"],
}

def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG, encoding="utf-8"), logging.StreamHandler(sys.stdout)])

def validate_files():
    for filename, expected in REQUIRED.items():
        path = RAW / filename
        if not path.exists():
            raise FileNotFoundError(f"Required input file is missing: {path}. Add it to data/raw and rerun.")
        # Read header first, so missing columns fail clearly before loading.
        cols = pd.read_csv(path, nrows=0).columns.tolist()
        missing = sorted(set(expected) - set(cols))
        if missing:
            raise ValueError(f"{filename} is missing expected column(s): {', '.join(missing)}")
    logging.info("All required input files and expected columns are present.")

def read_csv(filename):
    return pd.read_csv(RAW / filename)

def load_raw(conn):
    logging.info("STEP 1/5: Loading raw CSV tables (replace semantics make reruns idempotent).")
    for filename in REQUIRED:
        df = read_csv(filename)
        table = "raw_" + filename.replace(".csv", "").replace("-", "_")
        df.to_sql(table, conn, if_exists="replace", index=False, chunksize=10000)
        logging.info("Loaded %s rows into %s", len(df), table)

def build_staging(conn):
    logging.info("STEP 2/5: Building staging tables.")
    # Staging tables are rebuilt on every run. Date parsing happens in SQL for portability.
    scripts = [
    """DROP TABLE IF EXISTS stg_orders;
       CREATE TABLE stg_orders AS
       SELECT order_id, customer_id, order_status,
              datetime(order_purchase_timestamp) AS purchase_ts,
              datetime(order_approved_at) AS approved_ts,
              datetime(order_delivered_carrier_date) AS carrier_ts,
              datetime(order_delivered_customer_date) AS delivered_ts,
              datetime(order_estimated_delivery_date) AS estimated_delivery_ts
       FROM raw_olist_orders_dataset;""",
    """DROP TABLE IF EXISTS stg_order_items;
       CREATE TABLE stg_order_items AS
       SELECT order_id, order_item_id, product_id, seller_id,
              CAST(price AS REAL) AS price, CAST(freight_value AS REAL) AS freight_value
       FROM raw_olist_order_items_dataset;""",
    """DROP TABLE IF EXISTS stg_payments;
       CREATE TABLE stg_payments AS
       SELECT order_id, payment_sequential, payment_type,
              CAST(payment_installments AS INTEGER) AS payment_installments,
              CAST(payment_value AS REAL) AS payment_value
       FROM raw_olist_order_payments_dataset;""",
    """DROP TABLE IF EXISTS stg_reviews;
       CREATE TABLE stg_reviews AS
       SELECT review_id, order_id, CAST(review_score AS INTEGER) AS review_score,
              datetime(review_creation_date) AS review_created_ts,
              datetime(review_answer_timestamp) AS review_answered_ts
       FROM raw_olist_order_reviews_dataset;""",
    """DROP TABLE IF EXISTS stg_customers;
       CREATE TABLE stg_customers AS
       SELECT customer_id, customer_unique_id, customer_state, customer_city
       FROM raw_olist_customers_dataset;""",
    """DROP TABLE IF EXISTS stg_products;
       CREATE TABLE stg_products AS
       SELECT p.product_id, p.product_category_name,
              COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category_english
       FROM raw_olist_products_dataset p
       LEFT JOIN raw_product_category_name_translation t
         ON p.product_category_name = t.product_category_name;""",
    """DROP TABLE IF EXISTS stg_sellers;
       CREATE TABLE stg_sellers AS
       SELECT seller_id, seller_state, seller_city FROM raw_olist_sellers_dataset;"""
    ]
    for script in scripts:
        conn.executescript(script)
    logging.info("Staging tables rebuilt.")

def build_mart(conn):
    logging.info("STEP 3/5: Building order-level mart.")
    conn.executescript("""
    DROP TABLE IF EXISTS mart_order_summary;
    CREATE TABLE mart_order_summary AS
    WITH item_totals AS (
      SELECT order_id, SUM(price) AS item_revenue, SUM(freight_value) AS freight_total,
             COUNT(*) AS item_count
      FROM stg_order_items GROUP BY order_id
    ),
    payment_totals AS (
      SELECT order_id, SUM(payment_value) AS payment_total
      FROM stg_payments GROUP BY order_id
    ),
    review_one AS (
      SELECT order_id, AVG(review_score) AS review_score, COUNT(*) AS review_count
      FROM stg_reviews GROUP BY order_id
    )
    SELECT o.order_id, o.customer_id, c.customer_unique_id, c.customer_state,
           o.order_status, o.purchase_ts, o.approved_ts, o.carrier_ts, o.delivered_ts,
           o.estimated_delivery_ts,
           CAST((julianday(o.delivered_ts) - julianday(o.purchase_ts)) AS REAL) AS delivery_days,
           CAST((julianday(o.delivered_ts) - julianday(o.estimated_delivery_ts)) AS REAL) AS delivery_delay_days,
           COALESCE(i.item_revenue, 0) AS item_revenue,
           COALESCE(i.freight_total, 0) AS freight_total,
           COALESCE(i.item_revenue, 0) + COALESCE(i.freight_total, 0) AS order_value,
           COALESCE(p.payment_total, 0) AS payment_total,
           COALESCE(i.item_count, 0) AS item_count,
           r.review_score, COALESCE(r.review_count, 0) AS review_count
    FROM stg_orders o
    LEFT JOIN stg_customers c ON o.customer_id = c.customer_id
    LEFT JOIN item_totals i ON o.order_id = i.order_id
    LEFT JOIN payment_totals p ON o.order_id = p.order_id
    LEFT JOIN review_one r ON o.order_id = r.order_id;
    CREATE UNIQUE INDEX IF NOT EXISTS ux_mart_order_id ON mart_order_summary(order_id);
    """)
    logging.info("Mart created: %s rows", conn.execute("SELECT COUNT(*) FROM mart_order_summary").fetchone()[0])

def run_quality_checks(conn):
    logging.info("STEP 4/5: Running SQL data-quality checks.")
    checks = [
      ("null_or_duplicate_order_id", """SELECT
        (SELECT COUNT(*) FROM stg_orders WHERE order_id IS NULL) +
        (SELECT COUNT(*) FROM (SELECT order_id FROM stg_orders GROUP BY order_id HAVING COUNT(*) > 1))"""),
      ("delivered_before_purchase", """SELECT COUNT(*) FROM stg_orders
        WHERE delivered_ts IS NOT NULL AND purchase_ts IS NOT NULL AND delivered_ts < purchase_ts"""),
      ("payment_vs_items_freight_mismatch", """SELECT COUNT(*) FROM (
        SELECT i.order_id FROM (SELECT order_id, SUM(price+freight_value) total FROM stg_order_items GROUP BY order_id) i
        JOIN (SELECT order_id, SUM(payment_value) total FROM stg_payments GROUP BY order_id) p USING(order_id)
        WHERE ABS(i.total-p.total) > 0.05)"""),
      ("orders_without_customer", """SELECT COUNT(*) FROM stg_orders o
        LEFT JOIN stg_customers c USING(customer_id) WHERE c.customer_id IS NULL"""),
      ("invalid_review_score", """SELECT COUNT(*) FROM stg_reviews WHERE review_score NOT BETWEEN 1 AND 5 OR review_score IS NULL"""),
      ("delivered_order_missing_delivery_or_estimate_date", """SELECT COUNT(*) FROM stg_orders
        WHERE order_status='delivered' AND (delivered_ts IS NULL OR estimated_delivery_ts IS NULL)"""),
      ("mart_not_one_row_per_order", """SELECT ABS((SELECT COUNT(*) FROM stg_orders) -
        (SELECT COUNT(*) FROM mart_order_summary)) +
        (SELECT COUNT(*) FROM (SELECT order_id FROM mart_order_summary GROUP BY order_id HAVING COUNT(*) > 1))""")
    ]
    failures = []
    for name, query in checks:
        count = int(conn.execute(query).fetchone()[0] or 0)
        logging.info("DQ CHECK %-42s failing_rows=%d", name, count)
        if count:
            failures.append((name, count))
    # Persist all check counts, including passing checks, for the assignment report.
    REPORTS.mkdir(exist_ok=True)
    count_map = {name: int(conn.execute(query).fetchone()[0] or 0) for name, query in checks}
    pd.DataFrame(checks, columns=["check_name", "sql"]).to_csv(REPORTS / "quality_check_definitions.csv", index=False)
    pd.DataFrame([
        {"check_name": name, "failing_rows": count_map[name],
         "status": "PASS" if count_map[name] == 0 else "FAIL", "sql": query}
        for name, query in checks
    ]).to_csv(REPORTS / "quality_check_results.csv", index=False)
    pd.DataFrame([(n, c) for n, c in failures], columns=["check_name", "failing_rows"]).to_csv(REPORTS / "quality_failures.csv", index=False)

    # Export row-level evidence for the two observed data issues, so the analyst can investigate them.
    pd.read_sql_query("""
      WITH item_totals AS (SELECT order_id, SUM(price + freight_value) AS items_plus_freight
                           FROM stg_order_items GROUP BY order_id),
           payment_totals AS (SELECT order_id, SUM(payment_value) AS payment_total
                              FROM stg_payments GROUP BY order_id)
      SELECT i.order_id, ROUND(i.items_plus_freight, 2) AS items_plus_freight,
             ROUND(p.payment_total, 2) AS payment_total,
             ROUND(p.payment_total - i.items_plus_freight, 2) AS difference
      FROM item_totals i JOIN payment_totals p USING(order_id)
      WHERE ABS(p.payment_total - i.items_plus_freight) > 0.05
      ORDER BY ABS(p.payment_total - i.items_plus_freight) DESC
    """, conn).to_csv(REPORTS / "payment_mismatch_details.csv", index=False)
    pd.read_sql_query("""
      SELECT order_id, order_status, purchase_ts, delivered_ts, estimated_delivery_ts
      FROM stg_orders
      WHERE order_status='delivered' AND (delivered_ts IS NULL OR estimated_delivery_ts IS NULL)
      ORDER BY order_id
    """, conn).to_csv(REPORTS / "delivered_orders_missing_dates.csv", index=False)

    if failures:
        detail = "; ".join(f"{n}={c}" for n, c in failures)
        # The default is deliberately strict to meet the assignment's alarm requirement.
        # An explicit diagnostic override allows analytics to run on the unchanged mart while
        # retaining the flagged rows and failure artifacts for investigation/reporting.
        if os.environ.get("ALLOW_QUALITY_FAILURES", "0").strip() == "1":
            logging.warning("DATA QUALITY ALARM OVERRIDDEN FOR DIAGNOSTIC ANALYSIS ONLY: %s. No rows were changed or dropped.", detail)
        else:
            raise RuntimeError("DATA QUALITY ALARM: one or more checks failed: " + detail +
                               ". See reports/quality_check_results.csv and row-level exception CSVs. "
                               "Investigate/flag; rows were not silently dropped. For diagnostic analytics only, "
                               "set ALLOW_QUALITY_FAILURES=1 explicitly; the default remains fail-fast.")

def run_analytics(conn):
    logging.info("STEP 5/5: Running SQL analytics and creating charts.")
    REPORTS.mkdir(exist_ok=True)
    for path in sorted((BASE / "sql" / "analytics").glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        df = pd.read_sql_query(sql, conn)
        out = REPORTS / f"{path.stem}.csv"
        df.to_csv(out, index=False)
        logging.info("Saved %s (%s rows)", out.name, len(df))
    monthly = pd.read_sql_query("""
      SELECT substr(purchase_ts,1,7) month, SUM(order_value) revenue
      FROM mart_order_summary WHERE order_status='delivered' AND purchase_ts IS NOT NULL
      GROUP BY substr(purchase_ts,1,7) ORDER BY month
    """, conn)
    if not monthly.empty:
        plt.figure(figsize=(9, 4.8)); plt.plot(monthly["month"], monthly["revenue"], marker="o")
        plt.title("Monthly Delivered Order Value"); plt.xlabel("Purchase month"); plt.ylabel("Item price + freight")
        plt.xticks(rotation=45, ha="right"); plt.tight_layout(); plt.savefig(REPORTS / "monthly_revenue.png", dpi=150); plt.close()
    reviews = pd.read_sql_query("SELECT CAST(review_score AS INTEGER) score, COUNT(*) n FROM stg_reviews GROUP BY score ORDER BY score", conn)
    if not reviews.empty:
        plt.figure(figsize=(7, 4.5)); plt.bar(reviews["score"].astype(str), reviews["n"])
        plt.title("Review Score Distribution"); plt.xlabel("Review score"); plt.ylabel("Number of reviews")
        plt.tight_layout(); plt.savefig(REPORTS / "review_distribution.png", dpi=150); plt.close()
    delay = pd.read_sql_query("""SELECT CAST(ROUND(delivery_delay_days) AS INTEGER) delay_days,
        AVG(review_score) avg_review, COUNT(*) orders FROM mart_order_summary
        WHERE order_status='delivered' AND delivery_delay_days IS NOT NULL AND review_score IS NOT NULL
        GROUP BY CAST(ROUND(delivery_delay_days) AS INTEGER) HAVING COUNT(*) >= 20
        ORDER BY delay_days""", conn)
    if not delay.empty:
        plt.figure(figsize=(8, 4.8)); plt.scatter(delay["delay_days"], delay["avg_review"], s=delay["orders"].clip(upper=500))
        plt.title("Delivery Delay vs Average Review Score"); plt.xlabel("Days vs estimated date (negative = early)")
        plt.ylabel("Average review score"); plt.tight_layout(); plt.savefig(REPORTS / "delay_vs_review.png", dpi=150); plt.close()
    daily = pd.read_sql_query("""SELECT substr(purchase_ts,1,10) day, COUNT(*) orders
        FROM mart_order_summary WHERE purchase_ts IS NOT NULL GROUP BY substr(purchase_ts,1,10) ORDER BY day""", conn)
    if not daily.empty:
        daily["orders"] = pd.to_numeric(daily["orders"])
        daily["rolling_7d"] = daily["orders"].rolling(7, min_periods=1).mean()
        plt.figure(figsize=(9, 4.5)); plt.plot(daily["day"], daily["rolling_7d"])
        plt.title("7-Day Rolling Average of Daily Orders"); plt.xlabel("Date"); plt.ylabel("Orders (7-day average)")
        # Thin date labels to avoid an unreadable axis.
        ticks = list(range(0, len(daily), max(1, len(daily)//10)))
        plt.xticks(ticks, daily["day"].iloc[ticks], rotation=45, ha="right")
        plt.tight_layout(); plt.savefig(REPORTS / "rolling_orders.png", dpi=150); plt.close()

def main():
    setup_logging()
    try:
        validate_files()
        DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB) as conn:
            load_raw(conn)
            build_staging(conn)
            build_mart(conn)
            run_quality_checks(conn)
            run_analytics(conn)
        logging.info("SUCCESS: pipeline completed. Database: %s", DB)
    except Exception as exc:
        logging.exception("PIPELINE FAILED: %s", exc)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
