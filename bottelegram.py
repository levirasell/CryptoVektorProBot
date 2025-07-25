import os
import io
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

import requests
import matplotlib.pyplot as plt
import telebot
from telebot import types

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Не задан BOT_TOKEN в переменных окружения!")

bot = telebot.TeleBot(BOT_TOKEN)

COINGECKO_API = "https://api.coingecko.com/api/v3"
FEAR_GREED_API = "https://api.alternative.me/fng/"
DEFILLAMA_CHAINS = "https://api.llama.fi/chains"
CRYPTO_CHANNEL_URL = "https://t.me/cryptovektorpro"

# Список монет для уведомлений
ALERT_COINS: List[Dict[str, str]] = [
    {"id": "bitcoin", "label": "BTC"},
    {"id": "ethereum", "label": "ETH"},
    {"id": "tether", "label": "USDT"},
    {"id": "binancecoin", "label": "BNB"},
    {"id": "solana", "label": "SOL"},
    {"id": "ripple", "label": "XRP"},
    {"id": "usd-coin", "label": "USDC"},
    {"id": "dogecoin", "label": "DOGE"},
    {"id": "cardano", "label": "ADA"},
    {"id": "tron", "label": "TRX"},
    {"id": "avalanche-2", "label": "AVAX"},
    {"id": "polkadot", "label": "DOT"},
    {"id": "shiba-inu", "label": "SHIB"},
    {"id": "chainlink", "label": "LINK"},
    {"id": "litecoin", "label": "LTC"},
]

# Интервалы для уведомлений
ALERT_INTERVALS = [
    ("15 мин", 15 * 60),
    ("30 мин", 30 * 60),
    ("1 ч", 60 * 60),
    ("2 ч", 2 * 60 * 60),
    ("4 ч", 4 * 60 * 60),
    ("12 ч", 12 * 60 * 60),
    ("24 ч", 24 * 60 * 60),
]

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger("CryptoVektorProBot")

# ------------------------------------------------------------------
# CACHE
# ------------------------------------------------------------------
_API_CACHE: Dict[str, Dict[str, Any]] = {}
DEFAULT_TTL = 120
LONG_TTL = 3600

def cache_get(url: str, ttl: int = DEFAULT_TTL):
    rec = _API_CACHE.get(url)
    if not rec:
        return None
    if (time.time() - rec["ts"]) > ttl:
        return None
    return rec["data"]

def cache_set(url: str, data: Any):
    _API_CACHE[url] = {"ts": time.time(), "data": data}

def fetch_json(url: str, ttl: int = DEFAULT_TTL) -> Optional[Any]:
    cached = cache_get(url, ttl=ttl)
    if cached is not None:
        return cached
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            cache_set(url, data)
            return data
        logger.warning("API non-200 %s -> %s", url, r.status_code)
        return None
    except Exception as e:
        logger.error("Fetch error %s: %s", url, e)
        return None

# ------------------------------------------------------------------
# FORMATTING HELPERS
# ------------------------------------------------------------------
def fmt_money(v: Any, decimals: int = 2) -> str:
    try:
        f = float(v)
    except Exception:
        return "N/A"
    if f >= 1:
        return f"${f:,.{decimals}f}"
    return f"${f:.8f}".rstrip("0").rstrip(".")

def fmt_int(v: Any) -> str:
    try:
        return f"{int(v):,}"
    except Exception:
        return "N/A"

def fmt_pct(v: Any) -> str:
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "N/A"

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ------------------------------------------------------------------
# KEYBOARDS
# ------------------------------------------------------------------
def main_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    buttons = [
        types.InlineKeyboardButton("🌍 Глобальные метрики", callback_data="global"),
        types.InlineKeyboardButton("🏆 Топ-10 монет", callback_data="top10"),
        types.InlineKeyboardButton("🔥 Трендовые монеты", callback_data="trending"),
        types.InlineKeyboardButton("💹 Топ пар по объему", callback_data="pairs"),
        types.InlineKeyboardButton("😱 Индекс страха/жадности", callback_data="fear"),
        types.InlineKeyboardButton("💎 DeFi метрики", callback_data="defi"),
        types.InlineKeyboardButton("🔔 Уведомления", callback_data="alerts_menu"),
    ]
    keyboard.add(*buttons)
    keyboard.add(types.InlineKeyboardButton("📢 Канал CryptoVektorPro", url=CRYPTO_CHANNEL_URL))
    return keyboard

