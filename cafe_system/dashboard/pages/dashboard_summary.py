import streamlit as st
import pandas as pd
import plotly.express as px
import json
from datetime import datetime
import os

DATA_PATH = "../backend/orders_log.json"

@st.cache_data(ttl=30)
def load_orders():
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame(columns=["table", "timestamp", "item", "qty", "price", "subtotal"])
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for user, info in data.items():
        table = info.get("table", "N/A")
        timestamp = info.get("timestamp", "")
        for item in info.get("order", []):
            rows.append({
                "user": user,
                "table": table,
                "timestamp": timestamp,
                "item": item["name"],
                "qty": item["qty"],
                "price": item["price"],
                "subtotal": item["subtotal"],
                "category": item.get("category", "Uncategorized")
            })
    return pd.DataFrame(rows)

st.title("🏠 Dashboard Summary")

df = load_orders()
if df.empty:
    st.info("No orders found yet.")
    st.stop()

df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["day"] = df["timestamp"].dt.day_name()
df["hour"] = df["timestamp"].dt.hour

gross_sales = df["subtotal"].sum()
transactions = df["user"].nunique()
avg_sale = gross_sales / transactions if transactions else 0

col1, col2, col3 = st.columns(3)
col1.metric("Gross Sales", f"Rp {gross_sales:,.0f}")
col2.metric("Transactions", transactions)
col3.metric("Avg Sale / Transaction", f"Rp {avg_sale:,.0f}")

col_a, col_b = st.columns(2)

# Day of week chart
day_chart = df.groupby("day")["subtotal"].sum().reindex(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
)
col_a.plotly_chart(px.bar(day_chart, x=day_chart.index, y=day_chart.values,
                          title="Day of Week Sales (Rp)",
                          color=day_chart.index), use_container_width=True)

# Hourly chart
hour_chart = df.groupby("hour")["subtotal"].sum()
col_b.plotly_chart(px.area(hour_chart, x=hour_chart.index, y=hour_chart.values,
                           title="Hourly Sales (Rp)",
                           line_shape="spline"), use_container_width=True)
