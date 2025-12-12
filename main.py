import telebot
from telebot import types
import json
import hashlib
import requests
from datetime import datetime, timedelta
import time
import threading
import re
import os
import logging
import traceback
from collections import OrderedDict
import sys

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== КОНСТАНТЫ =====
PREMIUM_PRICE = 299  # сом
PREMIUM_DURATION_DAYS = 30
PAYMENT_CHECK_INTERVAL = 30  # секунд

# ===== СТРУКТУРЫ ДАННЫХ =====
class DataStorage:
    """Управление всеми данными бота"""
    def __init__(self):
        self.users = OrderedDict()  # user_id -> user_data
        self.states = OrderedDict() # user_id -> state_data
        self.invoices = OrderedDict() # invoice_id -> invoice_data
        self.premium_users = set()  # user_id
        self.support_messages = OrderedDict() # user_id -> message
        self.contacts = OrderedDict() # user_id -> contact_info
        self.message_cache = OrderedDict() # (user_id, message_id) -> message_data
        self.user_invoices = OrderedDict() # user_id -> [invoice_ids] для быстрого поиска
        
    def cleanup_old_data(self, max_age_hours=24):
        """Очистка старых данных"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        keys_to_remove = []
        
        for user_id, state in list(self.states.items()):
            if state.get('last_activity', datetime.min) < cutoff:
                keys_to_remove.append(('states', user_id))
        
        # Ограничиваем размер кэша сообщений
        if len(self.message_cache) > 1000:
            excess = len(self.message_cache) - 800
            for _ in range(excess):
                if self.message_cache:
                    self.message_cache.popitem(last=False)

storage = DataStorage()

# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    """Основная клавиатура, которая ВСЕГДА отображается"""
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2,
        one_time_keyboard=False  # Важно: не скрывать после нажатия!
    )
    keyboard.add(
        types.KeyboardButton("📖 FAQ"),
        types.KeyboardButton("💎 Донат")
    )
    keyboard.add(types.KeyboardButton("📞 Поддержка"))
    return keyboard

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=False
    )
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    return keyboard

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
try:
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o")
    CRYPTO_BOT_API_KEY = os.getenv("CRYPTO_BOT_API_KEY", "498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy")
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "7577716374").split(",")]
    CHANNEL_ID = os.getenv("CHANNEL_ID", "@FonZoneKg")
    SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "@FONZONE_CL")
    
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
    
    # Конфигурация CryptoBot
    CRYPTO_BOT_API_URL = "https://pay.crypt.bot/api/"
    CRYPTO_BOT_HEADERS = {
        "Crypto-Pay-API-Token": CRYPTO_BOT_API_KEY,
        "Content-Type": "application/json"
    }
    
except Exception as e:
    logger.error(f"Ошибка инициализации бота: {e}")
    raise

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def safe_send_message(user_id, text, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок"""
    try:
        # Гарантируем наличие основной клавиатуры, если не указано иное
        if 'reply_markup' not in kwargs:
            kwargs['reply_markup'] = get_main_keyboard()
        
        # Ограничиваем длину текста для Telegram
        if len(text) > 4096:
            parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
            messages = []
            for part in parts:
                msg = bot.send_message(user_id, part, **kwargs)
                messages.append(msg)
            return messages
        else:
            return bot.send_message(user_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
        return None

def safe_send_video(user_id, video_path, caption, **kwargs):
    """Безопасная отправка видео"""
    try:
        with open(video_path, 'rb') as video:
            return bot.send_video(user_id, video, caption=caption, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки видео пользователю {user_id}: {e}")
        # При ошибке отправляем текстовое сообщение
        return safe_send_message(user_id, caption, **kwargs)

def reset_user_state(user_id):
    """Сброс состояния пользователя"""
    if user_id in storage.states:
        del storage.states[user_id]
        ensure_main_keyboard(user_id)
        return True
    return False

def ensure_main_keyboard(user_id):
    """Гарантированное отображение основной клавиатуры"""
    try:
        bot.send_chat_action(user_id, 'typing')
        msg = safe_send_message(user_id, " ", reply_markup=get_main_keyboard())
        
        if msg:
            if isinstance(msg, list):
                for m in msg:
                    storage.message_cache[(user_id, m.message_id)] = {
                        'type': 'keyboard_refresh',
                        'timestamp': datetime.now()
                    }
            else:
                storage.message_cache[(user_id, msg.message_id)] = {
                    'type': 'keyboard_refresh',
                    'timestamp': datetime.now()
                }
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки основной клавиатуры: {e}")
        return False

# ===== СИСТЕМА СОСТОЯНИЙ =====
class UserState:
    """Управление состоянием пользователя"""
    
    @staticmethod
    def set_state(user_id, state_name, data=None):
        """Установка состояния пользователя"""
        storage.states[user_id] = {
            'state': state_name,
            'data': data or {},
            'timestamp': datetime.now()
        }
        logger.info(f"Установлено состояние {state_name} для пользователя {user_id}")
    
    @staticmethod
    def get_state(user_id):
        """Получение состояния пользователя"""
        return storage.states.get(user_id, {}).get('state')
    
    @staticmethod
    def get_data(user_id, key=None):
        """Получение данных состояния"""
        state = storage.states.get(user_id, {})
        if key:
            return state.get('data', {}).get(key)
        return state.get('data', {})

# ===== CRYPTOBOT API =====
class CryptoBotAPI:
    """Интерфейс для работы с CryptoBot API"""
    
    @staticmethod
    def create_invoice(amount, currency="USDT", description="", payload=""):
        """Создание инвойса"""
        try:
            url = CRYPTO_BOT_API_URL + "createInvoice"
            data = {
                "asset": currency,
                "amount": str(amount),
                "description": description,
                "hidden_message": "Оплата через CryptoBot",
                "paid_btn_name": "viewItem",
                "paid_btn_url": "https://t.me/yourbot",
                "payload": payload
            }
            
            response = requests.post(url, headers=CRYPTO_BOT_HEADERS, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]
                invoice_id = invoice["invoice_id"]
                
                # Сохраняем инвойс
                storage.invoices[invoice_id] = {
                    "user_id": payload,
                    "amount": amount,
                    "currency": currency,
                    "status": "active",
                    "created_at": datetime.now(),
                    "pay_url": invoice["pay_url"],
                    "invoice_data": invoice
                }
                
                # Сохраняем ссылку в user_invoices для быстрого поиска
                if payload not in storage.user_invoices:
                    storage.user_invoices[payload] = []
                storage.user_invoices[payload].append(invoice_id)
                
                logger.info(f"Создан инвойс {invoice_id} для пользователя {payload}")
                return invoice
            else:
                logger.error(f"CryptoBot API ошибка: {result}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети CryptoBot: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка создания инвойса: {e}")
            return None
    
    @staticmethod
    def get_invoice_status(invoice_id):
        """Получение статуса инвойса"""
        try:
            url = CRYPTO_BOT_API_URL + "getInvoices"
            data = {"invoice_ids": [invoice_id]}
            
            response = requests.post(url, headers=CRYPTO_BOT_HEADERS, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("ok") and result["result"]["items"]:
                return result["result"]["items"][0].get("status", "active")
                
        except Exception as e:
            logger.error(f"Ошибка проверки статуса инвойса: {e}")
        
        return None

# ===== ПРОВЕРКА ПЛАТЕЖЕЙ В ФОНОВОМ РЕЖИМЕ =====
def payment_checker_loop():
    """Фоновая проверка статуса платежей"""
    logger.info("Запущен фоновый процесс проверки платежей")
    
    while True:
        try:
            current_time = datetime.now()
            
            # Проверяем каждый инвойс
            for invoice_id, invoice_data in list(storage.invoices.items()):
                try:
                    # Пропускаем старые инвойсы (старше 24 часов)
                    if (current_time - invoice_data.get("created_at", current_time)).total_seconds() > 86400:
                        continue
                    
                    # Проверяем только активные инвойсы
                    if invoice_data.get("status") == "active":
                        status = CryptoBotAPI.get_invoice_status(invoice_id)
                        
                        if status:
                            invoice_data["status"] = status
                            
                            # Обработка оплаченного инвойса
                            if status == "paid":
                                user_id = invoice_data.get("user_id")
                                amount = invoice_data.get("amount", 0)
                                
                                if user_id:
                                    # Для инвойсов с суммой 3 USDT и более активируем премиум
                                    if amount >= 3:
                                        storage.premium_users.add(user_id)
                                        
                                        # Обновляем данные пользователя
                                        if user_id in storage.users:
                                            storage.users[user_id]["is_premium"] = True
                                            storage.users[user_id]["premium_until"] = (
                                                datetime.now() + timedelta(days=PREMIUM_DURATION_DAYS)
                                            ).isoformat()
                                        
                                        # Уведомляем пользователя
                                        try:
                                            bot.send_message(
                                                user_id,
                                                "🎉 <b>Поздравляем!</b>\n\n"
                                                "Ваш PREMIUM статус успешно активирован!",
                                                reply_markup=get_main_keyboard()
                                            )
                                            logger.info(f"Активирован PREMIUM для пользователя {user_id}")
                                        except Exception as e:
                                            logger.error(f"Ошибка уведомления о премиуме: {e}")
                                    else:
                                        # Простая поддержка - просто благодарим
                                        try:
                                            bot.send_message(
                                                user_id,
                                                "❤️ <b>Спасибо за поддержку!</b>\n\n"
                                                "Ваш донат помогает развивать бота.",
                                                reply_markup=get_main_keyboard()
                                            )
                                            logger.info(f"Поддержка от пользователя {user_id}: {amount} {invoice_data.get('currency')}")
                                        except Exception as e:
                                            logger.error(f"Ошибка благодарности за донат: {e}")
                                    
                                    # Обновляем статус инвойса
                                    invoice_data["paid_at"] = datetime.now()
                
                except Exception as e:
                    logger.error(f"Ошибка проверки инвойса {invoice_id}: {e}")
            
            # Пауза между проверками
            time.sleep(PAYMENT_CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Критическая ошибка в проверке платежей: {e}")
            time.sleep(60)

# Запускаем фоновую проверку
payment_thread = threading.Thread(target=payment_checker_loop, daemon=True)
payment_thread.start()

# ===== ОСНОВНЫЕ КОМАНДЫ =====
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработка команды /start с видео"""
    user_id = message.from_user.id
    user_name = message.from_user.username or message.from_user.first_name
    
    # Регистрируем/обновляем пользователя
    if user_id not in storage.users:
        storage.users[user_id] = {
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "created_at": datetime.now().isoformat(),
            "is_premium": user_id in storage.premium_users,
            "premium_until": None
        }
        logger.info(f"Новый пользователь: {user_id} ({user_name})")
    
    # Сбрасываем состояние пользователя
    reset_user_state(user_id)
    
    # Текст приветствия
    welcome_text = """
🤖 <b>Добро пожаловать в бот!</b>

📌 <b>Основные возможности:</b>
• 💎 Поддержка проекта через донат
• 📞 Техническая поддержка
• 📖 FAQ и правила

Выберите действие с помощью кнопок ниже 👇
"""
    
    # Отправляем видео с приветственным текстом
    try:
        # Пытаемся отправить видео (предполагается, что файл welcome.mp4 существует в текущей директории)
        video_path = "welcome.mp4"
        if os.path.exists(video_path):
            safe_send_video(user_id, video_path, welcome_text, reply_markup=get_main_keyboard())
        else:
            # Если видео не найдено, отправляем только текст
            safe_send_message(user_id, welcome_text)
            logger.warning(f"Видеофайл {video_path} не найден")
    except Exception as e:
        logger.error(f"Ошибка отправки видео: {e}")
        # При ошибке отправляем текстовое сообщение
        safe_send_message(user_id, welcome_text)

@bot.message_handler(func=lambda m: m.text == "📖 FAQ")
def faq_command(message):
    """Показать FAQ"""
    user_id = message.from_user.id
    
    faq_text = """
📖 <b>FAQ / Часто задаваемые вопросы</b>

❓ <b>Сколько стоит PREMIUM статус?</b>
• Премиум статус: <b>299 сом/месяц</b> (примерно 3 USDT)

❓ <b>Что дает PREMIUM статус?</b>
✅ Приоритетная поддержка

❓ <b>Как оплатить?</b>
• Используйте кнопку "💎 Донат"
• Выберите сумму оплаты
• Оплатите через CryptoBot

❓ <b>Как связаться с поддержкой?</b>
• Нажмите кнопку "📞 Поддержка"
• Опишите вашу проблему
• Менеджер ответит в течение 24 часов

⚠️ <b>Правила:</b>
1. Будьте вежливы с другими пользователями
2. Соблюдайте правила Telegram
3. Запрещено нарушать законодательство

❗️ <b>Нарушители правил блокируются!</b>
"""
    
    safe_send_message(user_id, faq_text)

@bot.message_handler(func=lambda m: m.text == "💎 Донат")
def donate_command(message):
    """Обработка команды доната"""
    user_id = message.from_user.id
    
    donate_text = """
💎 <b>Поддержите развитие бота через CryptoBot!</b>

Ваша поддержка помогает:
• Развивать новые функции
• Улучшать стабильность работы
• Добавлять новые возможности

<b>Премиум-статус включает:</b>
✅ Приоритетная поддержка

💰 <b>299 сом/месяц</b> (примерно 3 USDT)
"""
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💳 Купить PREMIUM", callback_data="buy_premium"),
        types.InlineKeyboardButton("🎁 Просто поддержать", callback_data="simple_donate")
    )
    keyboard.add(
        types.InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"check_user_payment:{user_id}")
    )
    
    safe_send_message(user_id, donate_text, reply_markup=keyboard)

# ===== ОБРАБОТКА ОТМЕНЫ =====
@bot.message_handler(func=lambda m: m.text == "❌ Отмена")
def cancel_command(message):
    """Обработка кнопки отмены - сброс состояния и возврат в главное меню"""
    user_id = message.from_user.id
    
    # Сбрасываем состояние пользователя
    reset_user_state(user_id)
    
    # Отправляем сообщение с основной клавиатурой
    safe_send_message(
        user_id,
        "❌ Действие отменено. Возвращаю в главное меню.",
        reply_markup=get_main_keyboard()
    )

# ===== ПОДДЕРЖКА =====
@bot.message_handler(func=lambda m: m.text == "📞 Поддержка")
def support_command(message):
    """Обработка команды поддержки"""
    user_id = message.from_user.id
    
    support_text = """
📞 <b>Техническая поддержка</b>

Опишите вашу проблему или вопрос:
• Вопросы по оплате
• Предложения по улучшению

Наш менеджер ответит вам в течение 24 часов.

<b>Отправьте ваше сообщение ниже:</b>
"""
    
    UserState.set_state(user_id, "waiting_support")
    safe_send_message(user_id, support_text, reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda m: UserState.get_state(m.from_user.id) == "waiting_support")
def handle_support_message(message):
    """Обработка сообщения в поддержку"""
    user_id = message.from_user.id
    message_text = message.text.strip()
    
    if not message_text or message_text == "❌ Отмена":
        reset_user_state(user_id)
        safe_send_message(user_id, "❌ Сообщение в поддержку отменено.")
        return
    
    # Сохраняем сообщение
    storage.support_messages[user_id] = {
        'text': message_text,
        'username': storage.users.get(user_id, {}).get('username', 'N/A'),
        'first_name': storage.users.get(user_id, {}).get('first_name', 'N/A'),
        'timestamp': datetime.now(),
        'answered': False
    }
    
    # Формируем сообщение для администраторов
    support_msg = f"""
📩 <b>НОВОЕ СООБЩЕНИЕ В ПОДДЕРЖКУ</b>

👤 <b>Пользователь:</b>
• ID: <code>{user_id}</code>
• Username: @{storage.users.get(user_id, {}).get('username', 'Нет')}
• Имя: {storage.users.get(user_id, {}).get('first_name', 'Неизвестно')}

💬 <b>Сообщение:</b>
{message_text}

⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
    
    # Отправляем администраторам
    for admin_id in ADMIN_IDS:
        try:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("📝 Ответить", callback_data=f"reply_to:{user_id}"))
            
            bot.send_message(admin_id, support_msg, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения админу {admin_id}: {e}")
    
    # Подтверждаем пользователю
    reset_user_state(user_id)
    safe_send_message(user_id,
        "✅ <b>Ваше сообщение отправлено в поддержку!</b>\n\n"
        "Наш менеджер ответит вам в течение 24 часов.\n\n"
        "Спасибо за обращение!"
    )

# ===== ДОПОЛНИТЕЛЬНЫЙ ФУНКЦИОНАЛ ДОНАТА =====
def create_donate_invoice(user_id, amount):
    """Создание инвойса для доната"""
    invoice = CryptoBotAPI.create_invoice(
        amount=amount,
        currency="USDT",
        description=f"Поддержка развития бота: {amount} USDT",
        payload=str(user_id)
    )
    
    if invoice:
        # Отправляем пользователю ссылку для оплаты
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice["pay_url"]))
        keyboard.add(types.InlineKeyboardButton("🔄 Проверить оплату", 
                     callback_data=f"check_user_payment:{user_id}"))
        
        safe_send_message(
            user_id,
            f"❤️ <b>Спасибо за поддержку!</b>\n\n"
            f"Оплатите {invoice['amount']} {invoice['asset']} для поддержки развития бота.\n\n"
            "✅ После оплаты вы получите уведомление.\n"
            "⏰ Ссылка для оплата действительна 30 минут.",
            reply_markup=keyboard
        )
        return True
    else:
        safe_send_message(
            user_id,
            "❌ <b>Ошибка создания счета для оплаты.</b>\n\n"
            "Попробуйте позже или выберите другую сумму."
        )
        return False

@bot.callback_query_handler(func=lambda call: call.data == "simple_donate")
def simple_donate_handler(call):
    """Обработка кнопки 'Просто поддержать' с выбором суммы"""
    user_id = call.from_user.id
    
    # Сбрасываем предыдущее состояние
    reset_user_state(user_id)
    
    # Создаем inline-клавиатуру
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💰 Указать сумму", callback_data="enter_donate_amount")
    )
    keyboard.add(
        types.InlineKeyboardButton("❤️ 1 USDT", callback_data="donate_amount:1"),
        types.InlineKeyboardButton("❤️ 2 USDT", callback_data="donate_amount:2")
    )
    keyboard.add(
        types.InlineKeyboardButton("❤️ 5 USDT", callback_data="donate_amount:5"),
        types.InlineKeyboardButton("❤️ 10 USDT", callback_data="donate_amount:10")
    )
    keyboard.add(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")
    )
    
    safe_send_message(user_id,
        "❤️ <b>Поддержка развития бота</b>\n\n"
        "Выберите сумму поддержки или укажите свою:\n\n"
        "• Минимальная сумма: <b>1 USDT</b>\n"
        "• Максимальная сумма: <b>10000 USDT</b>\n\n"
        "Ваша поддержка помогает развивать новые функции и улучшать работу бота!"
    )
    
    # Редактируем сообщение с клавиатурой
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=keyboard)
    except:
        pass
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "enter_donate_amount")
def enter_donate_amount_handler(call):
    """Обработка кнопки 'Указать сумму'"""
    user_id = call.from_user.id
    UserState.set_state(user_id, "entering_donate_amount")
    
    bot.send_message(
        user_id,
        "💰 <b>Введите сумму доната в USDT:</b>\n\n"
        "Укажите число от 1 до 10000.\n"
        "Например: <code>3.5</code> или <code>15</code>\n\n"
        "💡 <i>Курс: примерно 1 USDT = 100 сом</i>",
        reply_markup=get_cancel_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('donate_amount:'))
