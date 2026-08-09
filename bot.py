import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import aiohttp

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот готов. Используй /ip <адрес> для проверки IP.")

async def ip_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Пример: /ip 8.8.8.8")
        return
    ip = context.args[0]
    url = f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,isp,org,as,query"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("status") == "success":
                    text = (
                        f"IP: {data['query']}\n"
                        f"Страна: {data['country']}\n"
                        f"Регион: {data['regionName']}\n"
                        f"Город: {data['city']}\n"
                        f"Провайдер: {data['isp']}\n"
                        f"Организация: {data['org']}\n"
                        f"AS: {data['as']}"
                    )
                else:
                    text = "Ошибка: неверный IP или сервис недоступен."
                await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN")
    if not TOKEN:
        print("Токен не найден! Укажите переменную окружения BOT_TOKEN")
        exit(1)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ip", ip_lookup))
    print("Бот запущен...")
    app.run_polling()
