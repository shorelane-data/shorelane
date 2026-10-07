"""Small synthetic contract checks for first_renewal_nrr; no warehouse or generated data reads."""
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from evals.bank.derive import DERIVERS, first_renewal_nrr  # noqa: E402

assert DERIVERS["first_renewal_nrr"] is first_renewal_nrr

customers = pd.DataFrame({
    "app_db_customer_id": ["a", "b", "c", "test"],
    "account_type": ["customer", "customer", "customer", "test"],
    "segment": ["smb", "enterprise", "smb", "smb"],
})
plans = pd.DataFrame({"plan_id": ["old"], "plan_name": ["Legacy"],
                      "plan_generation": [1], "is_current": [False]})
rows = [
    ("a0", "a", "2023-01-01", "2023-12-31", 100, None),
    ("b0", "b", "2023-12-31", "2024-12-30", 200, None),
    ("a1", "a", "2024-01-01", "2024-12-31", 150, "a0"),
    ("a2", "a", "2025-01-01", "2025-12-31", 500, "a1"),
    ("b1", "b", "2026-09-01", "2027-08-31", 900, "b0"),
    ("c0", "c", "2022-12-31", "2023-12-30", 1000, None),
    ("t0", "test", "2023-06-01", "2024-05-31", 1000, None),
]
subscriptions = pd.DataFrame(rows, columns=["subscription_id", "customer_id",
                             "term_start", "term_end", "acv", "renewed_from_subscription_id"])
subscriptions["plan_id"] = "old"
for col in ("term_start", "term_end"):
    subscriptions[col] = pd.to_datetime(subscriptions[col])
tables = {"app_db__customers": customers, "app_db__plans": plans,
          "app_db__subscriptions": subscriptions}
params = dict(start="2023-01-01", end="2023-12-31", as_of="2026-08-31")
result = first_renewal_nrr(tables, **params)
assert result.value == 0.5, result
assert result.components["initial_acv"] == 300
assert result.components["first_renewal_acv"] == 150
assert result.components["cohort_customers"] == 2
assert result.components["renewed_customers"] == 1
assert result.silent_fail["renewers_only_denominator"] == 1.5
assert result.silent_fail["all_chain_renewals"] == round((150 + 500) / 300, 4)
assert result.silent_fail["including_test_and_internal"] == round(150 / 1300, 4)


def rejects(frame, message):
    try:
        first_renewal_nrr({**tables, "app_db__subscriptions": frame}, **params)
    except ValueError as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError("Expected ValueError")


duplicate = subscriptions.loc[subscriptions.subscription_id == "a1"].copy()
duplicate["subscription_id"] = "a1_duplicate"
rejects(pd.concat([subscriptions, duplicate], ignore_index=True), "at most one")
immature = subscriptions.copy()
immature.loc[immature.subscription_id == "b0", "term_end"] = pd.Timestamp("2026-09-01")
rejects(immature, "not yet due")
ends_at_cutoff = subscriptions.copy()  # its renewal could only start after as_of
ends_at_cutoff.loc[ends_at_cutoff.subscription_id == "b0", "term_end"] = pd.Timestamp("2026-08-31")
rejects(ends_at_cutoff, "not yet due")
print("OK: date boundaries, real customers, legacy plans, zero nonrenewals, first renewal only, "
      "cutoff, duplicate links, immature cohort.")
