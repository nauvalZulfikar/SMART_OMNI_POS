import os
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from datetime import datetime
import re

# -----------------------------
# Load environment variables
# -----------------------------
load_dotenv()

ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WABA_PHONE_ID")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

GRAPH_URL = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
ORDERS_FILE = "orders_log.json"
MENU_FILE = "menu.json"

app = FastAPI()

# -----------------------------
# Load menu.json (code -> name)
# -----------------------------
if os.path.exists(MENU_FILE):
    with open(MENU_FILE, "r", encoding="utf-8") as f:
        MENU = json.load(f)
else:
    MENU = {}


# -----------------------------
# Orders helpers
# -----------------------------
def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return {}
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=4, ensure_ascii=False)


def update_order(user_id, items, table=None):
    """
    items: list of {name, qty, price, subtotal}
    """
    orders = load_orders()
    if user_id not in orders:
        orders[user_id] = {
            "order": [],
            "total": 0,
            "status": "unpaid",
            "timestamp": str(datetime.now()),
            "table": table or None,
        }

    if table and not orders[user_id].get("table"):
        orders[user_id]["table"] = table

    for item in items:
        existing = next(
            (x for x in orders[user_id]["order"] if x["name"] == item["name"]), None
        )
        if existing:
            existing["qty"] += item["qty"]
            existing["subtotal"] += item["qty"] * item["price"]
        else:
            orders[user_id]["order"].append(item)

        orders[user_id]["total"] += item["qty"] * item["price"]

    save_orders(orders)
    return orders[user_id]


def cancel_all_orders(user_id):
    orders = load_orders()
    if user_id in orders:
        del orders[user_id]
        save_orders(orders)
        return True
    return False


def build_cart_text(order_obj):
    """
    Build numbered cart lines from an order object like:
    { "order": [...], "total": ... }
    """
    lines = []
    for idx, item in enumerate(order_obj["order"], start=1):
        lines.append(
            f"{idx}. {item['name']} x{item['qty']} = {item['subtotal']:,} IDR"
        )
    text = "🧾 Pesanan kamu:\n" + "\n".join(lines)
    text += f"\n\nTotal: {order_obj['total']:,} IDR"
    text += "\nUntuk membatalkan, ketik *hapus <nomor_item> <jumlah>*.\nContoh: `hapus 1 2`"
    return text


def get_cart_state_for_agent(user_id):
    orders = load_orders()
    user_order = orders.get(user_id)
    if not user_order:
        return []
    result = []
    for idx, item in enumerate(user_order["order"], start=1):
        result.append(
            {
                "index": idx,
                "name": item["name"],
                "qty": item["qty"],
                "subtotal": item["subtotal"],
            }
        )
    return result


# -----------------------------
# WhatsApp helpers
# -----------------------------
async def wa_send(payload):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(GRAPH_URL, headers=headers, json=payload)
        print("WA STATUS:", res.status_code)
        try:
            print(res.json())
        except Exception:
            print(await res.text())


def catalog_message(to):
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "catalog_message",
            "body": {"text": "🍽️ Silakan lihat katalog menu kami di bawah ini:"},
            "action": {"name": "catalog_message"},
        },
    }


def payment_options(to, total):
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": f"💰 Total pesanan kamu {total:,} IDR.\nPilih metode pembayaran:"
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "PAY_QRIS", "title": "QRIS"}},
                    {"type": "reply", "reply": {"id": "PAY_CASH", "title": "Cash"}},
                    {
                        "type": "reply",
                        "reply": {"id": "PAY_VA", "title": "Virtual Account"},
                    },
                ]
            },
        },
    }


def ask_next_action(to):
    """
    Show next action buttons after user has an updated cart (typically after ordering).
    """
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Apa yang ingin kamu lakukan selanjutnya?"},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "ORDER_MORE", "title": "Tambah Pesanan"},
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "PAY_NOW", "title": "Bayar Sekarang"},
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "ORDER_CANCEL", "title": "❌ Batalkan Pesanan"},
                    },
                ]
            },
        },
    }


