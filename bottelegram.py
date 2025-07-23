import os
import io
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

import requests
import matplotlib.pyplot as plt

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
    Job,
)

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
# ВСТАВЬ СВОЙ ТОКЕН НИЖЕ или установи переменную окружения BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")

COINGECKO_API = "https://api.coingecko.com/api/v3"
FEAR_GREED_API = "https://api.alternative.me/fng/"
DEFILLAMA_CHAINS = "https://api.llama.fi/chains"
CRYPTO_CHANNEL_URL = "https://t.me/cryptovektorpro"

# Список монет для уведомлений (15 популярных)
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

# Интервалы для уведомлений (секунды)
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("CryptoVektorProBot")

# ------------------------------------------------------------------
# SIMPLE IN-MEMORY CACHE
# ------------------------------------------------------------------
_API_CACHE: Dict[str, Dict[str, Any]] = {}  # url -> {"ts": epoch, "data": obj}
DEFAULT_TTL = 120  # seconds
LONG_TTL = 3600  # 1 hour, e.g. for /coins/list

import time

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
# HELPER FORMATTING
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
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Глобальные метрики", callback_data="global")],
        [InlineKeyboardButton("🏆 Топ-10 монет", callback_data="top10")],
        [InlineKeyboardButton("🔥 Трендовые монеты", callback_data="trending")],
        [InlineKeyboardButton("💹 Топ пар по объему", callback_data="pairs")],
        [InlineKeyboardButton("😱 Индекс страха/жадности", callback_data="fear")],
        [InlineKeyboardButton("💎 DeFi метрики", callback_data="defi")],
        [InlineKeyboardButton("🔔 Уведомления", callback_data="alerts_menu")],
        [InlineKeyboardButton("📢 Канал CryptoVektorPro", url=CRYPTO_CHANNEL_URL)],
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])

