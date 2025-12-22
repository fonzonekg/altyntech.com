import telebot
from telebot import types
import os
import logging
from datetime import datetime
import re
import sys

# ===== НАСТРОЙКИ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Токен бота и группа поддержки
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8184028081:AAE72PAnvU498oTA4pJh0GRHxMxOxsI8kr8")
# Закрытая группа поддержки: https://t.me/+2cRF5q9dtlZkOWYy
SUPPORT_GROUP_ID = -1003639294816 # ID закрытой группы (отрицательное число)

# Инициализация бота
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Хранилище для ID пользователей и их сообщений
user_messages = {}

# ===== ФУНКЦИИ =====
def format_time() -> str:
    """Форматирование времени"""
    return datetime.now().strftime("%H:%M")

def format_date() -> str:
    """Форматирование даты"""
    return datetime.now().strftime("%d.%m.%Y")

def clean_text(text: str) -> str:
    """Очистка текста от лишних пробелов"""
    if not text:
        return ""
    return ' '.join(text.split())

def get_user_display_name(user) -> str:
    """Получение отображаемого имени пользователя"""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.username:
        return f"@{user.username}"
    else:
        return "Пользователь"

# ===== ОБРАБОТКА КОМАНД =====
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Обработка команды /start"""
    user_id = message.from_user.id
    
    welcome_text = """<b>🛠️ Служба поддержки</b>

Привет! Напишите ваше сообщение, и наша команда поможет вам.

<code>━━━━━━━━━━━━━━</code>

<b>Как это работает:</b>
1. Вы пишете сообщение
2. Оно отправляется в группу поддержки
3. Специалист отвечает вам

<code>━━━━━━━━━━━━━━</code>

<b>Просто напишите ниже:</b>"""
    
    try:
        bot.send_message(user_id, welcome_text)
        logger.info(f"Новый пользователь: {user_id}")
    except Exception as e:
        logger.error(f"Ошибка приветствия: {e}")

@bot.message_handler(commands=['help'])
def handle_help(message):
    """Обработка команды /help"""
    help_text = """<b>📋 Помощь</b>

<code>━━━━━━━━━━━━━━</code>

<b>Доступные команды:</b>
• /start - начать диалог
• /help - эта справка

<code>━━━━━━━━━━━━━━</code>

<b>Что можно отправить:</b>
• Текст сообщения
• Фотографии
• Документы

<b>Время ответа:</b> до 24 часов"""
    
    bot.send_message(message.chat.id, help_text)

# ===== ОБРАБОТКА ЛИЧНЫХ СООБЩЕНИЙ =====
@bot.message_handler(func=lambda message: message.chat.type == 'private' and not message.text.startswith('/'))
def handle_private_message(message):
    """Обработка личных сообщений от пользователей"""
    user_id = message.from_user.id
    user = message.from_user
    
    # Сохраняем информацию о пользователе
    user_display_name = get_user_display_name(user)
    user_info = f"{user_display_name} (ID: {user_id})"
    if user.username:
        user_info += f" | @{user.username}"
    
    # Подтверждение пользователю
    confirm_text = f"""<b>✅ Отправлено</b>

<code>━━━━━━━━━━━━━━</code>

Ваше обращение получено и отправлено в поддержку.

<b>Время:</b> {format_time()}
<b>Дата:</b> {format_date()}"""
    
    try:
        bot.send_message(user_id, confirm_text)
        
        # Формируем сообщение для группы поддержки
        if message.text:
            # Текстовое сообщение
            group_message = f"""<b>📩 Новое обращение</b>

<code>━━━━━━━━━━━━━━</code>

<b>👤 От:</b> {user_display_name}
<b>🆔 ID:</b> <code>{user_id}</code>
<b>🕐 {format_time()} • {format_date()}</b>

<code>━━━━━━━━━━━━━━</code>

{clean_text(message.text)}

<code>━━━━━━━━━━━━━━</code>
<i>Ответьте на это сообщение, чтобы отправить ответ пользователю</i>"""
            
            # Отправляем в группу
            sent_msg = bot.send_message(
                SUPPORT_GROUP_ID,
                group_message,
                parse_mode="HTML"
            )
            
        elif message.photo:
            # Фото с подписью или без
            photo_id = message.photo[-1].file_id
            caption = message.caption or ""
            
            group_caption = f"""<b>📷 Фото от пользователя</b>

<code>━━━━━━━━━━━━━━</code>

<b>👤 От:</b> {user_display_name}
<b>🆔 ID:</b> <code>{user_id}</code>
<b>🕐 {format_time()} • {format_date()}</b>"""
            
            if caption:
                group_caption += f"\n\n<b>Подпись:</b>\n{clean_text(caption)}"
            
            group_caption += f"""\n\n<code>━━━━━━━━━━━━━━</code>
