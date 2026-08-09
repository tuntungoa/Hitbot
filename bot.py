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

# --- Простой HTTP-сервер в отдельном потоке (чтобы Render видел порт) ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"Health server listening on port {port}")
    server.serve_forever()

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

# --- Команды бота ---
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

async def ip_lookup(update, context):
    if not context.args: await update.message.reply_text("/ip 8.8.8.8"); return
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
    if not context.args: await update.message.reply_text("/username nick"); return
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
    if not context.args: await update.message.reply_text("/email user@mail.com"); return
    email = context.args[0]
    out = []
    try:
        proc = subprocess.run(["holehe", email, "--only-used", "-C"], capture_output=True, text=True, timeout=30)
        if proc.stdout.strip():
            out.append("📌 Регистрации:\n" + proc.stdout.strip()[:500])
    except FileNotFoundError:
        out.append("⚠️ Holehe не установлен.")
    except subprocess.TimeoutExpired:
        out.append("⚠️ Holehe: долгий ответ")
    except Exception as e:
        out.append(f"Ошибка Holehe: {e}")
    # BreachDirectory
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
    if not context.args: await update.message.reply_text("/phone +79161234567"); return
    num = context.args[0]
    try:
        p = phonenumbers.parse(num)
        if not phonenumbers.is_valid_number(p):
            await update.message.reply_text("Некорректный номер."); return
        country = geocoder.description_for_number(p, "ru")
        oper = carrier.name_for_number(p, "ru")
        formatted = phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        text = f"📞 {formatted}\n🌍 {country}\n📡 {oper}"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def passport_check(update, context):
    if len(context.args) < 2: await update.message.reply_text("/passport 4510 123456"); return
    series, number = context.args[0], context.args[1]
    if not (series.isdigit() and len(series)==4 and number.isdigit() and len(number)==6):
        await update.message.reply_text("Неверный формат."); return
    url = f"https://api.гувм.рф/passport/invalid?series={series}&number={number}"
    async with aiohttp_client.ClientSession() as s:
        try:
            data = await fetch_json(s, url)
            if data and data.get("valid") is not None:
                await update.message.reply_text(f"Паспорт {series} {number} {'действителен' if data['valid'] else 'НЕДЕЙСТВИТЕЛЕН!'}")
            else:
                raise Exception()
        except:
            await update.message.reply_text(f"Проверьте паспорт {series} {number} на [сайте МВД](https://проверкапаспорта.рф)", parse_mode="MarkdownV2")

async def domain_search(update, context):
    if not context.args: return
    domain = context.args[0]
    out = []
    try:
        w = whois.whois(domain)
        out.append(f"📅 Whois:\nРегистратор: {w.registrar}\nСоздан: {w.creation_date}\nИстекает: {w.expiration_date}")
    except Exception as e:
        out.append(f"Ошибка Whois: {e}")
    try:
        answers = dns.resolver.resolve(domain, 'A')
        out.append(f"🌐 A: {', '.join([str(r) for r in answers])}")
    except: pass
    await update.message.reply_text("\n\n".join(out)[:4000])

async def leak_email(update, context):
    if not context.args: await update.message.reply_text("/leak_email user@example.com"); return
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
            await update.message.reply_text("Ошибка или лимит запросов (5/день)")

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

# === Главная функция (синхронная) ===
def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("BOT_TOKEN не задан"); exit(1)

    # Запускаем health-check сервер в отдельном потоке
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Создаём приложение бота
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
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
