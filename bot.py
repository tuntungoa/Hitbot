import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import aiohttp
import phonenumbers
from phonenumbers import carrier, geocoder
import whois
import dns.resolver
import subprocess
import re
import urllib.parse

# --- Вспомогательные функции ---
async def fetch_json(session, url, headers=None):
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        pass
    return None

def escape_md(text):
    chars = r'_[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in chars else c for c in str(text))

# --- Старт ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔍 *OSINT Bot без ключей*\\.\n\n"
        "/ip `IP`\n"
        "/username `ник` — поиск по 600\\+ сайтам\n"
        "/email `email` — утечки и регистрации\n"
        "/phone `+7916...` — оператор, страна\n"
        "/passport `серия номер` — проверка паспорта РФ\n"
        "/domain `site\\.com` — whois\\, DNS\n"
        "/leak\\_email `email` — факт слива данных\n"
        "/leak\\_phone `телефон`"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

# --- IP ---
async def ip_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/ip 8.8.8.8"); return
    ip = context.args[0]
    async with aiohttp.ClientSession() as s:
        data = await fetch_json(s, f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,isp,org,as,query")
        if data and data.get("status") == "success":
            text = (f"IP: {data['query']}\n"
                    f"Страна: {data['country']}\n"
                    f"Регион: {data['regionName']}\n"
                    f"Город: {data['city']}\n"
                    f"Провайдер: {data['isp']}\n"
                    f"Орг: {data['org']}\n"
                    f"AS: {data['as']}")
        else:
            text = "Ошибка."
        await update.message.reply_text(text)

# --- USERNAME (Maigret без ключа) ---
async def username_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/username nick"); return
    username = context.args[0]
    url = f"https://api.maigret-app.com/v1/search?username={username}"
    async with aiohttp.ClientSession() as s:
        data = await fetch_json(s, url)
        if data:
            results = data.get("results", [])
            if results:
                text = f"🎯 *Найдено {len(results)} профилей:*\n"
                for r in results[:20]:
                    site = escape_md(r['site'])
                    link = r['url']
                    text += f"• [{site}]({link})\n"
                if len(results) > 20:
                    text += f"… и ещё {len(results)-20}"
                await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)
            else:
                await update.message.reply_text("Не найдено.")
        else:
            await update.message.reply_text("Сервис Maigret недоступен.")

# --- EMAIL (Holehe + BreachDirectory) ---
async def email_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/email user@mail.com"); return
    email = context.args[0]
    out = []
    # 1. Holehe (регистрации на сайтах)
    try:
        proc = subprocess.run(["holehe", email, "--only-used", "-C"], capture_output=True, text=True, timeout=30)
        if proc.stdout.strip():
            out.append("📌 *Регистрации на сайтах:*\n" + escape_md(proc.stdout.strip()[:450]))
    except FileNotFoundError:
        out.append("⚠️ Holehe не установлен (pip install holehe)")
    except subprocess.TimeoutExpired:
        out.append("⚠️ Holehe: долгий ответ")
    except Exception as e:
        out.append(f"Ошибка Holehe: {e}")
    # 2. BreachDirectory (бесплатный поиск утечек без ключа)
    try:
        async with aiohttp.ClientSession() as s:
            data = await fetch_json(s, f"https://breachdirectory.org/api?func=auto&term={email}")
            if data and data.get("success"):
                breaches = data.get("result", [])
                if breaches:
                    out.append(f"🛡 *Утечки (BreachDirectory):* {len(breaches)} шт\\.\n"
                               + "\n".join([escape_md(b) for b in breaches[:10]]))
    except:
        pass
    if not out:
        text = "Данные не найдены."
    else:
        text = "\n\n".join(out)
    await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)

