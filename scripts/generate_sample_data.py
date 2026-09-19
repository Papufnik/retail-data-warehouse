"""
Generates synthetic raw data that mirrors the shape and quirks of a real
small-retail POS export pipeline: a monthly item-catalog snapshot (so the
warehouse has genuine history to build a Type-2 slowly changing dimension
from) and daily order-export folders (so the warehouse has to deal with the
same "every day's files share the same basename" problem a real SFTP-based
POS export produces).

This is synthetic data, not a real business's records. The shapes, column
names, and gotchas it reproduces (identically-named daily export files,
items changing category/price between snapshots, items being discontinued
and re-added under a new ID, a handful of voided orders and negative-total
return rows) are drawn from a real production retail data pipeline this
warehouse project is a portfolio-grade rebuild of -- see the README.

Deterministic: re-running this script with the same SEED produces byte-identical
output, which is what lets the dbt build/test suite in this repo run the same
way in CI as it does locally.
"""

import csv
import hashlib
import os
import random
from datetime import date, datetime, timedelta

SEED = 20260101
random.seed(SEED)

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
CATALOG_DIR = os.path.join(RAW_DIR, "item_catalog_snapshots")
ORDERS_DIR = os.path.join(RAW_DIR, "toast_exports")

# ---------------------------------------------------------------------------
# Reference data: categories, vendors, and a base item catalog. Deliberately
# generic/synthetic -- not any real business's actual product list.
# ---------------------------------------------------------------------------

CATEGORIES = [
    ("Jewelry", "Fine Jewelry", "Vantage Jewelry Supply Co."),
    ("Jewelry", "Fashion Jewelry", "Northline Apparel Group"),
    ("Wine & Spirits", "Red Wine", "Cascadia Beverage Imports"),
    ("Wine & Spirits", "White Wine", "Cascadia Beverage Imports"),
    ("Home Decor", "Candles", "Aurora Home Co."),
    ("Home Decor", "Tabletop", "Aurora Home Co."),
    ("Apparel", "Tops", "Northline Apparel Group"),
    ("Apparel", "Outerwear", "Northline Apparel Group"),
    ("Gifts", "Stationery", "Willow Paper Goods"),
    ("Gifts", "Kids", "Willow Paper Goods"),
    ("Accessories", "Bags", "Meridian Leather Works"),
    ("Accessories", "Scarves", "Meridian Leather Works"),
]

ADJECTIVES = ["Vintage", "Classic", "Modern", "Rustic", "Coastal", "Heritage",
              "Signature", "Everyday", "Statement", "Petite"]
NOUNS = ["Bracelet", "Necklace", "Candle", "Tumbler", "Cardigan", "Scarf",
         "Notebook", "Tote", "Vase", "Earrings", "Wrap", "Bottle"]


def make_item_name(rng):
    return f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"


def stable_id(*parts):
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


class Item:
    """A catalog item whose price/cost/category can drift snapshot to snapshot,
    same as the real Toast retail-items export does between pulls."""

    def __init__(self, item_id, name, category_group, category, supplier,
                 price, cost, active_from):
        self.item_id = item_id
        self.name = name
        self.category_group = category_group
        self.category = category
        self.supplier = supplier
        self.price = price
        self.cost = cost
        self.active_from = active_from
        self.discontinued_at = None


def build_base_catalog(n_items=140):
    items = []
    for i in range(n_items):
        group, cat, supplier = random.choice(CATEGORIES)
        cost = round(random.uniform(4, 65), 2)
        margin_target = random.uniform(1.7, 3.2)
        price = round(cost * margin_target, 2)
        items.append(Item(
            item_id=stable_id("item", i),
            name=make_item_name(random),
            category_group=group,
            category=cat,
            supplier=supplier,
            price=price,
            cost=cost,
            active_from=date(2026, 1, 1),
        ))
    return items


