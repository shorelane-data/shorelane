"""
Commerce generator — the v4 orchestrator for every app_db / stripe / erp / ads table.

Produces the RAW landing tables (Fivetran-shaped) whose interaction makes the
FIVE REVENUES genuinely diverge for any period, now on top of a business with
growth, seasonality, a customer lifecycle, a product catalog, subscription plan
generations, and a calendar of seeded events (config.EVENTS):

  gmv                full ticket value, incl. full price of marketplace goods, gross of refunds
  net_revenue        what Shorelane earns (marketplace -> take only), net of refunds
  recognized_revenue subscriptions recognized ratably over the term
  billed_revenue     invoiced in period (net-30 billed at order date)
  collected_cash     cash actually received in period (net-30 timing + bad debt + refunds out)

Raw tables emitted (see raw_schema/ for column contracts):
  app_db__customers, app_db__products, app_db__orders, app_db__order_lines,
  app_db__plans, app_db__plan_prices, app_db__subscriptions, app_db__invoices,
  app_db__revenue_recognition, app_db__promotions, stripe__refunds,
  erp__suppliers, erp__supplier_shipments, ads__daily_spend

Determinism: every draw uses a fixed RNG stream from config.SEED (registry in
generators/common.py). Adding a generator must use a NEW stream int.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from generators import catalog, customers, marketing, subscriptions, timeline
from generators.common import canonical_channel, make_rng


def _consumer_orders(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stream 20: dates + channel per consumer order, plus marketplace take rates."""
    n = config.N_CONSUMER_ORDERS
    n_d2c = int(round(n * config.CONSUMER_CHANNEL_MIX["d2c"]))
    n_mk = n - n_d2c
    dates = np.concatenate([timeline.draw_dates(rng, "d2c", n_d2c),
                            timeline.draw_dates(rng, "marketplace", n_mk)])
    channels = np.array(["d2c"] * n_d2c + ["marketplace"] * n_mk, dtype=object)
    order = np.lexsort((channels, dates))
    dates, channels = dates[order], channels[order]
    take_rate = np.full(n, np.nan)
    mk = channels == "marketplace"
    take_rate[mk] = rng.uniform(*config.MARKETPLACE_TAKE_RATE_RANGE, size=int(mk.sum()))
    return dates, channels, np.round(take_rate, 4)


def _order_lines(rng: np.random.Generator, dates: np.ndarray, is_test_order: np.ndarray,
                 promo_discount: np.ndarray, products: pd.DataFrame) -> pd.DataFrame:
    """Stream 26: 1..MAX lines per consumer order; category mix follows the event
    calendar (stockout), SKU must already be introduced, quantity skews low."""
    n = len(dates)
    n_lines = np.minimum(rng.geometric(config.LINES_PER_ORDER_P, size=n), config.MAX_LINES_PER_ORDER)
    n_lines[is_test_order] = 1
    order_idx = np.repeat(np.arange(n), n_lines)
    L = len(order_idx)
    line_dates = dates[order_idx]

    cats = list(config.CATEGORIES)
    cw = np.cumsum(timeline.category_weights(line_dates), axis=1)
    u_cat = rng.random(L)
    cat_idx = np.minimum((u_cat[:, None] > cw).sum(axis=1), len(cats) - 1)
    u_sku = rng.random(L)
    u_qty = rng.random(L)

    sku = np.empty(L, dtype=object)
    qty = np.empty(L, dtype=int)
    price = np.empty(L, dtype=float)
    prod = products.sort_values(["category", "introduced_at", "sku"], kind="stable")
    for ci, cat in enumerate(cats):
        m = cat_idx == ci
        if not m.any():
            continue
        p = prod[prod.category == cat]
        intro = p.introduced_at.values.astype("datetime64[D]")
        n_avail = np.maximum(np.searchsorted(intro, line_dates[m].astype("datetime64[D]"), side="right"), 1)
        pick = np.floor(u_sku[m] * n_avail).astype(int)
        sku[m] = p.sku.values[pick]
        price[m] = p.list_price.values[pick]
        qmax = config.CATEGORIES[cat][1]
        qty[m] = 1 + np.floor(qmax * u_qty[m] ** 2).astype(int)
    qty[is_test_order[order_idx]] = 1
    disc = promo_discount[order_idx]
    amount = np.round(qty * price * (1.0 - disc), 2)
    return pd.DataFrame({"order_idx": order_idx, "sku": sku, "quantity": qty,
                         "unit_price": price, "discount_pct": disc, "line_amount": amount})


