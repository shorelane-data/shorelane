"""Re-derive and validate the committed seeded-event ground truth, and assert
each planted event is still detectable (so a generator change cannot silently
defuse a diagnostic trap).

    python tests/check_event_ground_truth.py
"""
from __future__ import annotations

import pathlib
import sys

from generators import dataset
from generators.event_measures import derive_event_measures, render_markdown

REPO = pathlib.Path(__file__).resolve().parent.parent
GROUND_TRUTH = REPO / "context" / "ground_truth" / "events.md"


def main() -> int:
    m = derive_event_measures(dataset.generate())
    failures: list[str] = []

    so = m["supplier_outage_2023_03"]
    share = so["paper_share_of_line_revenue_by_month"]
    if not share["2023-03"] < 0.5 * share["2023-02"]:
        failures.append("supplier outage: paper share in Mar 2023 is not < half of Feb 2023")
    if so["paper_units_received_in_window"] != 0:
        failures.append("supplier outage: paper units were received inside the window")

    pr = m["promo_back_to_business_2024_09"]
    if not pr["consumer_orders_by_month"]["2024-09"] > 1.25 * pr["consumer_orders_by_month"]["2024-08"]:
        failures.append("promo: Sep 2024 consumer orders are not > 1.25x Aug 2024")
    if not pr["consumer_aov_by_month"]["2024-09"] < pr["consumer_aov_by_month"]["2024-08"]:
        failures.append("promo: Sep 2024 AOV did not fall below Aug 2024")

    pi = m["sub_price_increase_2025_05"]
    for pid, hist in pi["gen3_price_per_seat"].items():
        prices = list(hist.values())
        if len(prices) != 2 or not prices[1] > prices[0]:
            failures.append(f"price increase: {pid} has no step-up in plan_prices")

    ch = m["enterprise_churn_2022_q4"]["renewal_outcomes"]
    if not ch["2022Q4_enterprise"]["churn_rate"] > 3 * ch["2022Q3_enterprise"]["churn_rate"]:
        failures.append("enterprise churn: Q4 2022 enterprise churn is not > 3x Q3 2022")
    if not ch["2022Q4_smb"]["churn_rate"] < 0.35:
        failures.append("enterprise churn: smb churn also spiked (event should be segment-specific)")

    ad = m["ad_spend_cut_2026_02"]
    if not ad["ad_spend_by_month"]["2026-02"] < 0.5 * ad["ad_spend_by_month"]["2026-01"]:
        failures.append("ad cut: Feb 2026 spend is not < half of Jan 2026")
    if not ad["new_customer_share_of_d2c_orders_by_month"]["2026-03"] < 0.8 * ad["new_customer_share_of_d2c_orders_by_month"]["2026-01"]:
        failures.append("ad cut: new-customer share did not fall in Mar 2026")

    if failures:
        print("Event ground truth check FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    expected = render_markdown(m)
    if not GROUND_TRUTH.is_file() or GROUND_TRUTH.read_text() != expected:
        print(f"{GROUND_TRUTH.relative_to(REPO)} does not match canonical re-derivation.\n"
              "Run: python -m generators.event_measures --output context/ground_truth/events.md")
        return 1
    print("event ground truth holds; all five seeded events remain detectable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