<i>Ответьте на это сообщение, чтобы отправить ответ пользователю</i>"""
            
            sent_msg = bot.send_photo(
                SUPPORT_GROUP_ID,
                photo_id,
                caption=group_caption,
                parse_mode="HTML"
            )
            
        elif message.document:
            # Документ с подписью или без
            doc_id = message.document.file_id
            caption = message.caption or ""
            
            group_caption = f"""<b>📎 Документ от пользователя</b>

<code>━━━━━━━━━━━━━━</code>

<b>👤 От:</b> {user_display_name}
<b>🆔 ID:</b> <code>{user_id}</code>
<b>🕐 {format_time()} • {format_date()}</b>
<b>📄 Файл:</b> {message.document.file_name}"""
            
            if caption:
                group_caption += f"\n\n<b>Описание:</b>\n{clean_text(caption)}"
            
            group_caption += f"""\n\n<code>━━━━━━━━━━━━━━</code>
<i>Ответьте на это сообщение, чтобы отправить ответ пользователю</i>"""
            
            sent_msg = bot.send_document(
                SUPPORT_GROUP_ID,
                doc_id,
                caption=group_caption,
                parse_mode="HTML"
            )
            
        elif message.video:
            # Видео
            video_id = message.video.file_id
            caption = message.caption or ""
            
            group_caption = f"""<b>🎬 Видео от пользователя</b>

<code>━━━━━━━━━━━━━━</code>

<b>👤 От:</b> {user_display_name}
<b>🆔 ID:</b> <code>{user_id}</code>
<b>🕐 {format_time()} • {format_date()}</b>"""
            
            if caption:
                group_caption += f"\n\n<b>Описание:</b>\n{clean_text(caption)}"
            
            group_caption += f"""\n\n<code>━━━━━━━━━━━━━━</code>
<i>Ответьте на это сообщение, чтобы отправить ответ пользователю</i>"""
            
            sent_msg = bot.send_video(
                SUPPORT_GROUP_ID,
                video_id,
                caption=group_caption,
                parse_mode="HTML"
            )
        
        # Сохраняем связь между сообщением в группе и пользователем
        user_messages[sent_msg.message_id] = user_id
        
        logger.info(f"Обращение от {user_id} отправлено в группу {SUPPORT_GROUP_ID}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки в группу: {e}")
        
        error_text = f"""<b>⚠️ Ошибка отправки</b>

<code>━━━━━━━━━━━━━━</code>

Не удалось отправить ваше сообщение в поддержку.

<b>Причина:</b> {str(e)}

Попробуйте отправить сообщение еще раз через несколько минут."""
        
        bot.send_message(user_id, error_text)

# ===== ОБРАБОТКА ОТВЕТОВ В ГРУППЕ =====
@bot.message_handler(func=lambda message: message.chat.id == SUPPORT_GROUP_ID)
def handle_group_message(message):
    """Обработка сообщений в группе поддержки"""
    
    # Игнорируем сообщения от самого бота
    if message.from_user.is_bot:
        return
    
    # Проверяем, является ли сообщение ответом на обращение пользователя
    if message.reply_to_message:
        replied_msg = message.reply_to_message
        
        # Проверяем, есть ли это сообщение в сохраненных
        if replied_msg.message_id in user_messages:
            user_id = user_messages[replied_msg.message_id]
            
            # Определяем тип контента и формируем ответ
            try:
                if message.text:
                    # Текстовый ответ
                    response_text = f"""<b>📨 Ответ от поддержки</b>

<code>━━━━━━━━━━━━━━</code>

{clean_text(message.text)}

