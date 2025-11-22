import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os

DATA_PATH = "../backend/orders_log.json"

@st.cache_data(ttl=30)
def load_orders():
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for user, info in data.items():
        for item in info.get("order", []):
            rows.append({
                "category": item.get("category", "Uncategorized"),
                "item": item["name"],
                "qty": item["qty"],
                "subtotal": item["subtotal"]
            })
    return pd.DataFrame(rows)

st.title("📊 Category Analysis")

df = load_orders()
if df.empty:
    st.info("No category data yet.")
    st.stop()

col1, col2 = st.columns(2)

# Pie charts
cat_summary = df.groupby("category", as_index=False).agg({"qty": "sum", "subtotal": "sum"})
col1.plotly_chart(px.pie(cat_summary, names="category", values="qty", title="Category by Volume"),
                  use_container_width=True)
col2.plotly_chart(px.pie(cat_summary, names="category", values="subtotal", title="Category by Sales"),
                  use_container_width=True)

st.markdown("### 🏅 Top Items per Category")
for cat, group in df.groupby("category"):
    st.subheader(cat)
    chart = group.groupby("item")["qty"].sum().sort_values(ascending=False)
    st.bar_chart(chart)