def alerts_coin_kb() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, c in enumerate(ALERT_COINS, start=1):
        row.append(InlineKeyboardButton(c["label"], callback_data=f"alert_coin_{c['id']}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Отключить все", callback_data="alerts_clear")])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def alerts_interval_kb(coin_id: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for label, seconds in ALERT_INTERVALS:
        row.append(InlineKeyboardButton(label, callback_data=f"alert_set_{coin_id}_{seconds}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="alerts_menu")])
    return InlineKeyboardMarkup(rows)

def coin_card_kb(coin_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 График 24ч", callback_data=f"chart_{coin_id}")],
        [InlineKeyboardButton("🔔 Уведомления", callback_data=f"alert_coin_{coin_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
    ])

# ------------------------------------------------------------------
# COIN ID RESOLUTION
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
    # exact match by id, symbol, name
    for c in coins:
        if user_input == c["id"].lower() or user_input == c["symbol"].lower() or user_input == c["name"].lower():
            return c["id"]
    # partial match symbol
    for c in coins:
        if user_input in c["symbol"].lower():
            return c["id"]
    # partial name fallback
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
        f"Общая капитализация: {fmt_money(d.get('total_market_cap', {}).get('usd'),0)}\n"
        f"Объем 24ч: {fmt_money(d.get('total_volume', {}).get('usd'),0)}\n"
        f"BTC Dominance: {d.get('market_cap_percentage',{}).get('btc',0):.2f}%\n"
        f"ETH Dominance: {d.get('market_cap_percentage',{}).get('eth',0):.2f}%\n"
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
            f"   MC: {fmt_money(coin['market_cap'],0)}\n"
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
            f"{i}. <b>{c['name']}</b> ({c['symbol']}) — Ранг: {c.get('market_cap_rank','?')}"
        )
    lines.append(f"\n<i>Обновлено: {now_str()}</i>")
    return "\n".join(lines)

def get_pairs_text() -> str:
    # Стратегия: берём топ-10 монет и собираем их тикеры; строим общий список и выбираем по объёму
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
    lines = ["<b>💹 Топ 10 торговых пар по объёму (по топ-10 монет)</b>\n"]
    for i, p in enumerate(top, start=1):
        lines.append(
            f"{i}. <b>{p['pair']}</b> на <i>{p['exchange']}</i>\n"
            f"   Цена: {fmt_money(p['price'],6)}\n"
            f"   Объём: {fmt_money(p['volume'],0)}\n"
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
            f"   TVL: {fmt_money(ch.get('tvl'),0)}\n"
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
        f"Капитализация: {fmt_money(md.get('market_cap', {}).get('usd'),0)}\n"
        f"Объём 24ч: {fmt_money(md.get('total_volume', {}).get('usd'),0)}\n"
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
    data = fetch_json(
        f"{COINGECKO_API}/simple/price?ids={coin_id}&vs_currencies=usd", ttl=30
    )
    if not data or coin_id not in data:
        return None
    return float(data[coin_id]["usd"])

# ------------------------------------------------------------------
# ALERTS STORAGE (in-memory)
# ------------------------------------------------------------------
# bot_data["alerts"] = {
#   chat_id: { coin_id: job }
# }
def get_alerts_store(ctx: ContextTypes.DEFAULT_TYPE) -> Dict[int, Dict[str, Job]]:
    store = ctx.application.bot_data.get("alerts")
    if store is None:
        store = {}
        ctx.application.bot_data["alerts"] = store
    return store

# ------------------------------------------------------------------
# HANDLERS: COMMANDS
# ------------------------------------------------------------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>CryptoVektorPro</b>\n\n"
        "Добро пожаловать! Выберите раздел ниже.\n\n"
        f'<a href="{CRYPTO_CHANNEL_URL}">Наш канал</a>'
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode="HTML")

async def cmd_coin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /coin <монета>\nПример: /coin bitcoin")
        return
    user_input = ctx.args[0]
    coin_id = find_coin_id(user_input)
    if not coin_id:
        await update.message.reply_text("❌ Монета не найдена.")
        return
    card = get_coin_card_text(coin_id)
    if not card:
        await update.message.reply_text("❌ Ошибка получения данных.")
        return
    await update.message.reply_text(card, reply_markup=coin_card_kb(coin_id), parse_mode="HTML")

async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # shortcut командой /alert
    text = "Выберите монету для уведомлений:"
    await update.message.reply_text(text, reply_markup=alerts_coin_kb())

# ------------------------------------------------------------------
# HANDLERS: CALLBACK QUERY ROUTER
# ------------------------------------------------------------------
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "main_menu":
        await q.message.edit_text(
            "<b>CryptoVektorPro</b>\n\nВыберите раздел:", reply_markup=main_menu_kb(), parse_mode="HTML"
        )
        return

    if data == "global":
        await q.message.edit_text(get_global_metrics_text(), reply_markup=back_kb(), parse_mode="HTML")
        return

    if data == "top10":
        await q.message.edit_text(get_top10_text(), reply_markup=back_kb(), parse_mode="HTML")
        return

    if data == "trending":
        await q.message.edit_text(get_trending_text(), reply_markup=back_kb(), parse_mode="HTML")
        return

    if data == "pairs":
        await q.message.edit_text(get_pairs_text(), reply_markup=back_kb(), parse_mode="HTML")
        return

    if data == "fear":
        await q.message.edit_text(get_fear_text(), reply_markup=back_kb(), parse_mode="HTML")
        return

    if data == "defi":
        await q.message.edit_text(get_defi_text(), reply_markup=back_kb(), parse_mode="HTML")
        return

    if data == "alerts_menu":
        await q.message.edit_text("Выберите монету для уведомлений:", reply_markup=alerts_coin_kb())
        return

    if data == "alerts_clear":
        await clear_all_alerts_for_chat(q.message.chat_id, ctx)
        await q.message.edit_text("Все уведомления отключены.", reply_markup=alerts_coin_kb())
        return

    if data.startswith("alert_coin_"):
        coin_id = data[len("alert_coin_"):]
        await q.message.edit_text(
            f"Выбрана монета <b>{coin_id}</b>.\nВыберите интервал уведомлений:",
            reply_markup=alerts_interval_kb(coin_id),
            parse_mode="HTML",
        )
        return

    if data.startswith("alert_set_"):
        # format: alert_set_<coin>_<seconds>
        parts = data.split("_")
        # ["alert","set","<coin>", "<seconds>"]
        if len(parts) != 4:
            return
        coin_id = parts[2]
        try:
            seconds = int(parts[3])
        except Exception:
            seconds = 3600
        await setup_alert_for_chat(q.message.chat_id, coin_id, seconds, ctx)
        await q.message.edit_text(
            f"✅ Уведомления включены для <b>{coin_id}</b> каждые {seconds // 60} мин / {seconds // 3600} ч.\n"
            "Вы можете выбрать другую монету или отключить уведомления.",
            reply_markup=alerts_coin_kb(),
            parse_mode="HTML",
        )
        return

    if data.startswith("chart_"):
        coin_id = data[len("chart_"):]
        buf = build_coin_chart_image_bytes(coin_id)
        if not buf:
            await q.message.reply_text("❌ Не удалось построить график.")
        else:
            caption = f"График {coin_id.upper()} за 24ч\n{now_str()}"
            await q.message.reply_photo(photo=buf, caption=caption)
        # после отправки графика вернём карточку
        card = get_coin_card_text(coin_id)
        if card:
            await q.message.reply_text(card, reply_markup=coin_card_kb(coin_id), parse_mode="HTML")
        return

# ------------------------------------------------------------------
# ALERT JOB CALLBACK
# ------------------------------------------------------------------
async def alert_job_callback(ctx: ContextTypes.DEFAULT_TYPE):
    job: Job = ctx.job
    chat_id = job.chat_id
    data = job.data or {}
    coin_id = data.get("coin_id")
    last_price = data.get("last_price")

    current_price = get_simple_price(coin_id)
    if current_price is None:
        await ctx.bot.send_message(chat_id, text=f"⚠️ Не удалось получить цену {coin_id}.")
        return

    change_pct = None
    if last_price is not None and last_price > 0:
        change_pct = ((current_price - last_price) / last_price) * 100.0

    # обновляем в job.data
    job.data["last_price"] = current_price

    # формируем текст
    if change_pct is None:
        msg = f"🔔 Текущее значение {coin_id.upper()}: {fmt_money(current_price,6)}."
    else:
        msg = (
            f"🔔 Обновление {coin_id.upper()}.\n"
            f"Цена: {fmt_money(current_price,6)}\n"
            f"Изменение с последнего уведомления: {change_pct:+.2f}%"
        )
    await ctx.bot.send_message(chat_id, text=msg)

# ------------------------------------------------------------------
# ALERT MANAGEMENT
# ------------------------------------------------------------------
async def setup_alert_for_chat(chat_id: int, coin_id: str, interval_s: int, ctx: ContextTypes.DEFAULT_TYPE):
    store = get_alerts_store(ctx)
    chat_alerts = store.get(chat_id)
    if chat_alerts is None:
        chat_alerts = {}
        store[chat_id] = chat_alerts

    # отменяем предыдущую задачу для этой монеты, если была
    old_job = chat_alerts.get(coin_id)
    if old_job:
        old_job.schedule_removal()

    # получить стартовую цену
    start_price = get_simple_price(coin_id)

    # создать новую задачу
    job = ctx.job_queue.run_repeating(
        alert_job_callback,
        interval=interval_s,
        first=0,  # сразу отправим первое сообщение
        chat_id=chat_id,
        name=f"alert_{chat_id}_{coin_id}",
        data={"coin_id": coin_id, "last_price": start_price},
    )

    chat_alerts[coin_id] = job

async def clear_all_alerts_for_chat(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE):
    store = get_alerts_store(ctx)
    chat_alerts = store.get(chat_id)
    if not chat_alerts:
        return
    for _, job in chat_alerts.items():
        job.schedule_removal()
    store[chat_id] = {}

# ------------------------------------------------------------------
# MAIN SETUP
# ------------------------------------------------------------------
def main():
    BOT_TOKEN = "8122827824:AAEXHjFpYGKyHarzGN4nkxr34j99X9JWmLk"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("coin", cmd_coin))
    app.add_handler(CommandHandler("alert", cmd_alert))

    # inline callback router
    app.add_handler(CallbackQueryHandler(on_callback))

    logger.info("🚀 CryptoVektorPro Bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