# -----------------------------
# AI Agent: interpret text → intent
# -----------------------------
async def ask_agent(user_message: str, cart_state: list):
    """
    Call OpenAI agent to parse text into JSON:
    {
      "intent": "show_menu" | "show_cart" | "cancel_item" | "cancel_all" | "pay" | "add_item" | "help" | "none",
      "cancel_index": null or int,  (1-based)
      "cancel_qty": null or int,
      "reply": "friendly text"
    }

    NOTE: for 'add_item' we DO NOT directly modify cart.
    We just respond & show catalog so the user can tap items.
    """
    if not OPENAI_KEY:
        # fallback if key missing
        return {
            "intent": "none",
            "cancel_index": None,
            "cancel_qty": None,
            "reply": "Ketik *menu* untuk lihat menu, atau *cart* untuk lihat pesananmu 😊",
        }

    system_message = """
You are a multilingual AI assistant for a restaurant WhatsApp ordering bot.

Your job:
1. Understand the USER MESSAGE in any language.
2. Detect whether the user is using **Indonesian (ID)** or **English (EN)**.
3. ALWAYS reply in the SAME language they used.
4. Convert the message into a structured JSON ACTION for the backend.

You MUST ALWAYS return PURE JSON with:

{
  "intent": "<intent>",
  "cancel_index": null or number,
  "cancel_qty": null or number,
  "reply": "<friendly reply in the user's language>"
}

----------------------------------------------
LANGUAGE DETECTION (IMPORTANT)
----------------------------------------------

- If the message is mostly Indonesian (e.g., “mau pesan”, “tolong”, “lihat menu”), reply in INDONESIAN.
- If the message is mostly English (e.g., “menu please”, “I want to order”), reply in ENGLISH.
- If mixed, choose **English**.
- NEVER mix Indonesian & English in the same reply.

----------------------------------------------
SUPPORTED INTENTS
----------------------------------------------
- "show_menu"  → user wants to see menu  
- "show_cart"  → user wants to see their cart  
- "cancel_item" → user wants to remove quantity of an item  
- "cancel_all" → user wants to remove all items  
- "pay" → user wants to proceed to payment  
- "add_item" → user mentions food items in free text (e.g., “lasagne 2”, “I want tea 1”)  
               NOTE: you DO NOT modify cart; just confirm and backend will open catalog.
- "help" → user confused  
- "none" → smalltalk, greetings, unclear  

----------------------------------------------
CANCEL FORMAT INTERPRETATION
----------------------------------------------
Examples:
- “hapus 1 2” → item #1 qty 2  
- “delete 1 2” → same meaning  
- If user writes “hapus 1” → cancel ALL of item #1  

If item not found, respond in the same language politely.

----------------------------------------------
ADD_ITEM BEHAVIOR (IMPORTANT)
----------------------------------------------
For "add_item" intent:
- You DO NOT guess price or real item code.
- You DO NOT change the cart.
- You simply confirm nicely what the user wants and tell them the catalogue will appear.

ID example:
“Baik! Kamu ingin Lasagne 2 dan Tea 1 ya. Silakan pilih itemnya dari katalog di bawah 😊”

EN example:
“Great! You want 2 Lasagne and 1 Tea. Please select the items from the catalog below 😊”

----------------------------------------------
TONE GUIDELINES
----------------------------------------------
- Friendly, polite, casual but professional.
- No slang.
- Encourage correct format gently.
- Never scold the user.
- Never return anything outside JSON.

----------------------------------------------
REMEMBER:
Your final output MUST be valid JSON ONLY.
No explanation, no markdown, no text around it.
"""

    user_payload = {
        "user_message": user_message,
        "current_cart": cart_state,
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_message},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            },
        )

    try:
        content = res.json()["choices"][0]["message"]["content"]
        action = json.loads(content)
    except Exception as e:
        print("Agent error:", e)
        action = {
            "intent": "none",
            "cancel_index": None,
            "cancel_qty": None,
            "reply": "Maaf, aku agak bingung baca pesannya. Kamu bisa tulis ulang, atau ketik *menu* / *cart* 😊",
        }

    # Normalize
    action["intent"] = str(action.get("intent", "none")).lower()
    if "cancel_index" not in action:
        action["cancel_index"] = None
    if "cancel_qty" not in action:
        action["cancel_qty"] = None
    if "reply" not in action:
        action["reply"] = ""

    return action


# -----------------------------
# Webhook verification
# -----------------------------
@app.get("/webhook")
async def verify(hub_mode: str = None, hub_challenge: str = None, hub_verify_token: str = None):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    return PlainTextResponse("Verification failed", status_code=403)


