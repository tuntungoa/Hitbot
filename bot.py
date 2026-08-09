import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import aiohttp as aiohttp_client
import phonenumbers
from phonenumbers import carrier, geocoder
import whois
import dns.resolver
import subprocess
import re

# ========== Справочники регионов ==========
# DEF-коды России (первые 3 цифры после +7)
DEF_REGIONS_RU = {
    "900": "Москва и МО", "901": "Москва и МО", "902": "Москва и МО",
    "903": "Москва и МО", "904": "Москва и МО", "905": "Москва и МО",
    "906": "Москва и МО", "908": "Москва и МО", "909": "Москва и МО",
    "910": "Москва и МО", "911": "Санкт-Петербург", "912": "Санкт-Петербург",
    "913": "Новосибирская обл.", "914": "Хабаровский край", "915": "Москва и МО",
    "916": "Москва и МО", "917": "Татарстан", "918": "Краснодарский край",
    "919": "Челябинская обл.", "920": "Нижегородская обл.", "921": "Санкт-Петербург",
    "922": "Свердловская обл.", "923": "Кемеровская обл.", "924": "Приморский край",
    "925": "Москва и МО", "926": "Москва и МО", "927": "Самарская обл.",
    "928": "Ростовская обл.", "929": "Москва и МО", "930": "Москва и МО",
    "931": "Санкт-Петербург", "932": "Красноярский край", "933": "Иркутская обл.",
    "934": "Волгоградская обл.", "935": "Пермский край", "936": "Москва и МО",
    "937": "Башкортостан", "938": "Алтайский край", "939": "Омская обл.",
    "940": "Ставропольский край", "941": "Саратовская обл.", "942": "Воронежская обл.",
    "943": "Тюменская обл.", "944": "Удмуртия", "945": "Оренбургская обл.",
    "946": "Крым", "947": "Владимирская обл.", "948": "Тверская обл.",
    "949": "Ярославская обл.", "950": "Ульяновская обл.", "951": "Белгородская обл.",
    "952": "Кировская обл.", "953": "Рязанская обл.", "954": "Ивановская обл.",
    "955": "Калужская обл.", "956": "Смоленская обл.", "957": "Курская обл.",
    "958": "Липецкая обл.", "959": "Тульская обл.", "960": "Вологодская обл.",
    "961": "Калининградская обл.", "962": "Камчатский край", "963": "Амурская обл.",
    "964": "Сахалинская обл.", "965": "Москва и МО", "966": "Мурманская обл.",
    "967": "Коми", "968": "Архангельская обл.", "969": "Карелия",
    "970": "Забайкальский край", "971": "Якутия", "972": "Магаданская обл.",
    "973": "Тамбовская обл.", "974": "Псковская обл.", "975": "Новгородская обл.",
    "976": "Костромская обл.", "977": "Москва и МО", "978": "Мордовия",
    "979": "Марий Эл", "980": "Чувашия", "981": "Санкт-Петербург",
    "982": "Курганская обл.", "983": "Пензенская обл.", "984": "Астраханская обл.",
    "985": "Москва и МО", "986": "Дагестан", "987": "Северная Осетия",
    "988": "Чечня", "989": "Адыгея", "990": "Кабардино-Балкария",
    "991": "Карачаево-Черкесия", "992": "Ингушетия", "993": "Калмыкия",
    "994": "Тыва", "995": "Хакасия", "996": "Алтай", "997": "Брянская обл.",
    "998": "Орловская обл.", "999": "Томская обл."
}

# Коды мобильных Украины (+380) – оператор и типичный регион
UA_CODES = {
    "050": ("Vodafone Украина", "Киев, центральные регионы"),
    "066": ("Vodafone Украина", "Киев, центральные регионы"),
    "095": ("Vodafone Украина", "Киев, центральные регионы"),
    "099": ("Vodafone Украина", "Киев, центральные регионы"),
    "067": ("Киевстар", "Киев, все регионы"),
    "068": ("Киевстар", "Киев, все регионы"),
    "096": ("Киевстар", "Киев, все регионы"),
    "097": ("Киевстар", "Киев, все регионы"),
    "098": ("Киевстар", "Киев, все регионы"),
    "063": ("Lifecell", "Западная Украина, Киев"),
    "073": ("Lifecell", "Западная Украина, Киев"),
    "093": ("Lifecell", "Западная Украина, Киев"),
    "091": ("ТриМоб", "Киев"),
    "092": ("PEOPLEnet", "Киев"),
    "094": ("Интертелеком", "Киев"),
    "039": ("Голден Телеком", "Киев"),
}

