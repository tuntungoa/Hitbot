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

# ----------  Справочники регионов  ----------
# Россия (DEF-коды)
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

# Украина (+380)
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

# ----------  Health‑check для Render  ----------
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

# ----------  Вспомогательные функции  ----------
async def fetch_json(session, url, headers=None):
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        return None

def escape_md(text):
    """Экранирование спецсимволов для MarkdownV2"""
    chars = r'_[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in chars else c for c in str(text))

def get_region_info(parsed_num, raw_number):
    """Возвращает строку с регионом/оператором на основе DEF-кода."""
    cc = parsed_num.country_code
    cleaned = re.sub(r'[^0-9]', '', raw_number)
    # РФ
    if cc == 7:
        if len(cleaned) >= 10 and cleaned[-10] == '9':
            def_code = cleaned[-10:-7]
            return DEF_REGIONS_RU.get(def_code, "")
    # Украина
    elif cc == 380:
        match = re.search(r'380(\d{3})', cleaned)
        if match:
            code = match.group(1)
            info = UA_CODES.get(code)
            if info:
                return f"{info[0]}, {info[1]}"
    return ""

async def get_leakcheck_data(query: str, query_type: str) -> str:
    """Возвращает строку с утечками из LeakCheck, если ключ задан."""
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
        source = escape_md(entry.get("source", "?"))
        password = escape_md(entry.get("password", "—"))
        username = escape_md(entry.get("username", "—"))
        email = escape_md(entry.get("email", "—"))
        name = escape_md(entry.get("name", "—"))
        address = escape_md(entry.get("address", "—"))
        lines.append(
            f"• {source}\n  ├ Логин: `{username}`\n  ├ Email: `{email}`\n"
            f"  ├ Пароль: `{password}`\n  ├ Имя: `{name}`\n  └ Адрес: `{address}`"
        )
    return "\n".join(lines)[:4000]

# ----------  Команды бота  ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔍 *ROCKET OSINT Bot*\\.\n\n"
        "/ip `IP`\n"
        "/username `ник` – поиск по 600\\+ сайтам\n"
        "/email `email` – утечки и регистрации\n"
        "/phone `+380...` или `+7916...` – оператор, регион\n"
        "/passport `серия номер` – проверка РФ\n"
        "/domain `site.com` – whois, DNS\n"
        "/leak\\_email `email` – факт утечек\n"
        "/leak\\_phone `телефон` – факт утечек\n"
        "/leak\\_phone\\_full `телефон` – полные данные (LeakCheck)"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def ip_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/ip 8.8.8.8"); return
    ip = context.args[0]
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,isp,org,as,query")
        if data and data.get("status") == "success":
            text = (f"IP: {escape_md(data['query'])}\n"
                    f"Страна: {escape_md(data['country'])}\n"
                    f"Регион: {escape_md(data['regionName'])}\n"
                    f"Город: {escape_md(data['city'])}\n"
                    f"Провайдер: {escape_md(data['isp'])}\n"
                    f"Орг: {escape_md(data['org'])}\n"
                    f"AS: {escape_md(data['as'])}")
        else:
            text = "Ошибка."
        await update.message.reply_text(text, parse_mode="MarkdownV2")

async def username_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/username nick"); return
    username = context.args[0]
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, f"https://api.maigret-app.com/v1/search?username={username}")
        if data:
            results = data.get("results", [])
            if results:
                text = f"🎯 Найдено {len(results)} профилей:\n"
                for r in results[:20]:
                    site = escape_md(r['site'])
                    url = r['url']
                    text += f"• [{site}]({url})\n"
                if len(results) > 20:
                    text += f"… +{len(results)-20}"
                await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)
            else:
                await update.message.reply_text("Не найдено.")
        else:
            await update.message.reply_text("Сервис Maigret недоступен.")

async def email_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/email user@mail.com"); return
    email = context.args[0]
    out = []
    # Holehe
    try:
        proc = subprocess.run(["holehe", email, "--only-used", "-C"],
                              capture_output=True, text=True, timeout=30)
        if proc.stdout.strip():
            out.append("📌 Регистрации:\n" + escape_md(proc.stdout.strip()[:500]))
    except FileNotFoundError:
        out.append("⚠️ Holehe не установлен.")
    except subprocess.TimeoutExpired:
        out.append("⚠️ Holehe: долгий ответ")
    except Exception as e:
        out.append(f"Ошибка Holehe: {escape_md(str(e))}")
    # BreachDirectory
    try:
        async with aiohttp_client.ClientSession() as s:
            data = await fetch_json(s, f"https://breachdirectory.org/api?func=auto&term={email}")
            if data and data.get("success"):
                breaches = data.get("result", [])
                if breaches:
                    out.append(f"🛡 Утечки: {', '.join([escape_md(b) for b in breaches[:10]])}")
    except:
        pass
    text = "\n\n".join(out) if out else "Данные не найдены."
    await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)

