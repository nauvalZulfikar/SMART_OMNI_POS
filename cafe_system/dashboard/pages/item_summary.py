import streamlit as st
import pandas as pd
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
                "item": item["name"],
                "qty": item["qty"],
                "subtotal": item["subtotal"],
                "category": item.get("category", "Uncategorized")
            })
    return pd.DataFrame(rows)

st.title("📦 Item Summary")

df = load_orders()
if df.empty:
    st.info("No item data yet.")
    st.stop()

summary = (
    df.groupby("item", as_index=False)
      .agg({"qty": "sum", "subtotal": "sum"})
      .sort_values("subtotal", ascending=False)
)
summary.rename(columns={"qty": "Item Sold", "subtotal": "Gross Sales (Rp)"}, inplace=True)

st.markdown("### 🏆 Top 10 Items")
st.dataframe(summary.head(10), use_container_width=True)

st.markdown("### 🔍 All Item Performance")
st.dataframe(summary, use_container_width=True)