# Health сервер
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"Health server on port {port}")
    server.serve_forever()

# Асинхронные хелперы
async def fetch_json(session, url, headers=None):
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        return None

def get_region_info(parsed_num, raw_number):
    """Возвращает строку с регионом/оператором на основе DEF-кода."""
    country_code = parsed_num.country_code
    # Россия
    if country_code == 7:
        cleaned = re.sub(r'[^0-9]', '', raw_number)
        if len(cleaned) >= 10 and cleaned[-10] == '9':
            def_code = cleaned[-10:-7]
            return DEF_REGIONS_RU.get(def_code, "")
    # Украина
    if country_code == 380:
        cleaned = re.sub(r'[^0-9]', '', raw_number)
        # убираем 380, ищем код из 3 цифр
        match = re.search(r'380(\d{3})', cleaned)
        if match:
            code = match.group(1)
            info = UA_CODES.get(code)
            if info:
                return f"{info[0]}, {info[1]}"
    return ""

async def get_leakcheck_data(query: str, query_type: str) -> str:
    api_key = os.environ.get("LEAKCHECK_API")
    if not api_key:
        return ""
    url = "https://leakcheck.io/api/public"
    headers = {"X-API-Key": api_key}
    params = {"check": query, "type": query_type}
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, url, headers=headers, params=params)
    if not data or not data.get("success"):
        return ""
    entries = data.get("result", [])
    if not entries:
        return ""
    lines = [f"🔓 *LeakCheck: {len(entries)} записей*"]
    for entry in entries[:5]:
        source = entry.get("source", "?")
        password = entry.get("password", "—")
        username = entry.get("username", "—")
        email = entry.get("email", "—")
        name = entry.get("name", "—")
        address = entry.get("address", "—")
        lines.append(
            f"• {source}\n  ├ Логин: `{username}`\n  ├ Email: `{email}`\n"
            f"  ├ Пароль: `{password}`\n  ├ Имя: `{name}`\n  └ Адрес: `{address}`"
        )
    return "\n".join(lines)[:4000]

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔍 *ROCKET OSINT Bot*\\.\n\n"
        "/ip `IP`\n"
        "/username `ник` – поиск по 600\\+ сайтам\n"
        "/email `email` – утечки и регистрации\n"
        "/phone `+380...` или `+7916...` – оператор, регион\n"
        "/passport `серия номер` – проверка РФ\n"
        "/domain `site.com` – whois, DNS\n"
        "/leak_email `email` – факт утечек\n"
        "/leak_phone `телефон` – факт утечек\n"
        "/leak_phone_full `телефон` – полные данные \\(LeakCheck, нужен ключ\\)"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def ip_lookup(update, context):
    if not context.args: return
    ip = context.args[0]
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,isp,org,as,query")
        if data and data.get("status") == "success":
            text = (f"IP: {data['query']}\nСтрана: {data['country']}\n"
                    f"Регион: {data['regionName']}\nГород: {data['city']}\n"
                    f"Провайдер: {data['isp']}\nОрг: {data['org']}\nAS: {data['as']}")
        else:
            text = "Ошибка."
        await update.message.reply_text(text)

async def username_search(update, context):
    if not context.args: return
    username = context.args[0]
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, f"https://api.maigret-app.com/v1/search?username={username}")
        if data:
            results = data.get("results", [])
            if results:
                text = f"🎯 Найдено {len(results)} профилей:\n"
                for r in results[:20]:
                    text += f"• {r['site']}: {r['url']}\n"
                if len(results) > 20: text += f"… +{len(results)-20}"
                await update.message.reply_text(text[:4000])
            else:
                await update.message.reply_text("Не найдено.")
        else:
            await update.message.reply_text("Сервис Maigret недоступен.")