def fixed_donate_amount_handler(call):
    """Обработка выбора фиксированной суммы доната"""
    user_id = call.from_user.id
    amount_str = call.data.split(':')[1]
    
    try:
        amount = float(amount_str)
        if 1 <= amount <= 10000:
            create_donate_invoice(user_id, amount)
        else:
            bot.answer_callback_query(call.id, 
                "❌ Сумма должна быть от 1 до 10000 USDT", 
                show_alert=True)
    except ValueError:
        bot.answer_callback_query(call.id, 
            "❌ Некорректная сумма", 
            show_alert=True)
    
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: UserState.get_state(m.from_user.id) == "entering_donate_amount")
def handle_donate_amount_input(message):
    """Обработка ввода суммы доната"""
    user_id = message.from_user.id
    amount_text = message.text.strip()
    
    # Проверяем отмену
    if amount_text == "❌ Отмена":
        reset_user_state(user_id)
        return
    
    try:
        # Пытаемся преобразовать в число с плавающей точкой
        amount = float(amount_text.replace(',', '.').strip())
        
        if amount < 1:
            safe_send_message(user_id,
                "❌ <b>Сумма слишком мала!</b>\n\n"
                "Минимальная сумма: <b>1 USDT</b>",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        if amount > 10000:
            safe_send_message(user_id,
                "❌ <b>Сумма слишком велика!</b>\n\n"
                "Максимальная сумма: <b>10000 USDT</b>",
                reply_markup=get_cancel_keyboard()
            )
            return
        
        # Создаем инвойс
        success = create_donate_invoice(user_id, amount)
        if success:
            reset_user_state(user_id)
        
    except ValueError:
        safe_send_message(user_id,
            "❌ <b>Некорректная сумма!</b>\n\n"
            "Введите число от 1 до 10000.\n"
            "Например: <code>3.5</code> или <code>15</code>",
            reply_markup=get_cancel_keyboard()
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_user_payment:'))
def check_user_payment_handler(call):
    """Проверка оплаты для конкретного пользователя"""
    user_id = call.data.split(':')[1]
    caller_id = call.from_user.id
    
    if str(caller_id) != str(user_id):
        bot.answer_callback_query(call.id, "❌ Вы не можете проверять чужие платежи", show_alert=True)
        return
    
    # Ищем последний инвойс пользователя
    user_invoices = storage.user_invoices.get(str(user_id), [])
    
    if not user_invoices:
        bot.answer_callback_query(call.id, "❌ У вас нет активных платежей", show_alert=True)
        return
    
    # Берем последний инвойс
    last_invoice_id = user_invoices[-1]
    invoice_data = storage.invoices.get(last_invoice_id)
    
    if not invoice_data:
        bot.answer_callback_query(call.id, "❌ Инвойс не найден", show_alert=True)
        return
    
    # Проверяем статус
    status = invoice_data.get("status", "active")
    amount = invoice_data.get("amount", 0)
    
    if status == "paid":
        if amount >= 3:
            bot.answer_callback_query(call.id, "✅ Платеж получен! PREMIUM активирован!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "✅ Платеж получен! Спасибо за поддержку!", show_alert=True)
    elif status == "expired":
        bot.answer_callback_query(call.id, "❌ Платеж просрочен", show_alert=True)
    else:
        # Проверяем актуальный статус
        current_status = CryptoBotAPI.get_invoice_status(last_invoice_id)
        if current_status == "paid":
            bot.answer_callback_query(call.id, "✅ Платеж получен! Спасибо за поддержку!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "⏳ Платеж еще не получен. Попробуйте позже.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "buy_premium")
def buy_premium(call):
    """Покупка PREMIUM статуса"""
    user_id = call.from_user.id
    
    # Проверяем, не активирован ли уже PREMIUM
    if user_id in storage.premium_users:
        bot.answer_callback_query(call.id, 
            "✅ У вас уже активирован PREMIUM статус!", 
            show_alert=True)
        return
    
    # Создаем инвойс
    invoice = CryptoBotAPI.create_invoice(
        amount=3,  # 3 USDT ≈ 299 сом
        currency="USDT",
        description="PREMIUM статус на 30 дней",
        payload=str(user_id)
    )
    
    if invoice:
        # Отправляем пользователю ссылку для оплаты
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice["pay_url"]))
        keyboard.add(types.InlineKeyboardButton("🔄 Проверить оплату", 
                     callback_data=f"check_user_payment:{user_id}"))
        
        bot.send_message(
            user_id,
            f"💎 <b>Оплатите {invoice['amount']} {invoice['asset']}</b>\n\n"
            "Для активации PREMIUM статуса на 30 дней.\n\n"
            "Ссылка для оплаты действительна 30 минут.\n"
            "После оплаты статус активируется автоматически.",
            reply_markup=keyboard
        )
        
        bot.answer_callback_query(call.id, "✅ Счет создан")
    else:
        bot.answer_callback_query(call.id, 
            "❌ Ошибка создания счета. Попробуйте позже.", 
            show_alert=True)

# ===== ОБРАБОТКА CALLBACK-КНОПОК =====
@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_handler(call):
    """Возврат в главное меню"""
    user_id = call.from_user.id
    reset_user_state(user_id)
    bot.answer_callback_query(call.id, "✅ Возврат в главное меню")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_to:'))
def handle_admin_reply(call):
    """Обработка ответа администратора"""
    admin_id = call.from_user.id
    
    if admin_id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ Доступ запрещен", show_alert=True)
        return
    
    # Получаем ID пользователя для ответа
    target_user_id = call.data.split(':')[1]
    
    # Устанавливаем состояние ответа с сохранением target_user
    UserState.set_state(admin_id, "admin_replying", {"target_user": target_user_id})
    
    safe_send_message(admin_id,
        f"✍️ <b>Введите ответ для пользователя {target_user_id}:</b>\n\n"
        "Сообщение будет отправлено пользователю.\n"
        "Для отмены нажмите '❌ Отмена'.",
        reply_markup=get_cancel_keyboard()
    )
    
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: UserState.get_state(m.from_user.id) == "admin_replying")
def handle_admin_reply_text(message):
    """Обработка текста ответа администратора"""
    admin_id = message.from_user.id
    
    if admin_id not in ADMIN_IDS:
        return
    
    # Получаем данные состояния
    state_data = UserState.get_data(admin_id)
    target_user_id = state_data.get("target_user")
    
    if not target_user_id:
        safe_send_message(admin_id,
            "❌ <b>Не найден пользователь для ответа.</b>\n\n"
            "Пожалуйста, начните процесс ответа заново."
        )
        reset_user_state(admin_id)
        return
    
    reply_text = message.text.strip()
    
    if not reply_text or reply_text == "❌ Отмена":
        safe_send_message(admin_id,
            "❌ <b>Ответ отменен.</b>\n\n"
            "Возвращаю в главное меню."
        )
        reset_user_state(admin_id)
        return
    
    # Отправляем сообщение пользователю
    try:
        # Формируем сообщение с ответом поддержки
        response_text = f"""
📩 <b>Ответ от поддержки:</b>

{reply_text}

━━━━━━━━━━━━
💬 <i>Это ответ на ваше обращение в поддержку.</i>
🤖 <i>Для нового вопроса нажмите кнопку "📞 Поддержка"</i>
"""
        
        # Пытаемся отправить сообщение
        msg = bot.send_message(int(target_user_id), response_text)
        
        if msg:
            # Успешно отправлено
            safe_send_message(admin_id,
                f"✅ <b>Ответ успешно отправлен пользователю</b> ID: {target_user_id}"
            )
            
            # Логируем успешную отправку
            logger.info(f"Админ {admin_id} отправил ответ пользователю {target_user_id}")
            
            # Помечаем сообщение поддержки как отвеченное
            if target_user_id in storage.support_messages:
                storage.support_messages[target_user_id]['answered'] = True
                storage.support_messages[target_user_id]['answered_by'] = admin_id
                storage.support_messages[target_user_id]['answered_at'] = datetime.now()
        else:
            # Ошибка отправки
            safe_send_message(admin_id,
                f"❌ <b>Не удалось отправить ответ пользователю</b> ID: {target_user_id}\n\n"
                "Возможно, пользователь заблокировал бота."
            )
            logger.error(f"Не удалось отправить ответ от админа {admin_id} пользователю {target_user_id}")
    
    except Exception as e:
        # Обработка исключений при отправке
        error_msg = str(e)
        logger.error(f"Ошибка отправки ответа администратора: {error_msg}")
        
        if "bot was blocked by the user" in error_msg.lower() or "chat not found" in error_msg.lower():
            safe_send_message(admin_id,
                f"❌ <b>Не удалось отправить ответ пользователю {target_user_id}</b>\n\n"
                "Пользователь заблокировал бота или удалил чат."
            )
        else:
            safe_send_message(admin_id,
                f"❌ <b>Ошибка при отправке ответа:</b> {error_msg[:100]}"
            )
    
    # Сбрасываем состояние администратора
    reset_user_state(admin_id)