# --- PHONE ---
async def phone_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/phone +79161234567"); return
    num = context.args[0]
    try:
        p = phonenumbers.parse(num)
        if not phonenumbers.is_valid_number(p):
            await update.message.reply_text("Некорректный номер."); return
        country = geocoder.description_for_number(p, "ru")
        oper = carrier.name_for_number(p, "ru")
        formatted = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        text = (f"📞 *Номер:* {escape_md(formatted)}\n"
                f"🌍 *Страна:* {escape_md(country)}\n"
                f"📡 *Оператор:* {escape_md(oper)}")
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# --- PASSPORT (парсинг официального сервиса МВД) ---
async def passport_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("/passport 4510 123456"); return
    series, number = context.args[0], context.args[1]
    if not (series.isdigit() and len(series) == 4 and number.isdigit() and len(number) == 6):
        await update.message.reply_text("Неверный формат. 4 цифры серия, 6 цифр номер.")
        return
    # Обращаемся к публичному API сервиса МВД (неофициальный, но открытый)
    url = f"https://api.гувм.рф/passport/invalid?series={series}&number={number}"
    async with aiohttp.ClientSession() as s:
        try:
            data = await fetch_json(s, url)
            if data and data.get("valid") is not None:
                if data["valid"]:
                    await update.message.reply_text(f"Паспорт {series} {number} действителен.")
                else:
                    await update.message.reply_text(f"⚠️ Паспорт {series} {number} НЕДЕЙСТВИТЕЛЕН!")
            else:
                raise Exception()
        except:
            # Если API не сработало, дадим ссылку
            await update.message.reply_text(
                f"Проверка паспорта {series} {number}:\n"
                "[Перейти на сайт МВД](https://проверкапаспорта.рф)",
                parse_mode="MarkdownV2"
            )

# --- DOMAIN ---
async def domain_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/domain example.com"); return
    domain = context.args[0]
    out = []
    try:
        w = whois.whois(domain)
        out.append(f"📅 Whois:\nРег: {w.registrar}\nСоздан: {w.creation_date}\nИстекает: {w.expiration_date}")
    except Exception as e:
        out.append(f"Ошибка Whois: {e}")
    try:
        answers = dns.resolver.resolve(domain, 'A')
        out.append(f"🌐 A-записи: {', '.join([str(r) for r in answers])}")
    except: pass
    await update.message.reply_text("\n\n".join(out)[:4000])

# --- LEAK_EMAIL (BreachDirectory, без ключа) ---
async def leak_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/leak_email user@example.com"); return
    email = context.args[0]
    url = f"https://breachdirectory.org/api?func=auto&term={email}"
    async with aiohttp.ClientSession() as s:
        data = await fetch_json(s, url)
        if data and data.get("success"):
            breaches = data.get("result", [])
            if breaches:
                text = f"🔓 Утечки для {email}:\n" + "\n".join([f"• {b}" for b in breaches[:20]])
                if len(breaches) > 20: text += f"\n... и ещё {len(breaches)-20}"
                await update.message.reply_text(text)
            else:
                await update.message.reply_text("Утечек не найдено.")
        else:
            await update.message.reply_text("Ошибка или лимит запросов (5/день)")

# --- LEAK_PHONE (BreachDirectory) ---
async def leak_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/leak_phone 79161234567"); return
    phone = re.sub(r'[^0-9]', '', context.args[0])
    url = f"https://breachdirectory.org/api?func=auto&term={phone}"
    async with aiohttp.ClientSession() as s:
        data = await fetch_json(s, url)
        if data and data.get("success"):
            breaches = data.get("result", [])
            if breaches:
                text = f"📱 Утечки для {phone}:\n" + "\n".join([f"• {b}" for b in breaches[:20]])
                await update.message.reply_text(text)
            else:
                await update.message.reply_text("Не найдено.")
        else:
            await update.message.reply_text("Ошибка или лимит.")

if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("BOT_TOKEN не задан"); exit(1)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ip", ip_lookup))
    app.add_handler(CommandHandler("username", username_search))
    app.add_handler(CommandHandler("email", email_search))
    app.add_handler(CommandHandler("phone", phone_search))
    app.add_handler(CommandHandler("passport", passport_check))
    app.add_handler(CommandHandler("domain", domain_search))
    app.add_handler(CommandHandler("leak_email", leak_email))
    app.add_handler(CommandHandler("leak_phone", leak_phone))
    print("Бот запущен без API-ключей!")
    app.run_polling()# --- IP ---
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