def generate() -> dict[str, pd.DataFrame]:
    cat_tables = catalog.generate()
    products = cat_tables["app_db__products"]
    subs = subscriptions.generate()
    terms: pd.DataFrame = subs["terms"]

    # ---- consumer orders: dates/channels (20) -> customers (25) -> promos (27) -> lines (26)
    dates, channels, take_rate = _consumer_orders(make_rng(stream=20))
    n = len(dates)
    biz_starts = terms.term_start.values.astype("datetime64[D]")
    keys, is_new, is_internal, test_accounts = customers.assign_consumer_orders(
        dates, channels, biz_starts, terms.biz_idx.values.astype(np.int64)
    )
    rng27 = make_rng(stream=27)
    mk_tables = marketing.generate(rng27)
    promo_code = marketing.promo_attach(rng27, dates, channels)
    disc_map = {p["promo_code"]: p["discount_pct"] for p in config.PROMOTIONS}
    promo_discount = np.array([disc_map.get(c, 0.0) for c in promo_code], dtype=float)
    is_test_order = np.array([test_accounts.get(int(k), False) for k in keys])
    lines = _order_lines(make_rng(stream=26), dates, is_test_order, promo_discount, products)

    gross = np.round(lines.groupby("order_idx")["line_amount"].sum().reindex(range(n)).to_numpy(), 2)
    net = gross.copy()
    mk = channels == "marketplace"
    net[mk] = np.round(gross[mk] * take_rate[mk], 2)   # marketplace: keep only the take

    consumer = pd.DataFrame({
        "seq": np.arange(n),
        "key": keys,
        "channel": channels,
        "order_date": pd.to_datetime(dates),
        "gross_amount": gross,
        "take_rate": take_rate,
        "net_amount": net,
        "promo_code": promo_code,
        "subscription_id": None,
    })
    sub_orders = pd.DataFrame({
        "seq": np.arange(len(terms)) + n,
        "key": terms.biz_idx.values.astype(np.int64),
        "channel": "business_subscription",
        "order_date": terms.term_start.values,
        "gross_amount": terms.acv.values,
        "take_rate": np.nan,
        "net_amount": terms.acv.values,
        "promo_code": None,
        "subscription_id": terms.subscription_id.values,
    })
    orders = pd.concat([consumer, sub_orders], ignore_index=True)
    orders = orders.sort_values(["order_date", "seq"], kind="stable", ignore_index=True)
    orders["order_id"] = [f"ord_{i:07d}" for i in range(len(orders))]

    # ---- customers: creation dates, segments, account types, chronological ids (22)
    first_order = orders.groupby("key")["order_date"].min()
    first_channel = orders.sort_values(["order_date", "seq"], kind="stable").groupby("key")["channel"].first()
    created = first_order.copy()
    biz_keys = np.arange(len(subs["business_created_at"]))
    created.loc[biz_keys] = subs["business_created_at"].values
    internal_keys = [customers.KEY_INTERNAL_START + i for i in range(config.N_INTERNAL_ACCOUNTS)]
    for k in internal_keys:
        if k in created.index:
            created.loc[k] = pd.Timestamp(config.START_DATE)
    segment = pd.Series("consumer", index=created.index, dtype=object)
    segment.loc[biz_keys] = subs["business_segment"]
    account_type = pd.Series("customer", index=created.index, dtype=object)
    account_type.loc[[k for k, t in test_accounts.items() if t]] = "test"
    account_type.loc[[k for k in internal_keys if k in created.index]] = "internal"
    customers_df, key_to_id = customers.build_customer_table(created, segment, account_type, first_channel)
    orders["customer_id"] = orders["key"].map(key_to_id)

    # ---- debt #3: the 2022 channel rename. Raw rows before the rename say 'direct'.
    pre_rename = (orders.channel == "d2c") & (orders.order_date < pd.Timestamp(config.CHANNEL_RENAME_DATE))
    orders.loc[pre_rename, "channel"] = config.LEGACY_D2C_LABEL

    order_id_by_seq = pd.Series(orders.order_id.values, index=orders.seq.values)
    orders_out = orders[["order_id", "customer_id", "channel", "order_date", "gross_amount",
                         "take_rate", "net_amount", "promo_code", "subscription_id"]].copy()
    orders_out["promo_code"] = orders_out["promo_code"].astype("string")
    orders_out["subscription_id"] = orders_out["subscription_id"].astype("string")

    # ---- order lines (consumer orders only; subscriptions carry their composition
    #      in app_db__subscriptions — summing order_lines misses them: a documented trap)
    lines["order_id"] = order_id_by_seq.reindex(lines.order_idx.values).to_numpy()
    lines["created_at"] = pd.to_datetime(dates[lines.order_idx.values])
    lines = lines.sort_values(["order_id", "sku"], kind="stable", ignore_index=True)
    lines["order_line_id"] = [f"line_{i:07d}" for i in range(len(lines))]
    lines_out = lines[["order_line_id", "order_id", "sku", "quantity", "unit_price",
                       "discount_pct", "line_amount", "created_at"]]

    # ---- subscriptions table with customer + order ids
    subs_out = terms.copy()
    subs_out["customer_id"] = key_to_id.reindex(subs_out.biz_idx.values).to_numpy()
    subs_out["order_id"] = order_id_by_seq.reindex(np.arange(len(terms)) + n).to_numpy()
    subs_out = subs_out[["subscription_id", "customer_id", "plan_id", "seats", "term_start", "term_end",
                         "price_per_seat", "acv", "order_id", "renewed_from_subscription_id",
                         "status", "cancelled_at"]].reset_index(drop=True)

    # ---- Invoices: business subscriptions are net-30, some never collected (stream 2)
    subs_orders = orders_out[orders_out.channel == "business_subscription"].copy()
    rng_inv = make_rng(stream=2)
    collected_offset = np.full(len(subs_orders), config.NET_TERMS_DAYS)
    collected_offset = collected_offset + rng_inv.integers(-3, 12, size=len(subs_orders))
    bad_debt = rng_inv.random(len(subs_orders)) < config.BAD_DEBT_RATE
    billed_date = subs_orders.order_date.values
    collected_date = billed_date + collected_offset.astype("timedelta64[D]")
    collected_date = np.where(bad_debt, np.datetime64("NaT"), collected_date)
    invoices = pd.DataFrame({
        "invoice_id": [f"inv_{i:07d}" for i in range(len(subs_orders))],
        "order_id": subs_orders.order_id.values,
        "billed_date": pd.to_datetime(billed_date),
        "due_date": pd.to_datetime(billed_date + np.timedelta64(config.NET_TERMS_DAYS, "D")),
        "collected_date": pd.to_datetime(collected_date),
        "amount": subs_orders.net_amount.values,
        "is_bad_debt": bad_debt,
    })

    # ---- Revenue recognition: subscriptions ratable over the term; everything else immediate
    monthly = np.round(subs_orders.net_amount.values / config.SUBSCRIPTION_TERM_MONTHS, 2)
    rec_frames = [pd.DataFrame({
        "order_id": subs_orders.order_id.values,
        "recognition_date": (subs_orders.order_date + pd.DateOffset(months=m)).values,
        "amount": monthly,
    }) for m in range(config.SUBSCRIPTION_TERM_MONTHS)]
    non_sub = orders_out[orders_out.channel != "business_subscription"]
    rec_frames.append(pd.DataFrame({
        "order_id": non_sub.order_id.values,
        "recognition_date": non_sub.order_date.values,
        "amount": non_sub.net_amount.values,
    }))
    recognition = pd.concat(rec_frames, ignore_index=True)
    recognition["recognition_date"] = pd.to_datetime(recognition["recognition_date"])
    recognition = recognition.sort_values(["order_id", "recognition_date"], kind="stable", ignore_index=True)

    # ---- Refunds: consumer channels, lagged (stream 3)
    rng_ref = make_rng(stream=3)
    refundable = non_sub
    refund_mask = rng_ref.random(len(refundable)) < config.REFUND_RATE
    refunded = refundable[refund_mask].copy()
    lag = rng_ref.integers(*config.REFUND_LAG_DAYS_RANGE, size=len(refunded))
    refunds = pd.DataFrame({
        "refund_id": [f"ref_{i:07d}" for i in range(len(refunded))],
        "order_id": refunded.order_id.values,
        "refund_date": pd.to_datetime(refunded.order_date.values + lag.astype("timedelta64[D]")),
        "refund_amount": refunded.net_amount.values,
    })

    return {
        "app_db__customers": customers_df,
        "app_db__products": products,
        "app_db__orders": orders_out,
        "app_db__order_lines": lines_out,
        "app_db__plans": subs["plans"],
        "app_db__plan_prices": subs["prices"],
        "app_db__subscriptions": subs_out,
        "app_db__invoices": invoices,
        "app_db__revenue_recognition": recognition,
        "app_db__promotions": mk_tables["app_db__promotions"],
        "stripe__refunds": refunds,
        "erp__suppliers": cat_tables["erp__suppliers"],
        "erp__supplier_shipments": cat_tables["erp__supplier_shipments"],
        "ads__daily_spend": mk_tables["ads__daily_spend"],
    }