async def email_search(update, context):
    if not context.args: return
    email = context.args[0]
    out = []
    try:
        proc = subprocess.run(["holehe", email, "--only-used", "-C"], capture_output=True, text=True, timeout=30)
        if proc.stdout.strip():
            out.append("📌 Регистрации:\n" + proc.stdout.strip()[:500])
    except: pass
    try:
        async with aiohttp_client.ClientSession() as s:
            data = await fetch_json(s, f"https://breachdirectory.org/api?func=auto&term={email}")
            if data and data.get("success"):
                breaches = data.get("result", [])
                if breaches:
                    out.append(f"🛡 Утечки: {', '.join(breaches[:10])}")
    except: pass
    await update.message.reply_text("\n\n".join(out)[:4000] if out else "Данные не найдены.")

async def phone_search(update, context):
    if not context.args:
        await update.message.reply_text("/phone +79161234567 или +380501234567")
        return
    num = context.args[0]
    try:
        p = phonenumbers.parse(num)
        if not phonenumbers.is_valid_number(p):
            await update.message.reply_text("Некорректный номер.")
            return
        country = geocoder.description_for_number(p, "ru") or "Неизвестно"
        operator = carrier.name_for_number(p, "ru") or "Неизвестно"
        formatted = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        region = get_region_info(p, num)
        text = f"📞 *Номер:* {formatted}\n🌍 *Страна:* {country}\n📡 *Оператор:* {operator}"
        if region:
            text += f"\n📍 *Регион:* {region}"
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def passport_check(update, context):
    if len(context.args) < 2: return
    series, number = context.args[0], context.args[1]
    if not (series.isdigit() and len(series)==4 and number.isdigit() and len(number)==6):
        await update.message.reply_text("Формат: 4 цифры серия, 6 цифр номер."); return
    await update.message.reply_text(
        f"Проверьте паспорт {series} {number} на [сайте МВД](https://проверкапаспорта.рф)",
        parse_mode="MarkdownV2")

async def domain_search(update, context):
    if not context.args: return
    domain = context.args[0]
    out = []
    try:
        w = whois.whois(domain)
        out.append(f"📅 Whois:\nРег: {w.registrar}\nСоздан: {w.creation_date}\nИстекает: {w.expiration_date}")
    except: pass
    try:
        answers = dns.resolver.resolve(domain, 'A')
        out.append(f"🌐 A: {', '.join([str(r) for r in answers])}")
    except: pass
    await update.message.reply_text("\n\n".join(out)[:4000] if out else "Не удалось получить данные.")

async def leak_email(update, context):
    if not context.args: return
    email = context.args[0]
    url = f"https://breachdirectory.org/api?func=auto&term={email}"
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, url)
        if data and data.get("success"):
            breaches = data.get("result", [])
            if breaches:
                text = f"🔓 Утечки для {email}:\n" + "\n".join([f"• {b}" for b in breaches[:20]])
                await update.message.reply_text(text[:4000])
            else:
                await update.message.reply_text("Утечек не найдено.")
        else:
            await update.message.reply_text("Ошибка или лимит.")

async def leak_phone(update, context):
    if not context.args: return
    phone = re.sub(r'[^0-9]', '', context.args[0])
    url = f"https://breachdirectory.org/api?func=auto&term={phone}"
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, url)
        if data and data.get("success"):
            breaches = data.get("result", [])
            if breaches:
                text = f"📱 Утечки для {phone}:\n" + "\n".join([f"• {b}" for b in breaches[:20]])
                await update.message.reply_text(text[:4000])
            else:
                await update.message.reply_text("Не найдено.")
        else:
            await update.message.reply_text("Ошибка или лимит.")

async def leak_phone_full(update, context):
    if not context.args: return
    phone = re.sub(r'[^0-9]', '', context.args[0])
    # Убираем проверку на РФ – теперь универсально
    text = await get_leakcheck_data(phone, "phone")
    if not text:
        if os.environ.get("LEAKCHECK_API"):
            await update.message.reply_text("Утечек не найдено или лимит (50/мес).")
        else:
            await update.message.reply_text(
                "Нужен ключ LeakCheck API\\. Получите бесплатно на [leakcheck.io](https://leakcheck.io) и добавьте переменную `LEAKCHECK_API` в Render\\.",
                parse_mode="MarkdownV2"
            )
    else:
        await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)

def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("BOT_TOKEN не задан"); exit(1)
    threading.Thread(target=run_health_server, daemon=True).start()
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
    app.add_handler(CommandHandler("leak_phone_full", leak_phone_full))
    print("Бот с поддержкой Украины и LeakCheck запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
