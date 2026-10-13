# Data quality checks

The executable checks are embedded in `run_pipeline.py` so the pipeline can log counts and raise a blocking alarm. They cover:
1. Null or duplicate order IDs.
2. Delivery timestamp before purchase timestamp.
3. Payment total differing from item price + freight by more than R$0.05.
4. Orders without a matching customer.
5. Review score outside 1–5 or null.
6. Delivered orders missing delivery or estimated date.
7. Mart row count/uniqueness consistency.

Failures are flagged and logged; the pipeline stops rather than silently dropping or changing source rows. Payment differences need investigation because payment methods, vouchers, and source-data quirks can explain discrepancies.