def back_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
    return keyboard

def alerts_coin_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for coin in ALERT_COINS:
        buttons.append(types.InlineKeyboardButton(coin["label"], callback_data=f"alert_coin_{coin['id']}"))
    
    # Добавляем кнопки по 3 в ряд
    for i in range(0, len(buttons), 3):
        keyboard.add(*buttons[i:i+3])
    
    keyboard.add(types.InlineKeyboardButton("❌ Отключить все", callback_data="alerts_clear"))
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
    return keyboard

def alerts_interval_keyboard(coin_id: str):
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for label, seconds in ALERT_INTERVALS:
        buttons.append(types.InlineKeyboardButton(label, callback_data=f"alert_set_{coin_id}_{seconds}"))
    
    for i in range(0, len(buttons), 3):
        keyboard.add(*buttons[i:i+3])
    
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="alerts_menu"))
    return keyboard

def coin_card_keyboard(coin_id: str):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📈 График 24ч", callback_data=f"chart_{coin_id}"))
    keyboard.add(types.InlineKeyboardButton("🔔 Уведомления", callback_data=f"alert_coin_{coin_id}"))
    keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
    return keyboard

# ------------------------------------------------------------------
# COIN DATA
# ------------------------------------------------------------------
_COINS_LIST_CACHE: Optional[List[Dict[str, str]]] = None

def load_coins_list() -> Optional[List[Dict[str, str]]]:
    global _COINS_LIST_CACHE
    if _COINS_LIST_CACHE is not None:
        return _COINS_LIST_CACHE
    data = fetch_json(f"{COINGECKO_API}/coins/list", ttl=LONG_TTL)
    if isinstance(data, list):
        _COINS_LIST_CACHE = data
        return data
    return None

def find_coin_id(user_input: str) -> Optional[str]:
    user_input = user_input.strip().lower()
    coins = load_coins_list()
    if not coins:
        return None
    
    # Точное совпадение
    for c in coins:
        if user_input == c["id"].lower() or user_input == c["symbol"].lower() or user_input == c["name"].lower():
            return c["id"]
    
    # Частичное совпадение по символу
    for c in coins:
        if user_input in c["symbol"].lower():
            return c["id"]
    
    # Частичное совпадение по названию
    for c in coins:
        if user_input in c["name"].lower():
            return c["id"]
    return None

# ------------------------------------------------------------------
# DATA FUNCTIONS
# ------------------------------------------------------------------
def get_global_metrics_text() -> str:
    data = fetch_json(f"{COINGECKO_API}/global")
    if not data or "data" not in data:
        return "❌ Ошибка получения данных."
    d = data["data"]
    return (
        "<b>🌍 Глобальные метрики</b>\n\n"
        f"Активные криптовалюты: {fmt_int(d.get('active_cryptocurrencies'))}\n"
        f"Биржи: {fmt_int(d.get('markets'))}\n"
        f"Общая капитализация: {fmt_money(d.get('total_market_cap', {}).get('usd'), 0)}\n"
        f"Объем 24ч: {fmt_money(d.get('total_volume', {}).get('usd'), 0)}\n"
        f"BTC Dominance: {d.get('market_cap_percentage', {}).get('btc', 0):.2f}%\n"
        f"ETH Dominance: {d.get('market_cap_percentage', {}).get('eth', 0):.2f}%\n"
        f"\n<i>Обновлено: {now_str()}</i>"
    )

def get_top10_text() -> str:
    data = fetch_json(f"{COINGECKO_API}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1")
    if not isinstance(data, list):
        return "❌ Ошибка получения данных."
    lines = ["<b>🏆 Топ-10 криптовалют</b>\n"]
    for coin in data:
        lines.append(
            f"{coin['market_cap_rank']}. <b>{coin['name']}</b> ({coin['symbol'].upper()})\n"
            f"   Цена: {fmt_money(coin['current_price'])}\n"
            f"   MC: {fmt_money(coin['market_cap'], 0)}\n"
            f"   24ч: {fmt_pct(coin.get('price_change_percentage_24h'))}\n"
        )
    lines.append(f"<i>Обновлено: {now_str()}</i>")
    return "\n".join(lines)