# ===== АДМИН КОМАНДЫ =====
@bot.message_handler(commands=['admin'])
def admin_command(message):
    """Команда администратора"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        bot.send_message(user_id, "❌ Доступ запрещен")
        return
    
    # Считаем неотвеченные сообщения поддержки
    unanswered_support = len([m for m in storage.support_messages.values() if not m.get('answered')])
    
    admin_text = f"""
⚙️ <b>Админ панель</b>

📊 <b>Статистика:</b>
• Пользователей: {len(storage.users)}
• PREMIUM пользователей: {len(storage.premium_users)}
• Неотвеченных сообщений: {unanswered_support}

📢 <b>Рассылка:</b>
• /broadcast - Рассылка всем пользователям
• /broadcast_text текст - Быстрая текстовая рассылка
• /stats - Подробная статистика
"""
    
    safe_send_message(user_id, admin_text)

@bot.message_handler(commands=['stats'])
def stats_command(message):
    """Подробная статистика"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    # Пользователи за последнюю неделю
    week_ago = datetime.now() - timedelta(days=7)
    new_users = sum(1 for user in storage.users.values() 
                   if datetime.fromisoformat(user.get('created_at', '2000-01-01')) > week_ago)
    
    # Платежи
    total_payments = sum(inv.get('amount', 0) for inv in storage.invoices.values() if inv.get('status') == 'paid')
    
    stats_text = f"""
📊 <b>Подробная статистика</b>

👥 <b>Пользователи:</b>
• Всего: {len(storage.users)}
• Новые (за неделю): {new_users}
• PREMIUM: {len(storage.premium_users)}

💰 <b>Платежи:</b>
• Инвойсов: {len(storage.invoices)}
• Оплачено: {sum(1 for i in storage.invoices.values() if i.get('status') == 'paid')}
• Сумма: {total_payments} USDT

⚙️ <b>Система:</b>
• Состояний: {len(storage.states)}
• Кэш сообщений: {len(storage.message_cache)}
"""
    
    safe_send_message(user_id, stats_text)