def write_catalog_snapshot(items, snapshot_date, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = ["item_id", "export_date", "export_filename", "name",
                  "category_group", "category", "supplier", "price", "cost",
                  "gross_margin", "barcode"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for it in items:
            if it.discontinued_at and it.discontinued_at <= snapshot_date:
                continue
            margin = round((it.price - it.cost) / it.price, 4) if it.price else None
            w.writerow({
                "item_id": it.item_id,
                "export_date": snapshot_date.isoformat() + " 09:00:00",
                "export_filename": f"retail_items_{snapshot_date:%Y%m%d}.csv",
                "name": it.name,
                "category_group": it.category_group,
                "category": it.category,
                "supplier": it.supplier,
                "price": it.price,
                "cost": it.cost,
                "gross_margin": margin,
                "barcode": stable_id("barcode", it.item_id),
            })


def drift_catalog(items, snapshot_index):
    """Mutate a handful of items between snapshots -- price changes,
    re-categorization, and the occasional discontinue-and-replace -- so the
    warehouse's Type-2 history actually has real changes to capture, the
    same way the real store's catalog does between exports."""
    if snapshot_index == 0:
        return items

    # Price/cost drift on ~15% of items. Each factor is independently
    # random, so over several months of compounding drift cost can end up
    # exceeding price on a real (if rare) item -- confirmed happening here
    # via dbt's assert_margin_pct_within_sane_bounds test during the first
    # build of this project (one item drifted to a -110% "margin"). Floor
    # price at cost * 1.05 after every drift step so the catalog never
    # settles into a sustained below-cost state, the same way a real
    # retailer would catch and reprice an item selling under cost rather
    # than leaving it there for months.
    for it in random.sample(items, k=max(1, len(items) // 7)):
        it.cost = round(it.cost * random.uniform(0.92, 1.12), 2)
        it.price = round(it.price * random.uniform(0.97, 1.08), 2)
        it.price = max(it.price, round(it.cost * 1.05, 2))

    # Re-categorize a few items mid-life (mirrors the real "Camryn Bracelet
    # sold under two categories in one window" case).
    for it in random.sample(items, k=max(1, len(items) // 25)):
        group, cat, supplier = random.choice(CATEGORIES)
        it.category_group, it.category = group, cat

    # Discontinue a couple of items, replace with new ones under a NEW
    # item_id -- mirrors the real bulk delete-and-recreate behavior that
    # breaks naive "track by item_id" logic.
    still_active = [it for it in items if not it.discontinued_at]
    for it in random.sample(still_active, k=min(2, len(still_active))):
        it.discontinued_at = date(2026, snapshot_index + 1, 1)
        group, cat, supplier = random.choice(CATEGORIES)
        # Cost and margin are chosen independently, then price is derived
        # from them (same approach as build_base_catalog) -- NOT two
        # independent uniform() calls for price and cost. An earlier
        # version drew price and cost independently and occasionally
        # produced a replacement item priced below its own cost, caught by
        # this project's assert_margin_pct_within_sane_bounds dbt test.
        replacement_cost = round(random.uniform(4, 65), 2)
        replacement_margin_target = random.uniform(1.7, 3.2)
        items.append(Item(
            item_id=stable_id("item", "replacement", it.item_id, snapshot_index),
            name=make_item_name(random),
            category_group=group,
            category=cat,
            supplier=supplier,
            price=round(replacement_cost * replacement_margin_target, 2),
            cost=replacement_cost,
            active_from=date(2026, snapshot_index + 1, 1),
        ))
    return items


def generate_catalog_snapshots(months=6):
    items = build_base_catalog()
    for m in range(months):
        items = drift_catalog(items, m)
        snap_date = date(2026, 1, 1) + timedelta(days=30 * m)
        path = os.path.join(CATALOG_DIR, snap_date.isoformat(),
                             "retail_items_export.csv")
        write_catalog_snapshot(items, snap_date, path)
    return items  # final state, used to generate orders against a live catalog


def generate_daily_orders(items, days=30, start=date(2026, 7, 1)):
    active_items = [it for it in items if not it.discontinued_at]
    order_seq = 0
    line_seq = 0
    for d in range(days):
        order_date = start + timedelta(days=d)
        day_dir = os.path.join(ORDERS_DIR, order_date.strftime("%Y%m%d"))
        os.makedirs(day_dir, exist_ok=True)

        n_orders = random.randint(18, 55)
        order_rows = []
        line_rows = []

        for _ in range(n_orders):
            order_seq += 1
            order_id = f"ORD-{order_seq:07d}"
            opened = datetime.combine(
                order_date, datetime.min.time()
            ) + timedelta(hours=random.uniform(9, 19))
            voided = 1 if random.random() < 0.02 else 0

            n_lines = random.randint(1, 4)
            order_total = 0.0
            this_orders_lines = []
            for _ in range(n_lines):
                line_seq += 1
                it = random.choice(active_items)
                qty = random.choice([1, 1, 1, 2, 3])
                discount = round(it.price * qty * random.choice([0, 0, 0, 0.1, 0.2]), 2)
                gross = round(it.price * qty, 2)
                net = round(gross - discount, 2)
                order_total += net
                row = {
                    "item_selection_id": f"SEL-{line_seq:08d}",
                    "export_date": order_date.isoformat(),
                    "export_filename": "ItemSelectionDetails.csv",
                    "order_id": order_id,
                    "sent_date": opened.isoformat(sep=" "),
                    "item_id": it.item_id,
                    "menu_item": it.name,
                    "sales_category": it.category,
                    "gross_price": gross,
                    "discount": discount,
                    "net_price": net,
                    "qty": qty,
                    "void_flag": voided,
                }
                this_orders_lines.append(row)
                line_rows.append(row)

            order_rows.append({
                "order_id": order_id,
                "export_date": order_date.isoformat(),
                "export_filename": "OrderDetails.csv",
                "opened": opened.isoformat(sep=" "),
                "guest_count": random.randint(1, 3),
                "discount_amount": round(sum(l["discount"] for l in this_orders_lines), 2),
                "total": round(order_total, 2),
                "voided": voided,
            })

        with open(os.path.join(day_dir, "OrderDetails.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(order_rows[0].keys()))
            w.writeheader()
            w.writerows(order_rows)

        with open(os.path.join(day_dir, "ItemSelectionDetails.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(line_rows[0].keys()))
            w.writeheader()
            w.writerows(line_rows)


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    final_catalog = generate_catalog_snapshots(months=6)
    generate_daily_orders(final_catalog, days=30, start=date(2026, 7, 1))
    print("Sample data generated under data/raw/")


if __name__ == "__main__":
    main()