def get_trending_text() -> str:
    data = fetch_json(f"{COINGECKO_API}/search/trending")
    if not data or "coins" not in data:
        return "❌ Ошибка получения данных."
    lines = ["<b>🔥 Трендовые монеты</b>\n"]
    for i, item in enumerate(data["coins"], start=1):
        c = item["item"]
        lines.append(
            f"{i}. <b>{c['name']}</b> ({c['symbol']}) — Ранг: {c.get('market_cap_rank', '?')}"
        )
    lines.append(f"\n<i>Обновлено: {now_str()}</i>")
    return "\n".join(lines)

def get_pairs_text() -> str:
    coins = fetch_json(
        f"{COINGECKO_API}/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=10&page=1"
    )
    if not isinstance(coins, list):
        return "❌ Ошибка получения данных."
    
    pairs = []
    for coin in coins:
        coin_id = coin["id"]
        tickers_data = fetch_json(f"{COINGECKO_API}/coins/{coin_id}/tickers")
        if not tickers_data:
            continue
        for t in tickers_data.get("tickers", []):
            vol = t.get("volume")
            price = t.get("last")
            base = t.get("base")
            target = t.get("target")
            exch = t.get("market", {}).get("name")
            if vol and price and base and target and exch:
                pairs.append({
                    "pair": f"{base}/{target}",
                    "volume": vol,
                    "price": price,
                    "exchange": exch,
                })
    
    if not pairs:
        return "❌ Данные по парам не найдены."
    
    pairs.sort(key=lambda x: x["volume"], reverse=True)
    top = pairs[:10]
    lines = ["<b>💹 Топ 10 торговых пар по объёму</b>\n"]
    for i, p in enumerate(top, start=1):
        lines.append(
            f"{i}. <b>{p['pair']}</b> на <i>{p['exchange']}</i>\n"
            f"   Цена: {fmt_money(p['price'], 6)}\n"
            f"   Объём: {fmt_money(p['volume'], 0)}\n"
        )
    lines.append(f"<i>Обновлено: {now_str()}</i>")
    return "\n".join(lines)

def get_fear_text() -> str:
    data = fetch_json(FEAR_GREED_API)
    if not data or "data" not in data:
        return "❌ Ошибка получения данных."
    v = data["data"][0]
    ts = datetime.utcfromtimestamp(int(v["timestamp"])).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "<b>😱 Индекс страха и жадности</b>\n\n"
        f"Значение: {v['value']}\n"
        f"Категория: {v['value_classification']}\n"
        f"Обновлено: {ts}"
    )

def get_defi_text() -> str:
    data = fetch_json(DEFILLAMA_CHAINS)
    if not isinstance(data, list):
        return "❌ Ошибка получения данных."
    top = sorted(data, key=lambda x: x.get("tvl", 0), reverse=True)[:5]
    lines = ["<b>💎 DeFi Метрики (Top-5 Chain по TVL)</b>\n"]
    for i, ch in enumerate(top, start=1):
        lines.append(
            f"{i}. {ch['name']}\n"
            f"   TVL: {fmt_money(ch.get('tvl'), 0)}\n"
            f"   Изм. 1д: {fmt_pct(ch.get('change_1d'))}\n"
        )
    lines.append(f"<i>Обновлено: {now_str()}</i>")
    return "\n".join(lines)

def get_coin_card_text(coin_id: str) -> Optional[str]:
    data = fetch_json(f"{COINGECKO_API}/coins/{coin_id}?localization=false&tickers=false&market_data=true")
    if not data:
        return None
    md = data.get("market_data", {})
    return (
        f"<b>{data['name']} ({data['symbol'].upper()})</b>\n\n"
        f"Цена: {fmt_money(md.get('current_price', {}).get('usd'))}\n"
        f"Капитализация: {fmt_money(md.get('market_cap', {}).get('usd'), 0)}\n"
        f"Объём 24ч: {fmt_money(md.get('total_volume', {}).get('usd'), 0)}\n"
        f"Изм. 24ч: {fmt_pct(md.get('price_change_percentage_24h'))}\n"
    )