# ===== ОЧИСТКА СТАРЫХ ДАННЫХ =====
def cleanup_old_data():
    """Очистка старых данных"""
    logger.info("Запущена очистка старых данных")
    
    cutoff_time = datetime.now() - timedelta(hours=24)
    cleaned_count = 0
    
    # Очищаем старые состояния
    for user_id, state in list(storage.states.items()):
        if state.get('timestamp', datetime.min) < cutoff_time:
            del storage.states[user_id]
            cleaned_count += 1
    
    # Очищаем старые сообщения поддержки (старше 30 дней)
    support_cutoff = datetime.now() - timedelta(days=30)
    for user_id, msg in list(storage.support_messages.items()):
        if msg.get('timestamp', datetime.min) < support_cutoff:
            del storage.support_messages[user_id]
            cleaned_count += 1
    
    # Очищаем старый кэш сообщений
    cache_cutoff = datetime.now() - timedelta(hours=6)
    for key, msg_data in list(storage.message_cache.items()):
        if msg_data.get('timestamp', datetime.min) < cache_cutoff:
            del storage.message_cache[key]
            cleaned_count += 1
    
    logger.info(f"Очистка завершена. Удалено объектов: {cleaned_count}")
    
    # Запускаем следующую очистку через 1 час
    threading.Timer(3600, cleanup_old_data).start()

