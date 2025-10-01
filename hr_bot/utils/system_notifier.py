# hr_bot/utils/system_notifier.py
import os
import asyncio
from aiogram import Bot
from hr_bot.db.models import SessionLocal, TelegramUser

async def send_system_alert(message_text: str):
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    db = SessionLocal()
    try:
        # Отправляем всем: и админам, и пользователям
        all_users = db.query(TelegramUser).all()
        for user in all_users:
            try:
                await bot.send_message(chat_id=user.telegram_id, text=message_text)
            except Exception:
                pass # Игнорируем ошибки, если не удалось доставить кому-то одному
    finally:
        await bot.session.close()
        db.close()