def build_coin_chart_image_bytes(coin_id: str) -> Optional[io.BytesIO]:
    data = fetch_json(f"{COINGECKO_API}/coins/{coin_id}/market_chart?vs_currency=usd&days=1")
    if not data or "prices" not in data:
        return None
    prices = data["prices"]
    if not prices:
        return None
    
    xs = [datetime.fromtimestamp(p[0] / 1000) for p in prices]
    ys = [p[1] for p in prices]
    
    plt.figure(figsize=(8, 4))
    plt.plot(xs, ys)
    plt.title(f"{coin_id.upper()} — 24ч")
    plt.xlabel("Время")
    plt.ylabel("Цена $")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.figtext(0.99, 0.01, now_str(), ha="right", fontsize=8, color="gray")
    
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150)
    plt.close()
    buf.seek(0)
    return buf

def get_simple_price(coin_id: str) -> Optional[float]:
    data = fetch_json(f"{COINGECKO_API}/simple/price?ids={coin_id}&vs_currencies=usd", ttl=30)
    if not data or coin_id not in data:
        return None
    return float(data[coin_id]["usd"])

# ------------------------------------------------------------------
# ALERTS SYSTEM
# ------------------------------------------------------------------
# Структура: alerts_store[chat_id][coin_id] = {"thread": thread, "last_price": price, "interval": seconds}
alerts_store: Dict[int, Dict[str, Dict]] = {}

def alert_worker(chat_id: int, coin_id: str, interval_s: int):
    """Рабочий поток для отправки уведомлений"""
    last_price = get_simple_price(coin_id)
    
    # Отправляем первое сообщение
    if last_price:
        bot.send_message(chat_id, f"🔔 Уведомления включены для {coin_id.upper()}: {fmt_money(last_price, 6)}")
        alerts_store[chat_id][coin_id]["last_price"] = last_price
    
    while True:
        try:
            time.sleep(interval_s)
            
            # Проверяем, не был ли алерт отключен
            if chat_id not in alerts_store or coin_id not in alerts_store[chat_id]:
                break
            
            current_price = get_simple_price(coin_id)
            if current_price is None:
                bot.send_message(chat_id, f"⚠️ Не удалось получить цену {coin_id}")
                continue
            
            last_price = alerts_store[chat_id][coin_id].get("last_price")
            change_pct = None
            
            if last_price and last_price > 0:
                change_pct = ((current_price - last_price) / last_price) * 100.0
            
            # Обновляем последнюю цену
            alerts_store[chat_id][coin_id]["last_price"] = current_price
            
            # Формируем сообщение
            if change_pct is None:
                msg = f"🔔 {coin_id.upper()}: {fmt_money(current_price, 6)}"
            else:
                emoji = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➡️"
                msg = (
                    f"🔔 {coin_id.upper()}\n"
                    f"Цена: {fmt_money(current_price, 6)}\n"
                    f"{emoji} Изменение: {change_pct:+.2f}%"
                )
            
            bot.send_message(chat_id, msg)
            
        except Exception as e:
            logger.error(f"Ошибка в alert_worker для {chat_id}/{coin_id}: {e}")
            break

def setup_alert(chat_id: int, coin_id: str, interval_s: int):
    """Настройка уведомления для пользователя"""
    if chat_id not in alerts_store:
        alerts_store[chat_id] = {}
    
    # Останавливаем предыдущий алерт для этой монеты, если был
    if coin_id in alerts_store[chat_id]:
        # Поток завершится сам при следующей проверке
        pass
    
    # Создаем новый поток
    thread = threading.Thread(
        target=alert_worker,
        args=(chat_id, coin_id, interval_s),
        daemon=True
    )
    
    alerts_store[chat_id][coin_id] = {
        "thread": thread,
        "interval": interval_s,
        "last_price": None
    }
    
    thread.start()

def clear_all_alerts(chat_id: int):
    """Отключение всех уведомлений для пользователя"""
    if chat_id in alerts_store:
        alerts_store[chat_id].clear()

# ------------------------------------------------------------------
# COMMAND HANDLERS
# ------------------------------------------------------------------
@bot.message_handler(commands=['start'])
def start_command(message):
    text = (
        "<b>🚀 CryptoVektorPro</b>\n\n"
        "Добро пожаловать! Ваш помощник в мире криптовалют.\n"
        "Выберите раздел ниже.\n\n"
        f'<a href="{CRYPTO_CHANNEL_URL}">📢 Наш канал</a>'
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=main_menu_keyboard())

