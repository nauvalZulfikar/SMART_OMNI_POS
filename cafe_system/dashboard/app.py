import streamlit as st
import pandas as pd
import plotly.express as px
import json
from datetime import datetime
import time
import os

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Cafe POS Dashboard", layout="wide")

DATA_PATH = r"D:\Downloads\coding project\WA-POS\cafe_system\backend\orders_log.json"  # Adjust path if needed
REFRESH_INTERVAL = 10  # seconds

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=30)
def load_orders():
    if not os.path.exists(DATA_PATH):
        return pd.DataFrame(columns=["table", "timestamp", "item", "qty", "price", "subtotal"])
        # st.warning("Orders data file not found.")
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        # st.write(data)

    records = []
    for user, info in data.items():
        table = info.get("table", "N/A")
        timestamp = info.get("timestamp", "")
        for item in info.get("order", []):
            records.append({
                "user": user,
                "table": table,
                "timestamp": timestamp,
                "item": item["name"],
                "qty": item["qty"],
                "price": item["price"],
                "subtotal": item["subtotal"],
                "category": item.get("category", "Uncategorized")
            })
    return pd.DataFrame(records)

# ---------------- KPI COMPUTE ----------------
def compute_kpis(df):
    gross_sales = df["subtotal"].sum()
    net_sales = gross_sales * 0.995
    gross_profit = net_sales
    transactions = df["user"].nunique()
    avg_sale = gross_sales / transactions if transactions else 0
    gross_margin = (gross_profit / gross_sales * 100) if gross_sales else 0
    return gross_sales, net_sales, gross_profit, transactions, avg_sale, gross_margin

# ---------------- TABLE STATISTICS ----------------
def table_statistics(df):
    table_stats = df.groupby("table").agg(
        total_sales=("subtotal", "sum"),
        order_count=("user", "nunique"),
        last_order_time=("timestamp", "max")
    ).reset_index()

    table_stats["last_order_time"] = pd.to_datetime(table_stats["last_order_time"])
    table_stats["time_since_last_order"] = (datetime.now() - table_stats["last_order_time"]).dt.total_seconds() / 3600
    return table_stats

# ---------------- MAIN DASHBOARD ----------------
st.title("📊 Cafe POS Dashboard")
st.markdown("#### Real-Time Sales Overview (auto-refresh every 10s)")

# Auto refresh
st_autorefresh = st.empty()
time.sleep(REFRESH_INTERVAL)

df = load_orders()
if df.empty:
    st.info("No orders available yet. Waiting for new data...")
    st.stop()

# KPI metrics
gross_sales, net_sales, gross_profit, transactions, avg_sale, margin = compute_kpis(df)

col1, col2, col3 = st.columns(3)
col4, col5, col6 = st.columns(3)

col1.metric("Gross Sales", f"Rp {gross_sales:,.0f}")
col2.metric("Net Sales", f"Rp {net_sales:,.0f}")
col3.metric("Gross Profit", f"Rp {gross_profit:,.0f}")
col4.metric("Transactions", transactions)
col5.metric("Avg Sale / Transaction", f"Rp {avg_sale:,.0f}")
col6.metric("Gross Margin", f"{margin:.2f}%")

# ---------------- SALES CHARTS ----------------
st.markdown("### 📈 Sales Performance")

# Convert timestamp
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["day"] = df["timestamp"].dt.day_name()
df["hour"] = df["timestamp"].dt.hour

col_a, col_b = st.columns(2)

# Day of week chart
day_chart = (
    df.groupby("day")["subtotal"].sum().reindex(
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    )
)
col_a.plotly_chart(px.bar(day_chart, x=day_chart.index, y=day_chart.values,
                          title="Day of Week - Gross Sales (Rp)",
                          color=day_chart.index), use_container_width=True)

# Hourly sales chart
hour_chart = df.groupby("hour")["subtotal"].sum()
col_b.plotly_chart(px.area(hour_chart, x=hour_chart.index, y=hour_chart.values,
                           title="Hourly Gross Sales (Rp)",
                           line_shape="spline"), use_container_width=True)

# ---------------- TOP ITEMS ----------------
st.markdown("### 🍽️ Top Selling Items")
top_items = (
    df.groupby("item", as_index=False)
      .agg({"qty": "sum", "subtotal": "sum"})
      .sort_values("subtotal", ascending=False)
)
st.dataframe(top_items.head(10), use_container_width=True)

# ---------------- CATEGORY ANALYSIS ----------------
st.markdown("### 🥤 Category Insights")

cat_sales = df.groupby("category", as_index=False).agg(
    {"qty": "sum", "subtotal": "sum"}
)
col_x, col_y = st.columns(2)
col_x.plotly_chart(px.pie(cat_sales, names="category", values="qty", title="Category by Volume"),
                   use_container_width=True)
col_y.plotly_chart(px.pie(cat_sales, names="category", values="subtotal", title="Category by Sales"),
                   use_container_width=True)

# ---------------- TOP ITEMS BY CATEGORY ----------------
st.markdown("### 🏆 Top Items by Category")
for cat, group in df.groupby("category"):
    st.subheader(cat)
    chart = group.groupby("item")["qty"].sum().sort_values(ascending=False)
    st.plotly_chart(px.bar(chart, x=chart.index, y=chart.values,
                           title=f"{cat} - Top Items",
                           color=chart.values, text_auto=True),
                    use_container_width=True)

# # ---------------- TABLE STATISTICS ----------------
# st.markdown("### 🏷️ Table Statistics")

# table_stats = table_statistics(df)

# # Display table statistics in a neat table
# st.dataframe(table_stats)

# # ---------------- SIDEBAR FOR TABLE LINKS ----------------
# st.sidebar.title("Active Tables")
# active_tables = table_stats[["table", "total_sales", "order_count"]]
# for _, row in active_tables.iterrows():
#     st.sidebar.markdown(f"**Table {row['table']}**: Sales: Rp {row['total_sales']:,.0f} | Orders: {row['order_count']}")
#     st.sidebar.markdown(f"[Link to Table {row['table']} Orders](#)")

st.markdown("---")
st.caption("Cafe POS Dashboard © 2025 | Powered by Streamlit + WhatsApp POS Bot")
