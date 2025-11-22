# import json
# import os
# from datetime import datetime


# # -----------------------------------------------------------
# # Paths
# # -----------------------------------------------------------

# # Base folder: cafe_system/
# BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# # The backend folder contains orders_log.json
# ORDERS_FILE = os.path.join(BASE_DIR, "backend", "orders_log.json")


# # -----------------------------------------------------------
# # JSON Utilities
# # -----------------------------------------------------------

# def safe_load_json(file_path):
#     """Read JSON safely and return empty dict if broken."""
#     if not os.path.exists(file_path):
#         return {}

#     try:
#         with open(file_path, "r") as f:
#             return json.load(f)
#     except json.JSONDecodeError:
#         return {}


# def safe_save_json(file_path, data):
#     """Safely save JSON with pretty formatting."""
#     with open(file_path, "w") as f:
#         json.dump(data, f, indent=4)


# # -----------------------------------------------------------
# # Order Data Loaders
# # -----------------------------------------------------------

# def load_orders():
#     """
#     Load all orders from backend/orders_log.json.
#     Returns structure:

#     {
#         "user_123": {
#             "table": "A1",
#             "order": [
#                 {"item": "Fries", "qty": 2, "price": 10000},
#                 {"item": "Salmon", "qty": 1, "price": 45000}
#             ],
#             "total": 65000,
#             "timestamp": "2025-11-16 12:45:11.123123"
#         }
#     }
#     """
#     return safe_load_json(ORDERS_FILE)


# def save_orders(orders_data):
#     """Overwrite the entire orders JSON file."""
#     safe_save_json(ORDERS_FILE, orders_data)


# # -----------------------------------------------------------
# # Helper Functions for Analytics
# # -----------------------------------------------------------

# def get_orders_list():
#     """Return all orders as a list instead of dict."""
#     orders = load_orders()
#     return [
#         {**v, "user_id": k}
#         for k, v in orders.items()
#     ]


# def get_orders_by_table(table_number):
#     """Return all orders for a specific table."""
#     orders = load_orders()
#     return {
#         uid: data for uid, data in orders.items()
#         if data.get("table") == table_number
#     }


# def get_latest_order_time():
#     """Return the most recent order timestamp."""
#     orders = load_orders()
#     if not orders:
#         return None

#     timestamps = [
#         datetime.strptime(data["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
#         for data in orders.values()
#     ]
#     return max(timestamps)


# def get_unique_tables():
#     """Return list of tables that have active orders."""
#     orders = load_orders()
#     return sorted({data["table"] for data in orders.values()})


# def count_total_items():
#     """Total number of items ordered across all tables."""
#     orders = load_orders()
#     count = 0
#     for data in orders.values():
#         for item in data["order"]:
#             count += item.get("qty", 0)
#     return count


# # -----------------------------------------------------------
# # Data conversion helpers
# # -----------------------------------------------------------

# def convert_timestamp(ts: str):
#     """Convert timestamp string into datetime object."""
#     try:
#         return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
#     except ValueError:
#         # fallback if microseconds are missing
#         return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