async def phone_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /phone +79161234567 или +380501234567")
        return
    raw_num = context.args[0].strip()
    # автоматически добавляем '+', если его нет
    if not raw_num.startswith('+'):
        raw_num = '+' + raw_num
    try:
        p = phonenumbers.parse(raw_num, None)  # None – автоопределение страны
        if not phonenumbers.is_valid_number(p):
            await update.message.reply_text("Некорректный номер.")
            return
        country = geocoder.description_for_number(p, "ru") or "Неизвестно"
        operator = carrier.name_for_number(p, "ru") or "Неизвестно"
        formatted = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        region = get_region_info(p, raw_num)
        # Экранируем все данные
        text = (f"📞 *Номер:* {escape_md(formatted)}\n"
                f"🌍 *Страна:* {escape_md(country)}\n"
                f"📡 *Оператор:* {escape_md(operator)}")
        if region:
            text += f"\n📍 *Регион:* {escape_md(region)}"
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {escape_md(str(e))}", parse_mode="MarkdownV2")

async def passport_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("/passport 4510 123456")
        return
    series, number = context.args[0], context.args[1]
    if not (series.isdigit() and len(series) == 4 and number.isdigit() and len(number) == 6):
        await update.message.reply_text("Формат: 4 цифры серия, 6 цифр номер.")
        return
    await update.message.reply_text(
        f"Проверьте паспорт {escape_md(series)} {escape_md(number)} на [сайте МВД](https://проверкапаспорта.рф)",
        parse_mode="MarkdownV2"
    )

async def domain_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/domain example.com")
        return
    domain = context.args[0]
    out = []
    try:
        w = whois.whois(domain)
        out.append(f"📅 Whois:\nРег: {escape_md(str(w.registrar))}\n"
                   f"Создан: {escape_md(str(w.creation_date))}\n"
                   f"Истекает: {escape_md(str(w.expiration_date))}")
    except Exception as e:
        out.append(f"Ошибка Whois: {escape_md(str(e))}")
    try:
        answers = dns.resolver.resolve(domain, 'A')
        out.append(f"🌐 A: {', '.join([escape_md(str(r)) for r in answers])}")
    except:
        pass
    await update.message.reply_text("\n\n".join(out)[:4000], parse_mode="MarkdownV2")

async def leak_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/leak_email user@example.com"); return
    email = context.args[0]
    url = f"https://breachdirectory.org/api?func=auto&term={email}"
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, url)
        if data and data.get("success"):
            breaches = data.get("result", [])
            if breaches:
                text = f"🔓 Утечки для {escape_md(email)}:\n" + \
                       "\n".join([f"• {escape_md(b)}" for b in breaches[:20]])
                await update.message.reply_text(text, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text("Утечек не найдено.")
        else:
            await update.message.reply_text("Ошибка или лимит (5/день)")

async def leak_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/leak_phone 79161234567"); return
    phone = re.sub(r'[^0-9]', '', context.args[0])
    url = f"https://breachdirectory.org/api?func=auto&term={phone}"
    async with aiohttp_client.ClientSession() as s:
        data = await fetch_json(s, url)
        if data and data.get("success"):
            breaches = data.get("result", [])
            if breaches:
                text = f"📱 Утечки для {escape_md(phone)}:\n" + \
                       "\n".join([f"• {escape_md(b)}" for b in breaches[:20]])
                await update.message.reply_text(text, parse_mode="MarkdownV2")
            else:
                await update.message.reply_text("Не найдено.")
        else:
            await update.message.reply_text("Ошибка или лимит (5/день)")

async def leak_phone_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/leak_phone_full +79161234567"); return
    phone = re.sub(r'[^0-9]', '', context.args[0])
    text = await get_leakcheck_data(phone, "phone")
    if not text:
        if os.environ.get("LEAKCHECK_API"):
            await update.message.reply_text("Утечек не найдено или лимит (50/мес).")
        else:
            await update.message.reply_text(
                "Нужен ключ LeakCheck API\\. Получите бесплатно на [leakcheck.io](https://leakcheck.io) "
                "и добавьте переменную `LEAKCHECK_API` в Render\\.",
                parse_mode="MarkdownV2"
            )
    else:
        await update.message.reply_text(text, parse_mode="MarkdownV2", disable_web_page_preview=True)

# ----------  Точка входа  ----------
def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("BOT_TOKEN не задан"); exit(1)

    # запускаем health‑check в фоновом потоке
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
    print("ROCKET OSINT Bot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
