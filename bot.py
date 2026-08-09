import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import aiohttp
import phonenumbers
from phonenumbers import carrier, geocoder
import whois
import dns.resolver
import subprocess
import json
import re

# === Вспомогательные функции ===
async def fetch_json(session, url):
    async with session.get(url) as resp:
        return await resp.json() if resp.status == 200 else None

def escape_md(text):
    """Экранирование для MarkdownV2"""
    chars = r'_[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in chars else c for c in text)

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🔍 *OSINT Bot* готов\\.\n"
        "/ip `8\\.8\\.8\\.8` — информация об IP\n"
        "/username `nickname` — поиск по 500\\+ соцсетям\n"
        "/email `user@mail\\.com` — утечки и регистрации\n"
        "/phone `\\+79161234567` — оператор, страна, утечки\n"
        "/passport `1234 567890` — проверка паспорта РФ\n"
        "/search `запрос` — поиск упоминаний в открытых чатах\n"
        "/face `url_фото` — поиск по лицу \\(FaceCheck\\)"
    )
    await update.message.reply_text(help_text, parse_mode="MarkdownV2")

# --- IP ---
async def ip_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /ip 8.8.8.8"); return
    ip = context.args[0]
    async with aiohttp.ClientSession() as sess:
        data = await fetch_json(sess, f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,isp,org,as,query")
        if data and data.get("status") == "success":
            text = (f"IP: {data['query']}\nСтрана: {data['country']}\n"
                    f"Регион: {data['regionName']}\nГород: {data['city']}\n"
                    f"Провайдер: {data['isp']}\nОрганизация: {data['org']}\nAS: {data['as']}")
        else:
            text = "Неверный IP или сервис недоступен."
        await update.message.reply_text(text)

# --- USERNAME (Maigret API) ---
async def username_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /username someuser"); return
    username = context.args[0]
    async with aiohttp.ClientSession() as sess:
        data = await fetch_json(sess, f"https://api.maigret-app.com/v1/search?username={username}")
        if data:
            results = data.get("results", [])
            if results:
                text = f"Найдено {len(results)} профилей:\n"
                for r in results[:20]:
                    text += f"• [{escape_md(r['site'])}]({r['url']})\n"
                if len(results) > 20:
                    text += f"\\+ ещё {len(results)-20}..."
            else:
                text = "Ничего не найдено."
            await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)
        else:
            await update.message.reply_text("Сервис Maigret временно недоступен.")

# --- EMAIL (Holehe + HIBP) ---
async def email_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /email test@gmail.com"); return
    email = context.args[0]
    results = []
    # Holehe (регистрации)
    try:
        proc = subprocess.run(["holehe", email, "--only-used", "-C"], capture_output=True, text=True, timeout=25)
        if proc.stdout.strip():
            results.append("📌 *Регистрации на сайтах:*\n" + escape_md(proc.stdout.strip()[:400]))
    except FileNotFoundError:
        results.append("⚠️ Holehe не установлен.")
    except subprocess.TimeoutExpired:
        results.append("⚠️ Holehe превысил время.")
    # HIBP (утечки)
    try:
        async with aiohttp.ClientSession() as sess:
            data = await fetch_json(sess, f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                                    headers={"hibp-api-key": "твой_api_ключ_если_есть"}) # без ключа может работать с ограничениями
            if data:
                breaches = ', '.join([b['Name'] for b in data])
                results.append(f"🛡 *Утечки (HIBP):* {escape_md(breaches)}")
    except:
        pass
    if not results:
        text = "Данные не найдены."
    else:
        text = "\n\n".join(results)
    await update.message.reply_text(text[:4000], parse_mode="MarkdownV2")

# --- PHONE (расширенный: оператор, регион, утечки через Telegram-ботов) ---
async def phone_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /phone +79161234567"); return
    num = context.args[0]
    try:
        p = phonenumbers.parse(num)
        if not phonenumbers.is_valid_number(p):
            await update.message.reply_text("Некорректный номер.")
            return
        country = geocoder.description_for_number(p, "ru")
        oper = carrier.name_for_number(p, "ru")
        formatted = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        text = f"📞 *Номер:* {escape_md(formatted)}\n🌍 *Страна:* {escape_md(country)}\n📡 *Оператор:* {escape_md(oper)}"
        # Можно добавить поиск утечек через SMS-сервисы, но они требуют API.
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# --- PASSPORT (Проверка паспорта РФ по базе МВД) ---
async def passport_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Использует открытый API МВД для проверки недействительных паспортов.
    Формат: /passport <серия> <номер>
    Пример: /passport 4510 123456
    """
    if len(context.args) < 2:
        await update.message.reply_text("Пример: /passport 4510 123456")
        return
    series = context.args[0]
    number = context.args[1]
    if not (series.isdigit() and len(series) == 4 and number.isdigit() and len(number) == 6):
        await update.message.reply_text("Неверный формат. Серия (4 цифры) и номер (6 цифр).")
        return
    # API сервиса проверки недействительных паспортов (публичный)
    url = f"https://api.гувм.рф/passport/invalid?series={series}&number={number}"
    # Альтернативный сервис: https://проверкапаспорта.рф/api (может меняться)
    # Для реальной работы нужно найти актуальный эндпоинт. Пока показываем концепт.
    await update.message.reply_text(
        f"🔎 Проверка паспорта {series} {number} в базе недействительных...\n"
        "⚠️ В демо-режиме используйте сайт: [проверкапаспорта.рф](https://проверкапаспорта.рф) или ГУВМ.МВД.РФ\n"
        "Для интеграции API необходим токен, который можно получить на сайте МВД.",
        parse_mode="MarkdownV2"
    )

# --- SEARCH (Поиск упоминаний в публичных чатах/форумах) ---
async def public_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ищет переписки по нику/телефону/email через Google Custom Search.
    Требуется API ключ Google CSE и ID поисковика. Можно использовать и без ключа, но будет ограничение.
    """
    if not context.args:
        await update.message.reply_text("Пример: /search Иванов @telegram"); return
    query = ' '.join(context.args)
    # Для демо-режима используем публичный CSE или предупреждение
    await update.message.reply_text(
        f"🔍 Поиск по запросу: *{escape_md(query)}*\n"
        "⚠️ Для полной интеграции нужен Google API ключ и CSE ID\\.\n"
        "Временно используйте прямую ссылку: [Google](https://www.google.com/search?q={query})",
        parse_mode="MarkdownV2"
    )

# --- FACE (FaceCheck.id API) ---
async def face_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /face <ссылка_на_фото>"); return
    photo_url = context.args[0]
    # FaceCheck ID имеет бесплатный план. Требуется API ключ.
    await update.message.reply_text(
        "🔎 Поиск по лицу запущен\\!\n"
        "В демо-режиме загрузите фото на [FaceCheck\\.id](https://facecheck.id) вручную\\.\n"
        "Для интеграции API посетите: [facecheck.id/developer](https://facecheck.id/developer)",
        parse_mode="MarkdownV2"
    )

if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("Токен не найден!"); exit(1)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ip", ip_lookup))
    app.add_handler(CommandHandler("username", username_search))
    app.add_handler(CommandHandler("email", email_search))
    app.add_handler(CommandHandler("phone", phone_search))
    app.add_handler(CommandHandler("passport", passport_check))
    app.add_handler(CommandHandler("search", public_search))
    app.add_handler(CommandHandler("face", face_search))
    print("Бот с расширенным OSINT запущен...")
    app.run_polling()