# Запускаем очистку старых данных
cleanup_old_data()

# ===== ЗАПУСК БОТА =====
if __name__ == '__main__':
    print("=" * 60)
    print("🤖 БОТ ДЛЯ ОБЪЯВЛЕНИЙ О ТЕЛЕФОНАХ")
    print("=" * 60)
    print(f"Telegram Bot Token: {'✅ Установлен' if TOKEN != '8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"CryptoBot API Key: {'✅ Установлен' if CRYPTO_BOT_API_KEY != '498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Администраторы: {ADMIN_IDS}")
    print(f"Канал для публикаций: {CHANNEL_ID}")
    print(f"Чат поддержки: {SUPPORT_CHAT_ID}")
    print("=" * 60)
    print("📢 Основные команды:")
    print("• /start - Начать работу")
    print("• /admin - Админ-панель (только для администраторов)")
    print("=" * 60)
    print("🔧 Фоновые процессы запущены:")
    print("• Проверка платежей CryptoBot")
    print("• Очистка старых данных")
    print("=" * 60)
    print("✅ Функционал объявлений полностью удален!")
    print("✅ Сохранены: донат, поддержка, FAQ, рассылки")
    print("=" * 60)
    print("🚀 Запуск бота...")
    print("Логи записываются в bot.log")
    print("=" * 60)
    
    try:
        bot.polling(
            none_stop=True,
            interval=0,
            timeout=60,
            long_polling_timeout=30
        )
        
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
        logger.info("Бот остановлен пользователем")
        
    except Exception as e:
        logger.critical(f"Критическая ошибка бота: {e}")
        print(f"❌ Критическая ошибка: {e}")
        print("Попытка перезапуска через 30 секунд...")
        
        time.sleep(30)
        os.execv(sys.executable, [sys.executable] + sys.argv)