# -----------------------------
# Main webhook
# -----------------------------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    print("INCOMING:", data)

    try:
        msg = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_no = msg["from"]
        msg_type = msg.get("type")
    except Exception:
        return {"status": "ignored"}

    # -----------------------------
    # 1. Handle WhatsApp 'order' (catalog-based)
    # -----------------------------
    if msg_type == "order":
        order_data = msg["order"]
        products = order_data.get("product_items", [])

        new_items = []
        for p in products:
            code = str(p["product_retailer_id"])
            qty = p["quantity"]
            price = p.get("item_price", 0)
            name = MENU.get(code, code)

            new_items.append(
                {
                    "name": name,
                    "qty": qty,
                    "price": price,
                    "subtotal": price * qty,
                }
            )

        current = update_order(from_no, new_items)

        summary = "\n".join(
            [
                f"{idx}. {i['name']} x{i['qty']} = {i['subtotal']:,} IDR"
                for idx, i in enumerate(current["order"], start=1)
            ]
        )

        # Send summary
        await wa_send(
            {
                "messaging_product": "whatsapp",
                "to": from_no,
                "type": "text",
                "text": {
                    "body": f"🧾 Pesanan kamu:\n{summary}\n\nTotal: {current['total']:,} IDR"
                },
            }
        )

        # Then show what to do next
        await wa_send(ask_next_action(from_no))
        return {"status": "ok"}

    # -----------------------------
    # 2. Handle text (AI-driven)
    # -----------------------------
    if msg_type == "text":
        raw_text = msg["text"]["body"]
        text = raw_text.lower()

        # Quick rule: detect table number before AI
        if any(k in text for k in ["table", "meja"]):
            match = re.search(r"\d+", text)
            if match:
                table_no = match.group(0)
                orders = load_orders()
                if from_no not in orders:
                    orders[from_no] = {
                        "order": [],
                        "total": 0,
                        "status": "unpaid",
                        "timestamp": str(datetime.now()),
                        "table": table_no,
                    }
                else:
                    orders[from_no]["table"] = table_no
                save_orders(orders)

                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": f"👋 Hai! Kamu duduk di meja {table_no}. "
                                    "Kamu bisa ketik *menu* untuk lihat menu, atau langsung tulis mau pesan apa 😊"
                        },
                    }
                )
                return {"status": "ok"}

        # Build cart state for the agent
        cart_state = get_cart_state_for_agent(from_no)

        # Ask the AI agent
        action = await ask_agent(raw_text, cart_state)
        intent = action["intent"]
        cancel_index = action["cancel_index"]
        cancel_qty = action["cancel_qty"]
        reply = action["reply"] or ""

        # Always send the AI reply first
        await wa_send(
            {
                "messaging_product": "whatsapp",
                "to": from_no,
                "type": "text",
                "text": {"body": reply},
            }
        )

        # --- INTENT: show_menu ---
        if intent == "show_menu":
            await wa_send(catalog_message(from_no))
            return {"status": "ok"}

        # --- INTENT: show_cart ---
        if intent == "show_cart":
            orders = load_orders()
            if from_no in orders and orders[from_no]["order"]:
                cart_text = build_cart_text(orders[from_no])
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {"body": cart_text},
                    }
                )
                await wa_send(ask_next_action(from_no))
            else:
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": "Keranjang kamu masih kosong. Ketik *menu* untuk mulai pesan 😊"
                        },
                    }
                )
            return {"status": "ok"}

        # --- INTENT: cancel_all ---
        if intent == "cancel_all":
            if cancel_all_orders(from_no):
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {"body": "❌ Semua pesanan kamu sudah aku batalkan."},
                    }
                )
            else:
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {"body": "Sepertinya belum ada pesanan yang aktif."},
                    }
                )
            return {"status": "ok"}

        # --- INTENT: cancel_item ---
        if intent == "cancel_item":
            orders = load_orders()
            if from_no not in orders or not orders[from_no]["order"]:
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": "Keranjangmu masih kosong, belum ada item yang bisa dihapus."
                        },
                    }
                )
                return {"status": "ok"}

            if cancel_index is None:
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": "Biar aku bisa bantu, tulis seperti: *hapus 1 2* (hapus 2 porsi dari item nomor 1)."
                        },
                    }
                )
                return {"status": "ok"}

            index = int(cancel_index) - 1
            user_order = orders[from_no]["order"]
            if index < 0 or index >= len(user_order):
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {"body": "Nomor itemnya belum tepat, coba cek lagi ya 😊"},
                    }
                )
                return {"status": "ok"}

            item = user_order[index]

            # If cancel_qty == -1 or None -> remove all
            if cancel_qty is None or int(cancel_qty) <= 0:
                qty_to_remove = item["qty"]
            else:
                qty_to_remove = int(cancel_qty)

            if qty_to_remove >= item["qty"]:
                # remove whole
                orders[from_no]["total"] -= item["subtotal"]
                user_order.remove(item)
                msg2 = f"🗑️ Semua '{item['name']}' sudah aku hapus."
            else:
                reduce_amount = qty_to_remove * item["price"]
                item["qty"] -= qty_to_remove
                item["subtotal"] -= reduce_amount
                orders[from_no]["total"] -= reduce_amount
                msg2 = f"🗑️ '{item['name']}' aku kurangi {qty_to_remove}."

            # Save and respond with updated cart / empty info
            if not user_order:
                del orders[from_no]
                save_orders(orders)
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": msg2 + "\n\n🛒 Sekarang keranjangmu sudah kosong."
                        },
                    }
                )
            else:
                save_orders(orders)
                cart_text = build_cart_text(orders[from_no])
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {"body": msg2 + "\n\n" + cart_text},
                    }
                )
                await wa_send(ask_next_action(from_no))

            return {"status": "ok"}

        # --- INTENT: pay ---
        if intent == "pay":
            orders = load_orders()
            total = orders.get(from_no, {}).get("total", 0)
            if total <= 0:
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": "Sepertinya belum ada pesanan yang bisa dibayar. Ketik *menu* untuk mulai 😊"
                        },
                    }
                )
                return {"status": "ok"}

            await wa_send(payment_options(from_no, total))
            return {"status": "ok"}

        # --- INTENT: add_item (free-text ordering UX) ---
        if intent == "add_item":
            # We already sent AI confirmation text above.
            # Now show catalog so user can tap items to actually add to cart.
            await wa_send(catalog_message(from_no))
            return {"status": "ok"}

        # --- INTENT: help or none ---
        # Already sent AI reply text, nothing more to do.
        return {"status": "ok"}

    # -----------------------------
    # 3. INTERACTIVE BUTTON HANDLER
    # -----------------------------
    if msg_type == "interactive":
        inter = msg["interactive"]
        reply_id = inter.get("button_reply", {}).get("id", "")

        # Next-action buttons
        if reply_id == "ORDER_MORE":
            await wa_send(catalog_message(from_no))
            return {"status": "ok"}

        if reply_id == "ORDER_CANCEL":
            if cancel_all_orders(from_no):
                body = "❌ Semua pesanan kamu sudah aku batalkan."
            else:
                body = "Belum ada pesanan aktif yang bisa dibatalkan."
            await wa_send(
                {
                    "messaging_product": "whatsapp",
                    "to": from_no,
                    "type": "text",
                    "text": {"body": body},
                }
            )
            return {"status": "ok"}

        if reply_id == "PAY_NOW":
            orders = load_orders()
            total = orders.get(from_no, {}).get("total", 0)
            if total <= 0:
                await wa_send(
                    {
                        "messaging_product": "whatsapp",
                        "to": from_no,
                        "type": "text",
                        "text": {
                            "body": "Belum ada pesanan yang bisa dibayar. Ketik *menu* untuk mulai."
                        },
                    }
                )
            else:
                await wa_send(payment_options(from_no, total))
            return {"status": "ok"}

        # Payment method buttons (very simple stubs)
        if reply_id == "PAY_QRIS":
            await wa_send(
                {
                    "messaging_product": "whatsapp",
                    "to": from_no,
                    "type": "text",
                    "text": {
                        "body": "📸 Silakan scan QRIS di kasir atau yang sudah kami sediakan ya."
                    },
                }
            )
            return {"status": "ok"}

        if reply_id == "PAY_CASH":
            await wa_send(
                {
                    "messaging_product": "whatsapp",
                    "to": from_no,
                    "type": "text",
                    "text": {
                        "body": "💵 Baik, silakan bayar tunai di kasir saat pesanan diantar atau diambil."
                    },
                }
            )
            return {"status": "ok"}

        if reply_id == "PAY_VA":
            await wa_send(
                {
                    "messaging_product": "whatsapp",
                    "to": from_no,
                    "type": "text",
                    "text": {
                        "body": "🏦 Pembayaran via Virtual Account akan diinformasikan oleh kasir. Terima kasih 😊"
                    },
                }
            )
            return {"status": "ok"}

    return {"status": "ok"}