@bot.message_handler(commands=['coin'])
def coin_command(message):
    try:
        user_input = message.text.split(' ', 1)[1]
        coin_id = find_coin_id(user_input)
        if not coin_id:
            bot.send_message(message.chat.id, "❌ Монета не найдена.")
            return
        
        card = get_coin_card_text(coin_id)
        if not card:
            bot.send_message(message.chat.id, "❌ Ошибка получения данных.")
            return
        
        bot.send_message(message.chat.id, card, parse_mode="HTML", reply_markup=coin_card_keyboard(coin_id))
    except IndexError:
        bot.send_message(message.chat.id, "Использование: /coin <монета>\nПример: /coin bitcoin")

@bot.message_handler(commands=['alert'])
def alert_command(message):
    bot.send_message(message.chat.id, "Выберите монету для уведомлений:", reply_markup=alerts_coin_keyboard())

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "<b>📋 Команды бота:</b>\n\n"
        "/start - Главное меню\n"
        "/coin <название> - Информация о монете\n"
        "/alert - Настройка уведомлений\n"
        "/help - Это сообщение\n\n"
        "Используйте кнопки для навигации!"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="HTML")

# ------------------------------------------------------------------
# CALLBACK HANDLERS
# ------------------------------------------------------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data
    
    try:
        if data == "main_menu":
            text = (
                "<b>🚀 CryptoVektorPro</b>\n\n"
                "Выберите раздел:"
            )
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=main_menu_keyboard())
        
        elif data == "global":
            text = get_global_metrics_text()
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_keyboard())
        
        elif data == "top10":
            text = get_top10_text()
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_keyboard())
        
        elif data == "trending":
            text = get_trending_text()
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_keyboard())
        
        elif data == "pairs":
            text = get_pairs_text()
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_keyboard())
        
        elif data == "fear":
            text = get_fear_text()
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_keyboard())
        
        elif data == "defi":
            text = get_defi_text()
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_keyboard())
        
        elif data == "alerts_menu":
            bot.edit_message_text("Выберите монету для уведомлений:", chat_id, message_id, reply_markup=alerts_coin_keyboard())
        
        elif data == "alerts_clear":
            clear_all_alerts(chat_id)
            bot.edit_message_text("✅ Все уведомления отключены.", chat_id, message_id, reply_markup=alerts_coin_keyboard())
        
        elif data.startswith("alert_coin_"):
            coin_id = data[len("alert_coin_"):]
            text = f"Выбрана монета <b>{coin_id.upper()}</b>.\nВыберите интервал уведомлений:"
            bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=alerts_interval_keyboard(coin_id))
        
        elif data.startswith("alert_set_"):
            parts = data.split("_")
            if len(parts) >= 4:
                coin_id = parts[2]
                try:
                    seconds = int(parts[3])
                except ValueError:
                    seconds = 3600
                
                setup_alert(chat_id, coin_id, seconds)
                interval_text = f"{seconds // 60} мин" if seconds < 3600 else f"{seconds // 3600} ч"
                text = f"✅ Уведомления включены для <b>{coin_id.upper()}</b> каждые {interval_text}."
                bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=alerts_coin_keyboard())
        
        elif data.startswith("chart_"):
            coin_id = data[len("chart_"):]
            buf = build_coin_chart_image_bytes(coin_id)
            if buf:
                caption = f"📈 График {coin_id.upper()} за 24ч\n{now_str()}"
                bot.send_photo(chat_id, buf, caption=caption)
                # Возвращаем карточку монеты
                card = get_coin_card_text(coin_id)
                if card:
                    bot.send_message(chat_id, card, parse_mode="HTML", reply_markup=coin_card_keyboard(coin_id))
            else:
                bot.send_message(chat_id, "❌ Не удалось построить график.")
    
    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}")
        bot.send_message(chat_id, "❌ Произошла ошибка. Попробуйте еще раз.")

# ------------------------------------------------------------------
# TEXT HANDLER
# ------------------------------------------------------------------
@bot.message_handler(content_types=['text'])
def handle_text(message):
    bot.send_message(
        message.chat.id,
        "Используйте команды или кнопки меню для навигации!\n\n"
        "/start - главное меню\n"
        "/help - справка\n"
        "/coin <название> - информация о монете"
    )

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("🚀 CryptoVektorPro Bot запущен!")
    bot.polling(none_stop=True)
