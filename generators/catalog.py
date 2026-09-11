"""Product catalog + supplier shipments (streams 23, 24).

  app_db__products          one row per SKU: category, supplier, unit_cost, list_price
  erp__suppliers            one row per supplier (one supplier per category)
  erp__supplier_shipments   one row per supplier-week: expected vs received units

The supplier outage event (config.EVENTS: supplier_outage_2023_03) is planted here
as five weeks of zero-unit 'delayed' shipments from the paper supplier. Unit cost
is the margin substrate for prescriptive questions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators import timeline
from generators.common import in_window, make_rng

_ADJECTIVES = ["Classic", "Pro", "Eco", "Everyday", "Premium", "Compact", "Heavy-Duty",
               "Bright", "Studio", "Essential", "Executive", "Basic"]
_NOUNS = {
    "paper": ["Copy Paper Ream", "Legal Pad", "Notebook", "Sticky Notes", "Index Cards",
              "Envelopes", "Cardstock", "Printer Paper Case"],
    "writing": ["Ballpoint Pens", "Gel Pens", "Highlighters", "Markers", "Pencils",
                "Fineliners", "Whiteboard Markers", "Correction Tape"],
    "office_tech": ["Wireless Mouse", "Keyboard", "USB Hub", "Webcam", "Headset",
                    "Label Printer", "Monitor Stand", "Document Scanner"],
    "furniture": ["Task Chair", "Standing Desk", "Bookcase", "Filing Cabinet",
                  "Desk Lamp", "Mobile Pedestal", "Conference Chair"],
    "breakroom": ["Coffee Pods", "Paper Cups", "Napkins", "Tea Assortment", "Snack Box",
                  "Water Filter", "Hand Sanitizer", "Paper Towels"],
    "storage": ["Storage Bin", "Binder", "File Folders", "Desk Organizer", "Shelf Unit",
                "Hanging Files", "Magazine Holder", "Label Set"],
}
_BASE_WEEKLY_UNITS = {"paper": 9000, "writing": 6000, "office_tech": 900,
                      "furniture": 260, "breakroom": 5200, "storage": 2600}


def generate_products() -> pd.DataFrame:
    rng = make_rng(stream=23)
    supplier_for = {cat: sid for sid, (_, cat) in config.SUPPLIERS.items()}
    rows = []
    for cat, (_, _, (cost_lo, cost_hi), mk_lo, mk_hi, n_skus) in config.CATEGORIES.items():
        cost = np.round(rng.uniform(cost_lo, cost_hi, size=n_skus), 2)
        markup = rng.uniform(mk_lo, mk_hi, size=n_skus)
        price = np.floor(cost * markup) + 0.99
        # 20% of SKUs are introduced later than founding.
        late = rng.random(n_skus) < 0.20
        introduced = np.full(n_skus, np.datetime64(config.START_DATE))
        n_late = int(late.sum())
        if n_late:
            span = (np.datetime64("2023-12-31") - np.datetime64(config.START_DATE)).astype(int)
            introduced[late] = np.datetime64(config.START_DATE) + rng.integers(1, span, size=n_late).astype("timedelta64[D]")
        for i in range(n_skus):
            name = f"{_ADJECTIVES[int(rng.integers(len(_ADJECTIVES)))]} {_NOUNS[cat][i % len(_NOUNS[cat])]}"
            rows.append((f"sku_{cat[:3]}_{i + 1:03d}", name, cat, supplier_for[cat],
                         float(cost[i]), float(price[i]), introduced[i]))
    products = pd.DataFrame(rows, columns=["sku", "product_name", "category", "supplier_id",
                                           "unit_cost", "list_price", "introduced_at"])
    products["introduced_at"] = pd.to_datetime(products["introduced_at"])
    return products


def generate_suppliers() -> pd.DataFrame:
    return pd.DataFrame(
        [(sid, name, cat, pd.Timestamp(config.START_DATE)) for sid, (name, cat) in config.SUPPLIERS.items()],
        columns=["supplier_id", "supplier_name", "category", "onboarded_at"],
    )


def generate_shipments() -> pd.DataFrame:
    rng = make_rng(stream=24)
    weeks = pd.date_range(config.START_DATE, config.END_DATE, freq="W-MON")
    g = timeline.growth(weeks)
    s = timeline.seasonality(weeks, config.SEASONALITY_CONSUMER)
    outage = [ev for ev in config.EVENTS if ev["kind"] == "stockout"]
    rows = []
    for sid, (_, cat) in config.SUPPLIERS.items():
        expected = np.round(_BASE_WEEKLY_UNITS[cat] * g * s * rng.lognormal(0, 0.12, size=len(weeks))).astype(int)
        received = expected.copy()
        status = np.full(len(weeks), "received", dtype=object)
        partial = rng.random(len(weeks)) < 0.03
        received[partial] = np.round(expected[partial] * rng.uniform(0.6, 0.9, size=int(partial.sum()))).astype(int)
        status[partial] = "partial"
        received_date = weeks.values + rng.integers(0, 4, size=len(weeks)).astype("timedelta64[D]")
        for ev in outage:
            if cat in ev["effect"].get("category_share", {}):
                mask = in_window(weeks, ev["start"], ev["end"])
                received[mask] = 0
                status[mask] = "delayed"
                received_date = np.where(mask, np.datetime64("NaT"), received_date)
        for i, wk in enumerate(weeks):
            rows.append((f"shp_{sid[4:]}_{wk.strftime('%Y%m%d')}", sid, cat, wk,
                         pd.Timestamp(received_date[i]) if not pd.isna(received_date[i]) else pd.NaT,
                         int(expected[i]), int(received[i]), status[i]))
    df = pd.DataFrame(rows, columns=["shipment_id", "supplier_id", "category", "expected_date",
                                     "received_date", "units_expected", "units_received", "status"])
    df["expected_date"] = pd.to_datetime(df["expected_date"])
    df["received_date"] = pd.to_datetime(df["received_date"])
    return df


def generate() -> dict[str, pd.DataFrame]:
    return {
        "app_db__products": generate_products(),
        "erp__suppliers": generate_suppliers(),
        "erp__supplier_shipments": generate_shipments(),
    }
