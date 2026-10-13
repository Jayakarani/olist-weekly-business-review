# Olist Weekly Business Review

A small, reproducible ELT pipeline for the Olist Brazilian e-commerce dataset. It loads CSV files into SQLite raw tables, creates cleaned staging tables, builds an order-level mart, runs data-quality alarms, executes five SQL analytics queries, and creates labelled charts.

## Dataset files

The project includes all nine required Olist CSV files in `data/raw/`, including `olist_order_items_dataset.csv`. If you maintain a separate local copy, ensure all nine files are present there. The pipeline stops with a clear error if a required file or expected column is missing.

Expected files: `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_order_payments_dataset.csv`, `olist_order_reviews_dataset.csv`, `olist_customers_dataset.csv`, `olist_products_dataset.csv`, `olist_sellers_dataset.csv`, `product_category_name_translation.csv`, and `olist_geolocation_dataset.csv`.

## Requirements

- Python 3.10+
- pip

## Run on Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# If using a clean clone, place the nine dataset CSVs into data/raw first.
python run_pipeline.py
```

The SQLite database is created at `data/warehouse.db`. Logs are written to `pipeline.log`. Query outputs and charts are saved under `reports/`.

## Pipeline design

1. **Raw layer:** load CSVs to `raw_*` tables. Each run replaces raw table contents, so repeated runs do not append duplicates.
2. **Staging layer:** standardise timestamps, preserve keys, and expose consistent names.
3. **Mart layer:** `mart_order_summary`, one row per order, including item revenue, freight, payment totals, delivery timing, customer state, and review score.
4. **Quality checks:** execute all SQL checks; any failing check raises an error after printing/logging the failure count. Checks are designed to expose issues rather than silently discard data.
5. **Analytics:** execute five SQL-only queries in `sql/analytics/` and save CSV results. The 7-day rolling average uses calendar days, including days with zero orders.
6. **Charts:** monthly revenue, review-score distribution, delivery delay vs review score, and monthly order volume.

## Metric definitions

- **North Star — Successfully delivered order value:** sum of item price + freight for delivered orders. It captures completed customer value; it is not the same as accounting revenue.
- **Supporting — Delivered order rate:** delivered orders / all orders.
- **Guardrail — Low-review order rate:** orders whose average review score is 1–2 / orders with a review score. The mart averages multiple review records per order before calculating this order-level metric.
- **Supporting — On-time delivery rate:** delivered orders delivered on or before estimated delivery date / delivered orders with both dates.
- **Supporting — Repeat-customer rate:** customers with at least two distinct orders / customers with at least one order. Uses `customer_unique_id`, not `customer_id`, because a customer can have different customer IDs across orders.

## Notes on interpretation

- The Olist dataset covers historical orders, primarily 2016–2018; results describe this dataset, not current marketplace performance.
- Order-item revenue is `price`; shipping cost is `freight_value`. Payment totals may differ from item price + freight due to installments, vouchers, or data quirks, so mismatches are flagged for investigation rather than automatically corrected.
- The geolocation file can contain many rows per zip-prefix. It is loaded as raw data but not joined into the order mart to avoid multiplying rows.
- Run `python run_pipeline.py` only after all required CSVs are present.


## Handling known data-quality failures

The default `python run_pipeline.py` is fail-fast: any failed check records counts and exception details, then stops as required by the assignment. On this dataset, some payment totals may differ from item price + freight, and a small number of delivered orders may have missing delivery dates. Do not silently edit or delete these source rows. Review `reports/quality_check_results.csv`, `reports/payment_mismatch_details.csv`, and `reports/delivered_orders_missing_dates.csv`.

To generate analytics while preserving and flagging those exceptions, explicitly run **diagnostic mode** in PowerShell after activation:

```powershell
$env:ALLOW_QUALITY_FAILURES = "1"
python run_pipeline.py
Remove-Item Env:ALLOW_QUALITY_FAILURES
```

This override is for producing query outputs/charts and investigating flagged records only. The default remains strict, and the diagnostic run does not correct or drop rows. Document the failures and rationale in the report.


## Push the project to GitHub

1. Create a new empty repository on GitHub, for example `olist-weekly-business-review`. Do not add a README from the website if you already have this README locally.
2. Open PowerShell in the project root (the folder containing `run_pipeline.py`).
3. Initialize Git and commit the project files:

```powershell
git init
git add .
git status
git commit -m "Build Olist weekly business review pipeline"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/olist-weekly-business-review.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your GitHub username and use the repository URL GitHub gives you. Check `git status` before committing. The `.gitignore` excludes raw CSVs, the local SQLite database, virtual environment, logs, and generated chart/CSV outputs so the repository stays smaller; include the report PDF and source files. For a fresh clone, download the nine CSVs from the official Kaggle dataset and place them under `data/raw/` before running the pipeline.