<code>━━━━━━━━━━━━━━</code>
<i>Для уточняющего вопроса ответьте на это сообщение</i>"""
                    
                    bot.send_message(user_id, response_text)
                    
                    # Подтверждение в группе
                    bot.send_message(
                        SUPPORT_GROUP_ID,
                        f"✅ <b>Ответ отправлен пользователю</b>\n"
                        f"👤 ID: <code>{user_id}</code>\n"
                        f"🕐 {format_time()}",
                        reply_to_message_id=message.message_id
                    )
                    
                    logger.info(f"Текстовый ответ пользователю {user_id} от {message.from_user.id}")
                    
                elif message.photo:
                    # Ответ с фото
                    photo_id = message.photo[-1].file_id
                    caption = message.caption or ""
                    
                    response_caption = "<b>📷 Фото от поддержки</b>"
                    if caption:
                        response_caption += f"\n\n{caption}"
                    
                    bot.send_photo(user_id, photo_id, caption=response_caption)
                    
                    bot.send_message(
                        SUPPORT_GROUP_ID,
                        f"✅ <b>Фото отправлено пользователю</b>\n"
                        f"👤 ID: <code>{user_id}</code>\n"
                        f"🕐 {format_time()}",
                        reply_to_message_id=message.message_id
                    )
                    
                    logger.info(f"Фото отправлено пользователю {user_id}")
                    
                elif message.document:
                    # Ответ с документом
                    doc_id = message.document.file_id
                    caption = message.caption or ""
                    
                    response_caption = "<b>📎 Документ от поддержки</b>"
                    if caption:
                        response_caption += f"\n\n{caption}"
                    
                    bot.send_document(user_id, doc_id, caption=response_caption)
                    
                    bot.send_message(
                        SUPPORT_GROUP_ID,
                        f"✅ <b>Документ отправлен пользователю</b>\n"
                        f"👤 ID: <code>{user_id}</code>\n"
                        f"🕐 {format_time()}",
                        reply_to_message_id=message.message_id
                    )
                    
                    logger.info(f"Документ отправлен пользователю {user_id}")
                    
                elif message.video:
                    # Ответ с видео
                    video_id = message.video.file_id
                    caption = message.caption or ""
                    
                    response_caption = "<b>🎬 Видео от поддержки</b>"
                    if caption:
                        response_caption += f"\n\n{caption}"
                    
                    bot.send_video(user_id, video_id, caption=response_caption)
                    
                    bot.send_message(
                        SUPPORT_GROUP_ID,
                        f"✅ <b>Видео отправлено пользователю</b>\n"
                        f"👤 ID: <code>{user_id}</code>\n"
                        f"🕐 {format_time()}",
                        reply_to_message_id=message.message_id
                    )
                    
                    logger.info(f"Видео отправлено пользователю {user_id}")
                
            except Exception as e:
                error_msg = f"""<b>❌ Ошибка отправки</b>

Не удалось отправить ответ пользователю.

<b>Причина:</b> {str(e)}

Возможно, пользователь заблокировал бота или удалил чат."""
                
                bot.send_message(
                    SUPPORT_GROUP_ID,
                    error_msg,
                    reply_to_message_id=message.message_id
                )
                logger.error(f"Ошибка отправки ответа пользователю {user_id}: {e}")

# ===== АДМИН КОМАНДЫ =====
@bot.message_handler(commands=['status'])
def handle_status(message):
    """Проверка статуса бота"""
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    
    status_text = f"""<b>🤖 Статус бота</b>

<code>━━━━━━━━━━━━━━</code>

<b>Время работы:</b> {format_time()} • {format_date()}
<b>Активных чатов:</b> {len(user_messages)}
<b>Группа:</b> {SUPPORT_GROUP_ID}

<code>━━━━━━━━━━━━━━</code>
<i>Бот работает в штатном режиме</i>"""
    
    bot.send_message(message.chat.id, status_text)

@bot.message_handler(commands=['clear'])
def handle_clear(message):
    """Очистка старых сообщений"""
    if message.chat.id != SUPPORT_GROUP_ID:
        return
    
    # Удаляем старые записи (старше 1 дня)
    current_time = datetime.now().timestamp()
    
    # В реальной реализации здесь была бы очистка по времени
    # Для простоты просто очищаем словарь
    user_messages.clear()
    
    bot.send_message(
        message.chat.id,
        "✅ <b>Кэш очищен</b>\nВсе временные данные удалены.",
        reply_to_message_id=message.message_id
    )

# ===== ЗАПУСК БОТА =====
if __name__ == '__main__':
    print("=" * 60)
    print("🤖 БОТ ПОДДЕРЖКИ ДЛЯ ЗАКРЫТОЙ ГРУППЫ")
    print("=" * 60)
    print(f"Токен бота: {'✅' if TOKEN else '❌'}")
    print(f"Группа поддержки: {SUPPORT_GROUP_ID}")
    print(f"Ссылка: https://t.me/+2cRF5q9dtlZkOWYy")
    print("=" * 60)
    print("📋 Функционал:")
    print("1. Пользователи пишут боту в ЛС")
    print("2. Сообщения пересылаются в закрытую группу")
    print("3. Участники группы отвечают через Reply")
    print("4. Ответы отправляются обратно пользователям")
    print("=" * 60)
    print("🚀 Запуск бота...")
    
    try:
        # Проверка подключения к группе
        try:
            chat_info = bot.get_chat(SUPPORT_GROUP_ID)
            print(f"✅ Группа найдена: {chat_info.title}")
        except Exception as e:
            print(f"⚠️ Внимание: Не удалось подключиться к группе")
            print(f"   Убедитесь, что бот добавлен в группу")
            print(f"   ID группы: {SUPPORT_GROUP_ID}")
            print(f"   Ссылка: https://t.me/+2cRF5q9dtlZkOWYy")
        
        bot.polling(none_stop=True, timeout=60)
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        print("🔄 Перезапуск через 10 секунд...")
        import time
        time.sleep(10)
        os.execv(sys.executable, ['python'] + sys.argv)