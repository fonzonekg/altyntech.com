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

# ===== АДМИНИСТРАТОРЫ =====
# ID администраторов (можно задать через переменные окружения)
ADMIN_CEO_ID = os.getenv("7577716374", "7577716374",)  # ID или username CEO
ADMIN_SUPPORT_ID = os.getenv("1034732253", "1034732253")  # ID или username Поддержки

# Функция для проверки администратора
def is_admin(user_id, username=None):
    """Проверяет, является ли пользователь администратором"""
    user_id_str = str(user_id)
    if username:
        # Проверка по username
        if username in [ADMIN_CEO_ID, ADMIN_SUPPORT_ID]:
            return True
    
    # Проверка по ID
    return user_id_str in [ADMIN_CEO_ID, ADMIN_SUPPORT_ID]

# ===== СТРУКТУРЫ ДАННЫХ =====
class DataStorage:
    """Управление всеми данными бота"""
    def __init__(self):
        self.users = OrderedDict()  # user_id -> user_data
        self.states = OrderedDict() # user_id -> state_data
        self.invoices = OrderedDict() # invoice_id -> invoice_data
        self.premium_users = set()  # user_id
        self.support_messages = OrderedDict() # user_id -> support_message_data
        self.contacts = OrderedDict() # user_id -> contact_info
        self.message_cache = OrderedDict() # (user_id, message_id) -> message_data
        self.user_invoices = OrderedDict() # user_id -> [invoice_ids] для быстрого поиска
        self.admin_reply_context = OrderedDict() # admin_id -> reply_context
        self.admin_messages = OrderedDict() # (admin_id, message_id) -> user_id (для отслеживания сообщений админам)
        
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

# ===== УМНАЯ СИСТЕМА ПОДДЕРЖКИ =====
class SmartSupportSystem:
    """Интеллектуальная система поддержки с предотвращением дубликатов и автоопределением категорий"""
    
    def __init__(self):
        self.tickets = OrderedDict()  # ticket_id -> ticket_data
        self.user_last_tickets = OrderedDict()  # user_id -> [ticket_ids]
        self.categories = {
            'payment': ['оплат', 'деньг', 'средств', 'платёж', 'платеж', 'донат', 'premium', 'премиум'],
            'technical': ['ошибк', 'баг', 'глюк', 'не работ', 'сбой', 'техническ', 'видео', 'файл'],
            'suggestion': ['предложен', 'идея', 'улучшен', 'функц', 'хочу', 'можно', 'добав'],
            'general': ['как', 'что', 'вопрос', 'интерес', 'помощь', 'подскаж']
        }
        self.ticket_counter = 0
        
    def _generate_ticket_id(self):
        """Генерация уникального ID тикета"""
        self.ticket_counter += 1
        return f"TKT{self.ticket_counter:06d}"
    
    def _categorize_text(self, text):
        """Автоматическое определение категории обращения"""
        text_lower = text.lower()
        for category, keywords in self.categories.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return category
        return 'other'
    
    def _find_duplicate_tickets(self, user_id, text):
        """Поиск дублирующих тикетов"""
        duplicates = []
        if user_id in self.user_last_tickets:
            for ticket_id in self.user_last_tickets[user_id][-5:]:  # Проверяем последние 5 тикетов
                ticket = self.tickets.get(ticket_id)
                if ticket and ticket['status'] in ['new', 'pending']:
                    # Простая проверка схожести по ключевым словам
                    ticket_text = ticket['messages'][0]['text'].lower()
                    new_text = text.lower()
                    
                    # Находим общие значимые слова
                    ticket_words = set(re.findall(r'\b\w{4,}\b', ticket_text))
                    new_words = set(re.findall(r'\b\w{4,}\b', new_text))
                    common_words = ticket_words.intersection(new_words)
                    
                    if len(common_words) >= 3:  # Если есть 3+ общих слова
                        duplicates.append(ticket)
        
        return duplicates
    
    def create_ticket(self, user_id, username, first_name, last_name, text):
        """Создание нового тикета с проверкой на дубликаты"""
        
        # Поиск дубликатов
        duplicates = self._find_duplicate_tickets(user_id, text)
        
        # Определение категории
        category = self._categorize_text(text)
        
        # Генерация ID тикета
        ticket_id = self._generate_ticket_id()
        
        # Создание тикета
        ticket = {
            'ticket_id': ticket_id,
            'user_id': user_id,
            'username': username or 'не указан',
            'first_name': first_name,
            'last_name': last_name,
            'category': category,
            'status': 'new',
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'messages': [
                {
                    'text': text,
                    'sender': 'user',
                    'timestamp': datetime.now()
                }
            ],
            'logs': [
                {
                    'action': 'created',
                    'timestamp': datetime.now(),
                    'details': f'Тикет создан. Категория: {category}'
                }
            ],
            'duplicate_of': duplicates[0]['ticket_id'] if duplicates else None
        }
        
        # Сохранение тикета
        self.tickets[ticket_id] = ticket
        
        # Обновление истории пользователя
        if user_id not in self.user_last_tickets:
            self.user_last_tickets[user_id] = []
        self.user_last_tickets[user_id].append(ticket_id)
        
        # Логирование
        logger.info(f"Создан тикет {ticket_id} для пользователя {user_id}. Категория: {category}")
        
        return ticket, duplicates
    
    def add_message(self, ticket_id, sender, text, action=None):
        """Добавление сообщения в тикет"""
        if ticket_id not in self.tickets:
            return False
        
        ticket = self.tickets[ticket_id]
        ticket['messages'].append({
            'text': text,
            'sender': sender,
            'timestamp': datetime.now()
        })
        
        if action:
            ticket['logs'].append({
                'action': action,
                'timestamp': datetime.now(),
                'details': text[:100]  # Первые 100 символов для логирования
            })
        
        ticket['updated_at'] = datetime.now()
        
        logger.info(f"Добавлено сообщение в тикет {ticket_id} от {sender}")
        return True
    
    def update_status(self, ticket_id, status, admin_id=None):
        """Обновление статуса тикета"""
        if ticket_id not in self.tickets:
            return False
        
        ticket = self.tickets[ticket_id]
        old_status = ticket['status']
        ticket['status'] = status
        ticket['updated_at'] = datetime.now()
        
        # Логирование изменения статуса
        action = f"status_changed_{status}"
        details = f"Статус изменен с {old_status} на {status}"
        if admin_id:
            details += f" администратором {admin_id}"
        
        ticket['logs'].append({
            'action': action,
            'timestamp': datetime.now(),
            'details': details
        })
        
        logger.info(f"Статус тикета {ticket_id} изменен: {old_status} -> {status}")
        return True
    
    def get_ticket(self, ticket_id):
        """Получение информации о тикете"""
        return self.tickets.get(ticket_id)
    
    def get_user_tickets(self, user_id, limit=10):
        """Получение тикетов пользователя"""
        if user_id not in self.user_last_tickets:
            return []
        
        user_tickets = []
        for ticket_id in reversed(self.user_last_tickets[user_id][-limit:]):
            ticket = self.tickets.get(ticket_id)
            if ticket:
                user_tickets.append(ticket)
        
        return user_tickets

# Инициализация умной системы поддержки
smart_support = SmartSupportSystem()

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

def get_admin_keyboard(ticket_id, user_id):
    """Inline-клавиатура для администратора с тикетом"""
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        types.InlineKeyboardButton("📝 Ответить", callback_data=f"admin_reply:{user_id}:{ticket_id}"),
        types.InlineKeyboardButton("✅ Решено", callback_data=f"admin_solved:{user_id}:{ticket_id}"),
        types.InlineKeyboardButton("⏳ В работе", callback_data=f"admin_pending:{user_id}:{ticket_id}")
    )
    keyboard.row(types.InlineKeyboardButton("📊 История тикетов", callback_data=f"admin_history:{user_id}"))
    return keyboard

def get_back_cancel_inline_keyboard():
    """Inline-клавиатура с кнопками Назад и Отмена"""
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    return keyboard

def get_navigation_keyboard(main_buttons):
    """Создает клавиатуру с основными кнопками и навигацией"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    # Добавляем основные кнопки
    for i in range(0, len(main_buttons), 2):
        if i + 1 < len(main_buttons):
            keyboard.row(main_buttons[i], main_buttons[i+1])
        else:
            keyboard.row(main_buttons[i])
    
    # Добавляем навигацию
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    return keyboard

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
try:
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o")
    CRYPTO_BOT_API_KEY = os.getenv("CRYPTO_BOT_API_KEY", "498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy")
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
def start_command_with_ad_button(message):
    """Обработка команды /start с видео и кнопкой создания объявления"""
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
    
    # НОВЫЙ ТЕКСТ ПРИВЕТСТВИЯ согласно ТЗ
    welcome_text = """<b>Добро пожаловать в FonZone 📱</b>
Платформа, созданная для комфортного размещения объявлений о смартфонах.

✅ Быстрое добавление  
✅ Понятный интерфейс  
✅ Удобный формат

Всё, чтобы подать объявление без лишних сложностей!"""
    
    # Создаем inline-клавиатуру с кнопкой создания объявления
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("➕ Создать объявление", callback_data="create_ad"))
    
    # Отправляем видео с приветственным текстом и inline-кнопкой или просто текст с кнопкой
    try:
        # Пытаемся отправить видео (предполагается, что файл welcome.mp4 существует в текущей директории)
        video_path = "welcome.mp4"
        if os.path.exists(video_path):
            # Отправляем видео с заголовком и inline-кнопкой
            with open(video_path, 'rb') as video:
                bot.send_video(
                    user_id, 
                    video, 
                    caption=welcome_text, 
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            logger.info(f"Отправлено видео приветствия пользователю {user_id}")
        else:
            # Если видео не найдено, отправляем только текст с inline-кнопкой
            bot.send_message(
                user_id, 
                welcome_text, 
                parse_mode="HTML",
                reply_markup=keyboard
            )
            logger.warning(f"Видеофайл {video_path} не найден, отправлен текст")
    except Exception as e:
        logger.error(f"Ошибка отправки приветствия: {e}")
        # При ошибке отправляем текстовое сообщение с inline-кнопкой
        bot.send_message(
            user_id, 
            welcome_text, 
            parse_mode="HTML",
            reply_markup=keyboard
        )
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        "Выберите действие из меню ниже:",
        reply_markup=get_main_keyboard()
    )

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
1. Будьте вежливы с другими пользователей
2. Соблюдайте правила Telegram
3. Запрещено нарушать законодательство

❗️ <b>Наши модераторы всегда на чеку.</b>
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
        types.InlineKeyboardButton("💳 PREMIUM", callback_data="buy_premium"),
        types.InlineKeyboardButton("🎁 Поддержать", callback_data="simple_donate")
    )
    # УДАЛЕНО: кнопка "🔄 Проверить оплату"
    
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

# ===== УМНАЯ ПОДДЕРЖКА =====
def notify_admins_about_new_ticket(ticket):
    """Уведомление администраторов о новом тикете"""
    ticket_id = ticket['ticket_id']
    user_id = ticket['user_id']
    
    admin_message = f"""
🆕 <b>НОВЫЙ ТИКЕТ #{ticket_id}</b>

👤 <b>Пользователь:</b> {ticket['first_name']} {ticket['last_name']}
🔗 <b>Username:</b> @{ticket['username'] if ticket['username'] != 'нет' else 'не указан'}
🏷️ <b>Категория:</b> {ticket['category']}
🕐 <b>Дата:</b> {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}

📝 <b>Сообщение:</b>
"{ticket['messages'][0]['text']}"
"""
    
    # Отправляем уведомления администраторам
    for admin_id in [ADMIN_CEO_ID, ADMIN_SUPPORT_ID]:
        if admin_id:
            try:
                keyboard = get_admin_keyboard(ticket_id, user_id)
                admin_msg = bot.send_message(
                    admin_id,
                    admin_message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                storage.admin_messages[(admin_id, admin_msg.message_id)] = (user_id, ticket_id)
                logger.info(f"Уведомление о новом тикете {ticket_id} отправлено администратору {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")

def notify_admins_about_update(ticket, new_message):
    """Уведомление администраторов о новом сообщении в существующем тикете"""
    ticket_id = ticket['ticket_id']
    user_id = ticket['user_id']
    
    update_message = f"""
📨 <b>НОВОЕ СООБЩЕНИЕ В ТИКЕТЕ #{ticket_id}</b>

👤 <b>Пользователь:</b> {ticket['first_name']} {ticket['last_name']}
🔗 <b>Username:</b> @{ticket['username'] if ticket['username'] != 'нет' else 'не указан'}
🏷️ <b>Категория:</b> {ticket['category']}
📊 <b>Статус:</b> {ticket['status']}
🕐 <b>Дата обновления:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}

📝 <b>Новое сообщение:</b>
"{new_message[:200]}{'...' if len(new_message) > 200 else ''}"

📋 <b>Исходное сообщение:</b>
"{ticket['messages'][0]['text'][:100]}..."
"""
    
    # Отправляем уведомления администраторам
    for admin_id in [ADMIN_CEO_ID, ADMIN_SUPPORT_ID]:
        if admin_id:
            try:
                keyboard = get_admin_keyboard(ticket_id, user_id)
                admin_msg = bot.send_message(
                    admin_id,
                    update_message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                storage.admin_messages[(admin_id, admin_msg.message_id)] = (user_id, ticket_id)
                logger.info(f"Уведомление об обновлении тикета {ticket_id} отправлено администратору {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления администратору {admin_id}: {e}")

def remove_admin_keyboard(admin_id, message_id):
    """Удаляет inline-клавиатуру с сообщения администратора"""
    try:
        bot.edit_message_reply_markup(
            chat_id=admin_id,
            message_id=message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Ошибка удаления клавиатуры у админа {admin_id}: {e}")

def update_admin_messages(ticket_id, status_text):
    """Обновляет сообщения у всех администраторов о тикете"""
    for (admin_id, msg_id), (user_id, tkt_id) in list(storage.admin_messages.items()):
        if tkt_id == ticket_id:
            try:
                ticket = smart_support.get_ticket(ticket_id)
                if ticket:
                    first_name = ticket.get('first_name', 'Пользователь')
                    username = ticket.get('username', 'нет')
                    timestamp = ticket.get('updated_at', datetime.now()).strftime('%d.%m.%Y %H:%M')
                    
                    updated_text = f"""
<b>Обращение в поддержку</b>

🔸 <b>Тикет:</b> #{ticket_id}
👤 <b>Пользователь:</b> {first_name}
🔗 <b>Username:</b> @{username if username != 'нет' else 'не указан'}
🕐 <b>Обновлено:</b> {timestamp}
📊 <b>Статус:</b> {status_text}

📝 <b>Последнее сообщение:</b>
"{ticket['messages'][-1]['text'][:100]}..."
"""
                    
                    # Обновляем сообщение без клавиатуры
                    bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=msg_id,
                        text=updated_text,
                        parse_mode="HTML",
                        reply_markup=None
                    )
                
                # Удаляем из отслеживания
                del storage.admin_messages[(admin_id, msg_id)]
                
            except Exception as e:
                logger.error(f"Ошибка обновления сообщения админа {admin_id}: {e}")

@bot.message_handler(func=lambda m: m.text == "📞 Поддержка")
def smart_support_command(message):
    """Обработка команды поддержки с интеллектуальными функциями"""
    user_id = message.from_user.id
    
    # Получаем историю тикетов пользователя
    user_tickets = smart_support.get_user_tickets(user_id)
    open_tickets = [t for t in user_tickets if t['status'] in ['new', 'pending']]
    
    support_text = """📞 <b>Техническая поддержка</b>

Опишите вашу проблему или вопрос:
• Вопросы по оплате
• Технические проблемы  
• Предложения по улучшению
• Общие вопросы

<b>Наш менеджер ответит вам в течение 24 часов.</b>"""
    
    # Если у пользователя есть открытые тикеты
    if open_tickets:
        support_text += "\n\n⚠️ <b>У вас есть открытые обращения:</b>"
        for ticket in open_tickets[:3]:  # Показываем до 3 открытых тикетов
            status_emoji = "🆕" if ticket['status'] == 'new' else "⏳"
            ticket_preview = ticket['messages'][0]['text'][:50] + "..." if len(ticket['messages'][0]['text']) > 50 else ticket['messages'][0]['text']
            support_text += f"\n{status_emoji} Тикет #{ticket['ticket_id']}: {ticket_preview}"
        
        support_text += "\n\n<i>Пожалуйста, дождитесь ответа по текущим обращениям.</i>"
    
    UserState.set_state(user_id, "waiting_support")
    safe_send_message(user_id, support_text, reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda m: UserState.get_state(m.from_user.id) == "waiting_support")
def handle_smart_support_message(message):
    """Обработка сообщения в поддержку с интеллектуальными функциями"""
    user_id = message.from_user.id
    message_text = message.text.strip()
    
    if not message_text or message_text == "❌ Отмена":
        reset_user_state(user_id)
        safe_send_message(user_id, "❌ Сообщение в поддержку отменено.")
        return
    
    # Получаем данные пользователя
    user_data = storage.users.get(user_id, {})
    first_name = user_data.get('first_name', message.from_user.first_name)
    last_name = user_data.get('last_name', message.from_user.last_name or '')
    username = user_data.get('username', message.from_user.username or 'нет')
    
    # Создаем тикет через умную систему
    ticket, duplicates = smart_support.create_ticket(
        user_id, username, first_name, last_name, message_text
    )
    
    # Если найдены дубликаты
    if duplicates:
        duplicate_ticket = duplicates[0]
        
        # Добавляем сообщение в существующий тикет
        smart_support.add_message(
            duplicate_ticket['ticket_id'],
            'user',
            f"📨 Дополнительное сообщение: {message_text}",
            action="duplicate_message_added"
        )
        
        # Уведомляем пользователя о дубликате
        duplicate_message = f"""
⚠️ <b>Похожее обращение уже существует</b>

Мы нашли похожий вопрос, который вы уже задавали ранее.

🔸 <b>Ваш текущий тикет:</b> #{duplicate_ticket['ticket_id']}
🔸 <b>Статус:</b> {duplicate_ticket['status']}
🔸 <b>Создан:</b> {duplicate_ticket['created_at'].strftime('%d.%m.%Y %H:%M')}

📝 <b>Текст вашего предыдущего обращения:</b>
"{duplicate_ticket['messages'][0]['text'][:100]}..."

✅ <b>Мы добавили ваше новое сообщение к существующему тикету.</b>
Пожалуйста, дождитесь ответа от поддержки.
"""
        
        reset_user_state(user_id)
        safe_send_message(user_id, duplicate_message)
        
        # Уведомляем администраторов о новом сообщении в существующем тикете
        notify_admins_about_update(duplicate_ticket, message_text)
        
        return
    
    # Если это новый тикет, отправляем подтверждение
    confirmation_message = f"""
✅ <b>Ваше обращение зарегистрировано!</b>

🔸 <b>Номер тикета:</b> #{ticket['ticket_id']}
🔸 <b>Категория:</b> {ticket['category']}
🔸 <b>Дата создания:</b> {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}

📋 <b>Ваше сообщение:</b>
"{message_text}"

<b>Статус:</b> 🆕 Ожидает рассмотрения
<b>Ожидаемое время ответа:</b> до 24 часов

💡 <i>Сохраните номер тикета для отслеживания статуса.</i>
"""
    
    reset_user_state(user_id)
    safe_send_message(user_id, confirmation_message)
    
    # Уведомляем администраторов о новом тикете
    notify_admins_about_new_ticket(ticket)

# ===== ОБРАБОТКА КНОПОК АДМИНИСТРАТОРА =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    """Обработка действий администратора с тикетами"""
    admin_id = call.from_user.id
    admin_username = call.from_user.username
    
    # Проверяем права администратора
    if not is_admin(admin_id, admin_username):
        bot.answer_callback_query(call.id, "❌ У вас нет прав для этого действия", show_alert=True)
        return
    
    # Разбираем callback data
    parts = call.data.split(':')
    action = parts[0]
    user_id = int(parts[1]) if len(parts) > 1 else None
    ticket_id = parts[2] if len(parts) > 2 else None
    
    if not user_id or not ticket_id:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    # Получаем тикет
    ticket = smart_support.get_ticket(ticket_id)
    if not ticket:
        bot.answer_callback_query(call.id, "❌ Тикет не найден или уже обработан", show_alert=True)
        return
    
    # Обрабатываем действия
    if action == "admin_reply":
        # Устанавливаем состояние ответа для администратора
        storage.admin_reply_context[admin_id] = {
            'user_id': user_id,
            'ticket_id': ticket_id,
            'original_message_id': call.message.message_id,
            'timestamp': datetime.now()
        }
        
        # Удаляем клавиатуру с исходного сообщения
        remove_admin_keyboard(admin_id, call.message.message_id)
        
        # Запрашиваем текст ответа
        bot.send_message(
            admin_id,
            f"✏️ <b>Введите текст ответа для тикета #{ticket_id}:</b>\n\n"
            f"Пользователь: {ticket['first_name']}\n"
            f"Категория: {ticket['category']}\n\n"
            "Ответ будет отправлен от имени поддержки.",
            reply_markup=get_cancel_keyboard()
        )
        
        bot.answer_callback_query(call.id, "✏️ Введите текст ответа")
    
    elif action == "admin_solved":
        # Обновляем статус тикета
        smart_support.update_status(ticket_id, 'solved', admin_id)
        smart_support.add_message(
            ticket_id,
            'system',
            f"Тикет помечен как решенный администратором {admin_id}",
            action="marked_solved"
        )
        
        # Отправляем пользователю сообщение о решении
        try:
            bot.send_message(
                user_id,
                f"✅ <b>Ваш тикет #{ticket_id} решён!</b>\n\n"
                "Спасибо за обращение. Если у вас возникнут новые вопросы, "
                "обращайтесь в поддержку.",
                reply_markup=get_main_keyboard()
            )
            logger.info(f"Тикет {ticket_id} помечен как решенный администратором {admin_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
        
        # Обновляем сообщения у администраторов
        update_admin_messages(ticket_id, "✅ Решено")
        
        bot.answer_callback_query(call.id, "✅ Тикет помечен как решенный")
    
    elif action == "admin_pending":
        # Обновляем статус тикета
        smart_support.update_status(ticket_id, 'pending', admin_id)
        smart_support.add_message(
            ticket_id,
            'system',
            f"Тикет помечен как 'в работе' администратором {admin_id}",
            action="marked_pending"
        )
        
        # Отправляем пользователю сообщение
        try:
            bot.send_message(
                user_id,
                f"⏳ <b>Ваш тикет #{ticket_id} взят в работу.</b>\n\n"
                "Наши специалисты работают над вашим вопросом. "
                "Пожалуйста, ожидайте ответа.",
                reply_markup=get_main_keyboard()
            )
            logger.info(f"Тикет {ticket_id} помечен как 'в работе' администратором {admin_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
        
        # Обновляем сообщения у администраторов
        update_admin_messages(ticket_id, "⏳ В работе")
        
        bot.answer_callback_query(call.id, "⏳ Тикет помечен как 'в работе'")
    
    elif action == "admin_history":
        # Показываем историю тикетов пользователя
        user_tickets = smart_support.get_user_tickets(user_id, limit=5)
        
        if not user_tickets:
            history_text = f"📊 <b>История тикетов пользователя</b>\n\nУ пользователя нет предыдущих обращений."
        else:
            history_text = f"📊 <b>История тикетов пользователя</b>\n\n"
            for tkt in user_tickets:
                status_emoji = {
                    'new': '🆕',
                    'pending': '⏳',
                    'solved': '✅',
                    'closed': '🔒'
                }.get(tkt['status'], '❓')
                
                history_text += f"{status_emoji} <b>#{tkt['ticket_id']}</b> - {tkt['category']}\n"
                history_text += f"   {tkt['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
                history_text += f"   {tkt['messages'][0]['text'][:50]}...\n\n"
        
        bot.send_message(admin_id, history_text, parse_mode="HTML")
        bot.answer_callback_query(call.id, "📊 История загружена")

# ===== ОБРАБОТКА ОТВЕТОВ АДМИНИСТРАТОРА =====
@bot.message_handler(func=lambda m: m.from_user.id in storage.admin_reply_context)
def handle_admin_reply(message):
    """Обработка ответа администратора пользователю"""
    admin_id = message.from_user.id
    
    # Проверяем отмену
    if message.text == "❌ Отмена":
        if admin_id in storage.admin_reply_context:
            del storage.admin_reply_context[admin_id]
        bot.send_message(admin_id, "❌ Ответ отменен.")
        return
    
    # Получаем контекст ответа
    context = storage.admin_reply_context.get(admin_id)
    if not context:
        bot.send_message(admin_id, "❌ Контекст ответа утерян.")
        return
    
    user_id = context.get('user_id')
    ticket_id = context.get('ticket_id')
    
    # Получаем тикет
    ticket = smart_support.get_ticket(ticket_id)
    if not ticket:
        bot.send_message(admin_id, "❌ Тикет не найден или уже обработан.")
        if admin_id in storage.admin_reply_context:
            del storage.admin_reply_context[admin_id]
        return
    
    # Добавляем сообщение в тикет
    smart_support.add_message(
        ticket_id,
        'admin',
        message.text,
        action="admin_reply"
    )
    
    # Обновляем статус
    smart_support.update_status(ticket_id, 'answered', admin_id)
    
    # Отправляем ответ пользователю
    try:
        response_text = f"""
💬 <b>Поддержка ответила на тикет #{ticket_id}</b>

{message.text}

---
🔸 <i>Если у вас остались вопросы, вы можете ответить на это сообщение, "
"и ваш ответ будет добавлен к тикету #{ticket_id}.</i>
"""
        
        bot.send_message(user_id, response_text, reply_markup=get_main_keyboard())
        logger.info(f"Ответ администратора {admin_id} отправлен пользователю {user_id} для тикета {ticket_id}")
        
        # Уведомляем администратора
        bot.send_message(
            admin_id,
            f"✅ <b>Ответ успешно отправлен пользователю!</b>\n\n"
            f"Тикет: #{ticket_id}\n"
            f"Пользователь: {ticket['first_name']}\n"
            f"Статус: Отвечено"
        )
        
        # Обновляем сообщения у всех администраторов
        update_admin_messages(ticket_id, "💬 Отвечено")
    
    except Exception as e:
        logger.error(f"Ошибка отправки ответа пользователю {user_id}: {e}")
        bot.send_message(admin_id, f"❌ Ошибка отправки ответа: {e}")
    
    # Очищаем контекст
    if admin_id in storage.admin_reply_context:
        del storage.admin_reply_context[admin_id]

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
    """Обработка кнопки 'Просто поддержать' с выбором суммы - ИСПРАВЛЕНО РАСПОЛОЖЕНИЕ КНОПОК"""
    user_id = call.from_user.id
    
    # Сбрасываем предыдущее состояние
    reset_user_state(user_id)
    
    # Текст согласно примеру
    text = ("❤️ <b>Поддержка развития бота</b>\n\n"
            "Выберите сумму поддержки или укажите свою:\n\n"
            "• Минимальная сумма: <b>1 USDT</b>\n"
            "• Максимальная сумма: <b>10000 USDT</b>\n\n"
            "Ваша поддержка помогает развивать новые функции и улучшать работу бота!")
    
    # Создаем клавиатуру согласно ТЗ: 2 ряда по 2 кнопки
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Первый ряд: 1 USDT и 2 USDT
    markup.add(
        types.InlineKeyboardButton("❤️ 1 USDT", callback_data="donate_amount:1"),
        types.InlineKeyboardButton("❤️ 2 USDT", callback_data="donate_amount:2")
    )
    
    # Второй ряд: 5 USDT и 10 USDT
    markup.add(
        types.InlineKeyboardButton("❤️ 5 USDT", callback_data="donate_amount:5"),
        types.InlineKeyboardButton("❤️ 10 USDT", callback_data="donate_amount:10")
    )
    
    # Кнопка "Указать сумму" (отдельный ряд)
    markup.row(types.InlineKeyboardButton("💰 Указать сумму", callback_data="enter_donate_amount"))
    
    # Кнопка "Назад" (отдельный ряд) - ИЗМЕНЕНО на back_to_donate
    markup.row(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_donate"))
    
    # Отправляем единое сообщение с текстом и клавиатурой
    try:
        # Редактируем существующее сообщение
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        # Если не удалось редактировать, отправляем новое сообщение
        logger.warning(f"Не удалось редактировать сообщение: {e}")
        bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=markup
        )
    
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
        # Отправляем пользователю ссылку для оплата
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice["pay_url"]))
        
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

@bot.callback_query_handler(func=lambda call: call.data == "back_to_donate")
def back_to_donate_handler(call):
    """Обработка кнопки 'Назад' в разделе поддержки - возврат в меню доната"""
    user_id = call.from_user.id
    
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
    
    # Создаем клавиатуру с двумя кнопками (без кнопки проверки оплаты)
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💳 PREMIUM", callback_data="buy_premium"),
        types.InlineKeyboardButton("🎁 Поддержать", callback_data="simple_donate")
    )
    
    try:
        # Редактируем текущее сообщение
        bot.edit_message_text(
            text=donate_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        # В случае ошибки отправляем новое сообщение
        bot.send_message(
            user_id,
            donate_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    
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

# ===== КОМАНДА ПРОВЕРКИ СТАТУСА ТИКЕТА =====
@bot.message_handler(commands=['mytickets'])
def my_tickets_command(message):
    """Показывает пользователю его открытые тикеты"""
    user_id = message.from_user.id
    
    user_tickets = smart_support.get_user_tickets(user_id)
    open_tickets = [t for t in user_tickets if t['status'] in ['new', 'pending', 'answered']]
    
    if not open_tickets:
        response = "📋 <b>Ваши обращения в поддержку</b>\n\nУ вас нет активных обращений."
    else:
        response = "📋 <b>Ваши активные обращения</b>\n\n"
        for ticket in open_tickets:
            status_text = {
                'new': '🆕 Ожидает рассмотрения',
                'pending': '⏳ В работе',
                'answered': '💬 Получен ответ'
            }.get(ticket['status'], '❓ Неизвестный статус')
            
            response += f"🔸 <b>Тикет #{ticket['ticket_id']}</b>\n"
            response += f"   Статус: {status_text}\n"
            response += f"   Создан: {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
            response += f"   Категория: {ticket['category']}\n\n"
    
    safe_send_message(user_id, response)

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
    
    # Очищаем старые контексты ответов администраторов
    admin_cutoff = datetime.now() - timedelta(hours=2)
    for admin_id, context in list(storage.admin_reply_context.items()):
        if context.get('timestamp', datetime.min) < admin_cutoff:
            del storage.admin_reply_context[admin_id]
            cleaned_count += 1
    
    logger.info(f"Очистка завершена. Удалено объектов: {cleaned_count}")
    
    # Запускаем следующую очистку через 1 час
    threading.Timer(3600, cleanup_old_data).start()

def cleanup_old_tickets():
    """Очистка старых тикетов"""
    logger.info("Запущена очистка старых тикетов")
    
    cutoff_time = datetime.now() - timedelta(days=30)
    cleaned_count = 0
    
    for ticket_id, ticket in list(smart_support.tickets.items()):
        if ticket.get('updated_at', datetime.min) < cutoff_time and ticket.get('status') in ['solved', 'closed']:
            del smart_support.tickets[ticket_id]
            cleaned_count += 1
    
    logger.info(f"Очистка тикетов завершена. Удалено: {cleaned_count}")
    
    # Запускаем следующую очистку через 6 часов
    threading.Timer(21600, cleanup_old_tickets).start()

# Запускаем очистку старых данных
cleanup_old_data()
cleanup_old_tickets()

# ===== НОВЫЙ ФУНКЦИОНАЛ: СОЗДАНИЕ ОБЪЯВЛЕНИЙ О СМАРТФОНАХ =====

# ===== СОСТОЯНИЯ ДЛЯ СОЗДАНИЯ ОБЪЯВЛЕНИЙ =====
def set_ad_state(user_id, step, data=None):
    """Установка состояния создания объявления"""
    if 'ad_data' not in storage.states.get(user_id, {}):
        storage.states[user_id] = storage.states.get(user_id, {})
        storage.states[user_id]['ad_data'] = {}
        storage.states[user_id]['ad_photos'] = []
    
    storage.states[user_id]['ad_step'] = step
    if data:
        storage.states[user_id]['ad_data'].update(data)
    
    logger.info(f"Пользователь {user_id}: установлен шаг объявления - {step}")

def get_ad_state(user_id):
    """Получение состояния создания объявления"""
    state = storage.states.get(user_id, {})
    return state.get('ad_step'), state.get('ad_data', {}), state.get('ad_photos', [])

def clear_ad_state(user_id):
    """Очистка состояния создания объявления"""
    if user_id in storage.states:
        if 'ad_step' in storage.states[user_id]:
            del storage.states[user_id]['ad_step']
        if 'ad_data' in storage.states[user_id]:
            del storage.states[user_id]['ad_data']
        if 'ad_photos' in storage.states[user_id]:
            del storage.states[user_id]['ad_photos']
        logger.info(f"Пользователь {user_id}: состояние создания объявления очищено")

# ===== ОБРАБОТЧИК НАЧАЛА СОЗДАНИЯ ОБЪЯВЛЕНИЯ =====
@bot.callback_query_handler(func=lambda call: call.data == "create_ad")
def create_ad_callback(call):
    """Начало создания объявления"""
    user_id = call.from_user.id
    
    # Сбрасываем предыдущее состояние
    clear_ad_state(user_id)
    
    # Устанавливаем состояние выбора бренда
    set_ad_state(user_id, "choose_brand")
    
    # Отправляем сообщение с выбором бренда
    text = "📱 Выберите бренд смартфона:"
    
    # Создаем inline-клавиатуру с брендами (4 колонки)
    brands = [
        "Apple", "Samsung", "Xiaomi", "Redmi",
        "POCO", "Realme", "Oppo", "Vivo",
        "Huawei", "Honor", "Google Pixel", "OnePlus",
        "Nokia", "Sony", "Asus", "Infinix",
        "Tecno", "ZTE", "Meizu", "Другое"
    ]
    
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    buttons = []
    for brand in brands:
        buttons.append(types.InlineKeyboardButton(brand, callback_data=f"brand:{brand}"))
    
    # Распределяем кнопки по рядам
    for i in range(0, len(buttons), 4):
        keyboard.row(*buttons[i:i+4])
    
    # Добавляем кнопку отмены (без кнопки Назад, так как это первый шаг)
    keyboard.row(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad"))
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ ОТДЕЛЬНЫМ СООБЩЕНИЕМ
        safe_send_message(
            user_id,
            "Начинаем создание объявления! Выберите бренд:",
            reply_markup=get_main_keyboard()
        )
    except:
        # Если не удалось редактировать, отправляем новое сообщение с inline-клавиатурой
        bot.send_message(user_id, text, reply_markup=keyboard)
        # И отправляем основную клавиатуру
        safe_send_message(
            user_id,
            "Начинаем создание объявления!",
            reply_markup=get_main_keyboard()
        )
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТЧИК ВЫБОРА БРЕНДА =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('brand:'))
def brand_callback(call):
    """Обработка выбора бренда"""
    user_id = call.from_user.id
    brand = call.data.split(':')[1]
    
    # Сохраняем бренд и определяем тип устройства
    device_type = "iphone" if brand == "Apple" else "android"
    set_ad_state(user_id, "model", {"brand": brand, "device_type": device_type})
    
    # Задаем следующий вопрос в зависимости от типа устройства
    if device_type == "iphone":
        text = "📱 Введите модель iPhone:\n\nПример: <i>iPhone 11 / 12 Pro / 13 Pro Max / 14 / 15 Pro</i>"
        set_ad_state(user_id, "iphone_model")
    else:
        text = "📱 Введите модель смартфона:"
        set_ad_state(user_id, "android_model")
    
    keyboard = get_back_cancel_inline_keyboard()
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except:
        bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        f"Выбран бренд: {brand}. Теперь введите модель:",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТЧИК ОТМЕНЫ СОЗДАНИЯ ОБЪЯВЛЕНИЯ =====
@bot.callback_query_handler(func=lambda call: call.data == "cancel_ad")
def cancel_ad_callback(call):
    """Отмена создания объявления"""
    user_id = call.from_user.id
    clear_ad_state(user_id)
    
    bot.edit_message_text(
        text="❌ Создание объявления отменено.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ ПОСЛЕ ОТМЕНЫ
    safe_send_message(
        user_id,
        "❌ Создание объявления отменено. Возвращаю в главное меню.",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТЧИК КНОПКИ НАЗАД =====
@bot.callback_query_handler(func=lambda call: call.data == "back")
def back_callback(call):
    """Обработка кнопки Назад - возврат на предыдущий шаг"""
    user_id = call.from_user.id
    step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not step:
        bot.answer_callback_query(call.id, "Нет активного процесса создания объявления")
        return
    
    # Определяем предыдущий шаг
    previous_step = None
    device_type = ad_data.get('device_type')
    
    # Логика определения предыдущего шага
    if step == "iphone_model" or step == "android_model":
        previous_step = "choose_brand"
        # При возврате к выбору бренда удаляем тип устройства
        if 'device_type' in ad_data:
            del ad_data['device_type']
        if 'brand' in ad_data:
            del ad_data['brand']
    
    elif step == "iphone_memory":
        previous_step = "iphone_model"
        if 'model' in ad_data:
            del ad_data['model']
    
    elif step == "iphone_condition":
        previous_step = "iphone_memory"
        if 'memory' in ad_data:
            del ad_data['memory']
    
    elif step == "iphone_battery":
        previous_step = "iphone_condition"
        if 'condition' in ad_data:
            del ad_data['condition']
    
    elif step == "iphone_color":
        previous_step = "iphone_battery"
        if 'battery' in ad_data:
            del ad_data['battery']
    
    elif step == "iphone_package":
        previous_step = "iphone_color"
        if 'color' in ad_data:
            del ad_data['color']
    
    elif step == "android_ram":
        previous_step = "android_model"
        if 'model' in ad_data:
            del ad_data['model']
    
    elif step == "android_rom":
        previous_step = "android_ram"
        if 'ram' in ad_data:
            del ad_data['ram']
    
    elif step == "android_processor":
        previous_step = "android_rom"
        if 'rom' in ad_data:
            del ad_data['rom']
    
    elif step == "android_condition":
        previous_step = "android_processor"
        if 'processor' in ad_data:
            del ad_data['processor']
    
    elif step == "android_battery":
        previous_step = "android_condition"
        if 'condition' in ad_data:
            del ad_data['condition']
    
    elif step == "android_color":
        previous_step = "android_battery"
        if 'battery' in ad_data:
            del ad_data['battery']
    
    elif step == "price_usd":
        if device_type == "iphone":
            previous_step = "iphone_package"
            if 'package' in ad_data:
                del ad_data['package']
        else:
            previous_step = "android_color"
            if 'color' in ad_data:
                del ad_data['color']
    
    elif step == "price_kgs":
        previous_step = "price_usd"
        if 'price_usd' in ad_data:
            del ad_data['price_usd']
    
    elif step == "contact":
        previous_step = "price_kgs"
        if 'price_kgs' in ad_data:
            del ad_data['price_kgs']
    
    elif step == "photos":
        previous_step = "contact"
        if 'contact_type' in ad_data:
            del ad_data['contact_type']
        if 'contact' in ad_data:
            del ad_data['contact']
    
    elif step == "preview":
        previous_step = "photos"
        # При возврате к фото не очищаем данные фото
    
    else:
        bot.answer_callback_query(call.id, "Невозможно вернуться назад")
        return
    
    # Устанавливаем предыдущий шаг
    set_ad_state(user_id, previous_step, ad_data)
    
    # Показываем соответствующий интерфейс для предыдущего шага
    show_step_interface(user_id, previous_step, call.message.chat.id, call.message.message_id)
    
    # ЕСЛИ ВОЗВРАЩАЕМСЯ К ВЫБОРУ БРЕНДА - ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    if previous_step == "choose_brand":
        safe_send_message(
            user_id,
            "Возвращаемся к выбору бренда:",
            reply_markup=get_main_keyboard()
        )
    
    bot.answer_callback_query(call.id)

def show_step_interface(user_id, step, chat_id=None, message_id=None):
    """Показывает интерфейс для указанного шага"""
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    device_type = ad_data.get('device_type')
    
    try:
        if step == "choose_brand":
            text = "📱 Выберите бренд смартфона:"
            brands = [
                "Apple", "Samsung", "Xiaomi", "Redmi",
                "POCO", "Realme", "Oppo", "Vivo",
                "Huawei", "Honor", "Google Pixel", "OnePlus",
                "Nokia", "Sony", "Asus", "Infinix",
                "Tecno", "ZTE", "Meizu", "Другое"
            ]
            
            keyboard = types.InlineKeyboardMarkup(row_width=4)
            buttons = []
            for brand in brands:
                buttons.append(types.InlineKeyboardButton(brand, callback_data=f"brand:{brand}"))
            
            for i in range(0, len(buttons), 4):
                keyboard.row(*buttons[i:i+4])
            
            keyboard.row(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad"))
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "iphone_model":
            text = "📱 Введите модель iPhone:\n\nПример: <i>iPhone 11 / 12 Pro / 13 Pro Max / 14 / 15 Pro</i>"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            else:
                bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
        
        elif step == "iphone_memory":
            text = "💾 Выберите объем памяти:"
            memories = ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"]
            buttons = [types.InlineKeyboardButton(mem, callback_data=f"iphone_memory:{mem}") for mem in memories]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "iphone_condition":
            text = "📊 Выберите состояние телефона:"
            conditions = ["Новый", "Отличное", "Хорошее", "Удовлетворительное"]
            buttons = [types.InlineKeyboardButton(cond, callback_data=f"iphone_condition:{cond}") for cond in conditions]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "iphone_battery":
            current_battery = ad_data.get('battery', '')
            hint = f"\n\nТекущее значение: {current_battery}%" if current_battery else ""
            text = f"🔋 Введите состояние аккумулятора (%):\n\nЧисло от 70 до 100{hint}"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "iphone_color":
            current_color = ad_data.get('color', '')
            hint = f"\n\nТекущее значение: {current_color}" if current_color else ""
            text = f"🎨 Введите цвет телефона:{hint}"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "iphone_package":
            text = "📦 Выберите комплектацию:"
            packages = ["Полный комплект", "Только телефон", "Без коробки"]
            buttons = [types.InlineKeyboardButton(pkg, callback_data=f"iphone_package:{pkg}") for pkg in packages]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "android_model":
            text = "📱 Введите модель смартфона:"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "android_ram":
            text = "🧠 Выберите оперативную память (RAM):"
            ram_options = ["2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "12 GB", "16 GB"]
            buttons = [types.InlineKeyboardButton(ram, callback_data=f"android_ram:{ram}") for ram in ram_options]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "android_rom":
            text = "💾 Выберите встроенную память (ROM):"
            rom_options = ["32 GB", "64 GB", "128 GB", "256 GB", "512 GB"]
            buttons = [types.InlineKeyboardButton(rom, callback_data=f"android_rom:{rom}") for rom in rom_options]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "android_processor":
            current_processor = ad_data.get('processor', '')
            hint = f"\n\nТекущее значение: {current_processor}" if current_processor else ""
            text = f"⚡️ Введите модель процессора:\n\nНапример: <i>Snapdragon 888, Exynos 2100, Dimensity 1200</i>{hint}"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            else:
                bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
        
        elif step == "android_condition":
            text = "📊 Выберите состояние телефона:"
            conditions = ["Новый", "Отличное", "Хорошее", "Удовлетворительное"]
            buttons = [types.InlineKeyboardButton(cond, callback_data=f"android_condition:{cond}") for cond in conditions]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "android_battery":
            text = "🔋 Выберите состояние аккумулятора:"
            battery_options = ["Отличный", "Нормальный", "Требует замены"]
            buttons = [types.InlineKeyboardButton(batt, callback_data=f"android_battery:{batt}") for batt in battery_options]
            keyboard = get_navigation_keyboard(buttons)
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "android_color":
            current_color = ad_data.get('color', '')
            hint = f"\n\nТекущее значение: {current_color}" if current_color else ""
            text = f"🎨 Введите цвет телефона:{hint}"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "price_usd":
            current_price = ad_data.get('price_usd', '')
            hint = f"\n\nТекущее значение: {current_price} USD" if current_price else ""
            text = f"💰 Введите цену в долларах (USD):\n\nТолько число, например: <code>500</code>{hint}"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard, parse_mode="HTML")
            else:
                bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
        
        elif step == "price_kgs":
            current_price = ad_data.get('price_kgs', '')
            price_usd = ad_data.get('price_usd', 0)
            hint = f"\n\nТекущее значение: {current_price} KGS" if current_price else ""
            text = f"💰 Введите цену в сомах (KGS):\n\nТекущий курс: ~{price_usd * 100:.0f} сом{hint}"
            keyboard = get_back_cancel_inline_keyboard()
            
            if chat_id and message_id:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "contact":
            text = "📞 Выберите способ связи с покупателями:"
            keyboard = types.ReplyKeyboardMarkup(
                resize_keyboard=True,
                one_time_keyboard=True
            )
            keyboard.add(
                types.KeyboardButton("📞 Поделиться номером", request_contact=True),
                types.KeyboardButton("💬 Связь через Telegram")
            )
            keyboard.add(types.KeyboardButton("🔙 Назад"))
            keyboard.add(types.KeyboardButton("❌ Отмена"))
            
            if chat_id and message_id:
                # Для шага contact используем отдельное сообщение
                bot.send_message(user_id, text, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "photos":
            photo_count = len(ad_photos)
            text = f"📷 Теперь отправьте фото телефона (2-4 фото):\n" \
                   f"Минимум: 2 фото\n" \
                   f"Максимум: 4 фото\n\n" \
                   f"Загружено: {photo_count} фото\n" \
                   f"Осталось: {max(0, 2 - photo_count)} фото (минимум)"
            
            if photo_count >= 2:
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
                keyboard.add(types.KeyboardButton("✅ Готово"))
                keyboard.add(types.KeyboardButton("🔙 Назад"))
                keyboard.add(types.KeyboardButton("❌ Отмена"))
            else:
                keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
                keyboard.add(types.KeyboardButton("🔙 Назад"))
                keyboard.add(types.KeyboardButton("❌ Отмена"))
            
            if chat_id and message_id:
                bot.send_message(user_id, text, reply_markup=keyboard)
            else:
                bot.send_message(user_id, text, reply_markup=keyboard)
        
        elif step == "preview":
            show_ad_preview(user_id)
    
    except Exception as e:
        logger.error(f"Ошибка показа интерфейса шага {step}: {e}")
        bot.send_message(user_id, f"❌ Ошибка: {e}")

# ===== ОБРАБОТЧИКИ ДЛЯ IPHONE =====
@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "iphone_model")
def handle_iphone_model(message):
    """Обработка модели iPhone"""
    user_id = message.from_user.id
    model = message.text.strip()
    
    if not model:
        bot.send_message(user_id, "❌ Пожалуйста, введите модель iPhone.", reply_markup=get_back_cancel_inline_keyboard())
        return
    
    set_ad_state(user_id, "iphone_memory", {"model": model})
    
    # Показываем выбор памяти
    text = "💾 Выберите объем памяти:"
    memories = ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"]
    buttons = [types.InlineKeyboardButton(mem, callback_data=f"iphone_memory:{mem}") for mem in memories]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.send_message(user_id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('iphone_memory:'))
def handle_iphone_memory(call):
    """Обработка выбора памяти iPhone"""
    user_id = call.from_user.id
    memory = call.data.split(':')[1]
    
    set_ad_state(user_id, "iphone_condition", {"memory": memory})
    
    # Показываем выбор состояния
    text = "📊 Выберите состояние телефона:"
    conditions = ["Новый", "Отличное", "Хорошее", "Удовлетворительное"]
    buttons = [types.InlineKeyboardButton(cond, callback_data=f"iphone_condition:{cond}") for cond in conditions]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('iphone_condition:'))
def handle_iphone_condition(call):
    """Обработка выбора состояния iPhone"""
    user_id = call.from_user.id
    condition = call.data.split(':')[1]
    
    set_ad_state(user_id, "iphone_battery", {"condition": condition})
    
    bot.edit_message_text(
        text="🔋 Введите состояние аккумулятора (%):\n\nЧисло от 70 до 100",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=get_back_cancel_inline_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "iphone_battery")
def handle_iphone_battery(message):
    """Обработка состояния аккумулятора iPhone"""
    user_id = message.from_user.id
    
    try:
        battery = int(message.text.strip())
        if 70 <= battery <= 100:
            set_ad_state(user_id, "iphone_color", {"battery": battery})
            bot.send_message(
                user_id,
                "🎨 Введите цвет телефона:",
                reply_markup=get_back_cancel_inline_keyboard()
            )
        else:
            bot.send_message(user_id, "❌ Введите число от 70 до 100:", reply_markup=get_back_cancel_inline_keyboard())
    except ValueError:
        bot.send_message(user_id, "❌ Пожалуйста, введите число от 70 до 100:", reply_markup=get_back_cancel_inline_keyboard())

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "iphone_color")
def handle_iphone_color(message):
    """Обработка цвета iPhone"""
    user_id = message.from_user.id
    color = message.text.strip()
    
    if not color:
        bot.send_message(user_id, "❌ Пожалуйста, введите цвет.", reply_markup=get_back_cancel_inline_keyboard())
        return
    
    set_ad_state(user_id, "iphone_package", {"color": color})
    
    # Показываем выбор комплектации
    text = "📦 Выберите комплектацию:"
    packages = ["Полный комплект", "Только телефон", "Без коробки"]
    buttons = [types.InlineKeyboardButton(pkg, callback_data=f"iphone_package:{pkg}") for pkg in packages]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.send_message(user_id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('iphone_package:'))
def handle_iphone_package(call):
    """Обработка выбора комплектации iPhone"""
    user_id = call.from_user.id
    package = call.data.split(':')[1]
    
    set_ad_state(user_id, "price_usd", {"package": package})
    
    bot.edit_message_text(
        text="💰 Введите цену в долларах (USD):\n\nТолько число, например: <code>500</code>",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=get_back_cancel_inline_keyboard()
    )
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТЧИКИ ДЛЯ ANDROID =====
@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "android_model")
def handle_android_model(message):
    """Обработка модели Android"""
    user_id = message.from_user.id
    model = message.text.strip()
    
    if not model:
        bot.send_message(user_id, "❌ Пожалуйста, введите модель.", reply_markup=get_back_cancel_inline_keyboard())
        return
    
    set_ad_state(user_id, "android_ram", {"model": model})
    
    # Показываем выбор оперативной памяти
    text = "🧠 Выберите оперативную память (RAM):"
    ram_options = ["2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "12 GB", "16 GB"]
    buttons = [types.InlineKeyboardButton(ram, callback_data=f"android_ram:{ram}") for ram in ram_options]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.send_message(user_id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('android_ram:'))
def handle_android_ram(call):
    """Обработка выбора оперативной памяти Android"""
    user_id = call.from_user.id
    ram = call.data.split(':')[1]
    
    set_ad_state(user_id, "android_rom", {"ram": ram})
    
    # Показываем выбор встроенной памяти
    text = "💾 Выберите встроенную память (ROM):"
    rom_options = ["32 GB", "64 GB", "128 GB", "256 GB", "512 GB"]
    buttons = [types.InlineKeyboardButton(rom, callback_data=f"android_rom:{rom}") for rom in rom_options]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('android_rom:'))
def handle_android_rom(call):
    """Обработка выбора встроенной памяти Android"""
    user_id = call.from_user.id
    rom = call.data.split(':')[1]
    
    set_ad_state(user_id, "android_processor", {"rom": rom})
    
    bot.edit_message_text(
        text="⚡️ Введите модель процессора:\n\nНапример: <i>Snapdragon 888, Exynos 2100, Dimensity 1200</i>",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=get_back_cancel_inline_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "android_processor")
def handle_android_processor(message):
    """Обработка процессора Android"""
    user_id = message.from_user.id
    processor = message.text.strip()
    
    if not processor:
        bot.send_message(user_id, "❌ Пожалуйста, введите модель процессора.", reply_markup=get_back_cancel_inline_keyboard())
        return
    
    set_ad_state(user_id, "android_condition", {"processor": processor})
    
    # Показываем выбор состояния
    text = "📊 Выберите состояние телефона:"
    conditions = ["Новый", "Отличное", "Хорошее", "Удовлетворительное"]
    buttons = [types.InlineKeyboardButton(cond, callback_data=f"android_condition:{cond}") for cond in conditions]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.send_message(user_id, text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('android_condition:'))
def handle_android_condition(call):
    """Обработка выбора состояния Android"""
    user_id = call.from_user.id
    condition = call.data.split(':')[1]
    
    set_ad_state(user_id, "android_battery", {"condition": condition})
    
    # Показываем выбор состояния аккумулятора
    text = "🔋 Выберите состояние аккумулятора:"
    battery_options = ["Отличный", "Нормальный", "Требует замены"]
    buttons = [types.InlineKeyboardButton(batt, callback_data=f"android_battery:{batt}") for batt in battery_options]
    keyboard = get_navigation_keyboard(buttons)
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('android_battery:'))
def handle_android_battery(call):
    """Обработка выбора состояния аккумулятора Android"""
    user_id = call.from_user.id
    battery = call.data.split(':')[1]
    
    set_ad_state(user_id, "android_color", {"battery": battery})
    
    bot.edit_message_text(
        text="🎨 Введите цвет телефона:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=get_back_cancel_inline_keyboard()
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "android_color")
def handle_android_color(message):
    """Обработка цвета Android"""
    user_id = message.from_user.id
    color = message.text.strip()
    
    if not color:
        bot.send_message(user_id, "❌ Пожалуйста, введите цвет.", reply_markup=get_back_cancel_inline_keyboard())
        return
    
    set_ad_state(user_id, "price_usd", {"color": color})
    
    bot.send_message(
        user_id,
        "💰 Введите цену в долларах (USD):\n\nТолько число, например: <code>300</code>",
        parse_mode="HTML",
        reply_markup=get_back_cancel_inline_keyboard()
    )

# ===== ОБРАБОТЧИК ЦЕНЫ (ОБЩИЙ ДЛЯ IPHONE И ANDROID) =====
@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "price_usd")
def handle_price_usd(message):
    """Обработка цены в USD"""
    user_id = message.from_user.id
    
    try:
        price_usd = float(message.text.strip().replace(',', '.'))
        if price_usd <= 0:
            bot.send_message(user_id, "❌ Цена должна быть больше 0. Введите снова:", reply_markup=get_back_cancel_inline_keyboard())
            return
        
        set_ad_state(user_id, "price_kgs", {"price_usd": price_usd})
        
        bot.send_message(
            user_id,
            f"💰 Введите цену в сомах (KGS):\n\nТекущий курс: ~{price_usd * 100:.0f} сом",
            reply_markup=get_back_cancel_inline_keyboard()
        )
    except ValueError:
        bot.send_message(user_id, "❌ Пожалуйста, введите число. Например: <code>500</code>", parse_mode="HTML", reply_markup=get_back_cancel_inline_keyboard())

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "price_kgs")
def handle_price_kgs(message):
    """Обработка цены в KGS"""
    user_id = message.from_user.id
    
    try:
        price_kgs = float(message.text.strip().replace(',', '.'))
        if price_kgs <= 0:
            bot.send_message(user_id, "❌ Цена должна быть больше 0. Введите снова:", reply_markup=get_back_cancel_inline_keyboard())
            return
        
        # Сохраняем цену и переходим к контактам
        ad_step, ad_data, _ = get_ad_state(user_id)
        ad_data['price_kgs'] = price_kgs
        set_ad_state(user_id, "contact", ad_data)
        
        # Показываем выбор способа связи
        keyboard = types.ReplyKeyboardMarkup(
            resize_keyboard=True,
            one_time_keyboard=True
        )
        keyboard.add(
            types.KeyboardButton("📞 Поделиться номером", request_contact=True),
            types.KeyboardButton("💬 Связь через Telegram")
        )
        keyboard.add(types.KeyboardButton("🔙 Назад"))
        keyboard.add(types.KeyboardButton("❌ Отмена"))
        
        bot.send_message(
            user_id,
            "📞 Выберите способ связи с покупателями:",
            reply_markup=keyboard
        )
    except ValueError:
        bot.send_message(user_id, "❌ Пожалуйста, введите число. Например: <code>50000</code>", parse_mode="HTML", reply_markup=get_back_cancel_inline_keyboard())

# ===== ОБРАБОТЧИК КОНТАКТОВ =====
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    """Обработка контакта"""
    user_id = message.from_user.id
    ad_step, _, _ = get_ad_state(user_id)
    
    if ad_step == "contact":
        phone = message.contact.phone_number
        set_ad_state(user_id, "photos", {"contact_type": "phone", "contact": phone})
        
        bot.send_message(
            user_id,
            f"✅ Номер сохранен: {phone}\n\n"
            "📷 Теперь отправьте фото телефона (2-4 фото):\n"
            "Минимум: 2 фото\n"
            "Максимум: 4 фото\n\n"
            "После загрузки фото нажмите кнопку ✅ Готово",
            reply_markup=get_back_cancel_inline_keyboard()
        )

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "contact" and m.text == "💬 Связь через Telegram")
def handle_telegram_contact(message):
    """Обработка выбора связи через Telegram"""
    user_id = message.from_user.id
    username = message.from_user.username
    
    if username:
        contact_info = f"@{username}"
    else:
        contact_info = f"https://t.me/{message.from_user.first_name}"
    
    set_ad_state(user_id, "photos", {"contact_type": "telegram", "contact": contact_info})
    
    bot.send_message(
        user_id,
        f"✅ Контакт сохранен: {contact_info}\n\n"
        "📷 Теперь отправьте фото телефона (2-4 фото):\n"
        "Минимум: 2 фото\n"
        "Максимум: 4 фото\n\n"
        "После загрузки фото нажмите кнопку ✅ Готово",
        reply_markup=get_back_cancel_inline_keyboard()
    )

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "contact" and m.text == "🔙 Назад")
def handle_contact_back(message):
    """Обработка кнопки Назад на шаге контактов"""
    user_id = message.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if 'price_kgs' in ad_data:
        del ad_data['price_kgs']
    
    set_ad_state(user_id, "price_usd", ad_data)
    show_step_interface(user_id, "price_usd")

# ===== ОБРАБОТЧИК ФОТО =====
@bot.message_handler(content_types=['photo'], func=lambda m: get_ad_state(m.from_user.id)[0] == "photos")
def handle_ad_photos(message):
    """Обработка загрузки фото"""
    user_id = message.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if len(ad_photos) >= 4:
        bot.send_message(user_id, "❌ Максимальное количество фото - 4. Нажмите ✅ Готово.")
        return
    
    # Сохраняем photo_id самого большого размера
    photo_id = message.photo[-1].file_id
    ad_photos.append(photo_id)
    
    # Обновляем состояние
    state = storage.states.get(user_id, {})
    state['ad_photos'] = ad_photos
    storage.states[user_id] = state
    
    remaining = 4 - len(ad_photos)
    
    if len(ad_photos) >= 2:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("✅ Готово"))
        keyboard.add(types.KeyboardButton("🔙 Назад"))
        keyboard.add(types.KeyboardButton("❌ Отмена"))
        
        bot.send_message(
            user_id,
            f"✅ Фото #{len(ad_photos)} загружено.\n"
            f"Загружено: {len(ad_photos)} фото\n"
            f"Можно добавить еще: {remaining} фото\n\n"
            "Нажмите ✅ Готово, когда загрузите все фото.",
            reply_markup=keyboard
        )
    else:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("🔙 Назад"))
        keyboard.add(types.KeyboardButton("❌ Отмена"))
        
        bot.send_message(
            user_id,
            f"✅ Фото #{len(ad_photos)} загружено.\n"
            f"Нужно еще минимум: {2 - len(ad_photos)} фото",
            reply_markup=keyboard
        )

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "photos" and m.text == "✅ Готово")
def handle_photos_done(message):
    """Обработка завершения загрузки фото"""
    user_id = message.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if len(ad_photos) < 2:
        bot.send_message(
            user_id,
            f"❌ Минимальное количество фото - 2.\n"
            f"Загружено: {len(ad_photos)} фото\n"
            f"Нужно еще: {2 - len(ad_photos)} фото"
        )
        return
    
    # Переходим к предпросмотру
    set_ad_state(user_id, "preview", ad_data)
    show_ad_preview(user_id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "photos" and m.text == "🔙 Назад")
def handle_photos_back(message):
    """Обработка кнопки Назад на шаге фото"""
    user_id = message.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if 'contact_type' in ad_data:
        del ad_data['contact_type']
    if 'contact' in ad_data:
        del ad_data['contact']
    
    set_ad_state(user_id, "contact", ad_data)
    show_step_interface(user_id, "contact")

def show_ad_preview(user_id):
    """Показ предпросмотра объявления"""
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Формируем текст объявления
    preview_text = format_ad_text(ad_data, preview=True)
    
    # Создаем клавиатуру подтверждения
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish_ad"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_ad")
    )
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    # Отправляем фото альбомом
    if ad_photos:
        try:
            media = []
            for i, photo_id in enumerate(ad_photos):
                if i == 0:
                    media.append(types.InputMediaPhoto(photo_id, caption=preview_text, parse_mode="HTML"))
                else:
                    media.append(types.InputMediaPhoto(photo_id))
            
            bot.send_media_group(user_id, media)
            bot.send_message(user_id, "📋 Предварительный просмотр объявления:", reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Ошибка отправки медиагруппы: {e}")
            bot.send_message(user_id, preview_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        bot.send_message(user_id, preview_text, parse_mode="HTML", reply_markup=keyboard)

def format_ad_text(ad_data, preview=False):
    """Форматирование текста объявления"""
    device_type = ad_data.get('device_type', 'android')
    
    if device_type == 'iphone':
        text = f"""
📱 <b>Apple iPhone {ad_data.get('model', '')}</b>

📊 <b>Характеристики:</b>
• Память: {ad_data.get('memory', '')}
• Состояние: {ad_data.get('condition', '')}
• Аккумулятор: {ad_data.get('battery', '')}%
• Цвет: {ad_data.get('color', '')}
• Комплектация: {ad_data.get('package', '')}

💰 <b>Цена:</b>
• {ad_data.get('price_usd', 0):.0f} USD
• {ad_data.get('price_kgs', 0):.0f} KGS

👤 <b>Контакты:</b>
• {ad_data.get('contact', 'Не указан')}

"""
    else:
        text = f"""
📱 <b>{ad_data.get('brand', '')} {ad_data.get('model', '')}</b>

📊 <b>Характеристики:</b>
• ОЗУ: {ad_data.get('ram', '')}
• ПЗУ: {ad_data.get('rom', '')}
• Процессор: {ad_data.get('processor', '')}
• Состояние: {ad_data.get('condition', '')}
• Аккумулятор: {ad_data.get('battery', '')}
• Цвет: {ad_data.get('color', '')}

💰 <b>Цена:</b>
• {ad_data.get('price_usd', 0):.0f} USD
• {ad_data.get('price_kgs', 0):.0f} KGS

👤 <b>Контакты:</b>
• {ad_data.get('contact', 'Не указан')}

"""
    
    if preview:
        text += f"\n🕐 <i>Дата публикации: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>"
    
    return text

# ===== ОБРАБОТЧИКИ ПУБЛИКАЦИИ =====
@bot.callback_query_handler(func=lambda call: call.data == "publish_ad")
def publish_ad_callback(call):
    """Публикация объявления"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Формируем финальный текст
    final_text = format_ad_text(ad_data, preview=False)
    
    # Добавляем кнопку "Связаться"
    contact_button = None
    if ad_data.get('contact_type') == 'phone' and ad_data.get('contact'):
        phone = ad_data['contact'].replace('+', '')
        contact_button = types.InlineKeyboardButton(
            "📞 Связаться", 
            url=f"tel:+{phone}"
        )
    elif ad_data.get('contact_type') == 'telegram' and ad_data.get('contact'):
        if ad_data['contact'].startswith('@'):
            contact_button = types.InlineKeyboardButton(
                "📞 Связаться",
                url=f"https://t.me/{ad_data['contact'][1:]}"
            )
        else:
            contact_button = types.InlineKeyboardButton(
                "📞 Связаться",
                url=ad_data['contact']
            )
    
    # Публикуем в канал
    try:
        if ad_photos:
            media = []
            for i, photo_id in enumerate(ad_photos):
                if i == 0:
                    if contact_button:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(contact_button)
                        media.append(types.InputMediaPhoto(photo_id, caption=final_text, parse_mode="HTML"))
                    else:
                        media.append(types.InputMediaPhoto(photo_id, caption=final_text, parse_mode="HTML"))
                else:
                    media.append(types.InputMediaPhoto(photo_id))
            
            # Отправляем в канал
            sent_messages = bot.send_media_group(CHANNEL_ID, media)
            
            # Если есть кнопка, отправляем отдельное сообщение с ней
            if contact_button and len(sent_messages) > 0:
                bot.send_message(CHANNEL_ID, "👇 Связаться с продавцом:", reply_markup=keyboard)
            
        else:
            if contact_button:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(contact_button)
                bot.send_message(CHANNEL_ID, final_text, parse_mode="HTML", reply_markup=keyboard)
            else:
                bot.send_message(CHANNEL_ID, final_text, parse_mode="HTML")
        
        # Уведомляем пользователя
        bot.edit_message_text(
            text="✅ Объявление успешно опубликовано!",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ ПОСЛЕ ПУБЛИКАЦИИ
        safe_send_message(
            user_id,
            "✅ Объявление опубликовано! Возвращаю в главное меню.",
            reply_markup=get_main_keyboard()
        )
        
        logger.info(f"Пользователь {user_id} опубликовал объявление")
        
        # Очищаем состояние
        clear_ad_state(user_id)
        
    except Exception as e:
        logger.error(f"Ошибка публикации объявления: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка публикации. Попробуйте позже.", show_alert=True)
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ ОБЪЯВЛЕНИЯ =====

@bot.callback_query_handler(func=lambda call: call.data == "edit_ad")
def edit_ad_callback(call):
    """Редактирование объявления"""
    user_id = call.from_user.id
    
    # Показываем меню редактирования
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📱 Модель", callback_data="edit_field:model"),
        types.InlineKeyboardButton("💰 Цена", callback_data="edit_field:price"),
        types.InlineKeyboardButton("📊 Характеристики", callback_data="edit_field:specs"),
        types.InlineKeyboardButton("📞 Контакты", callback_data="edit_field:contact"),
        types.InlineKeyboardButton("📷 Фото", callback_data="edit_field:photos")
    )
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_preview"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    bot.edit_message_text(
        text="✏️ Что вы хотите отредактировать?",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard
    )
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        "Редактирование объявления. Выберите поле для изменения:",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_preview")
def back_to_preview_callback(call):
    """Возврат к предпросмотру"""
    user_id = call.from_user.id
    show_ad_preview(user_id)
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        "Возвращаемся к предпросмотру объявления:",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "edit_field:model")
def edit_field_model(call):
    """Редактирование модели устройства"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not ad_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные объявления не найдены", show_alert=True)
        return
    
    device_type = ad_data.get('device_type')
    
    # Определяем тип устройства и устанавливаем соответствующее состояние
    if device_type == 'iphone':
        # Удаляем старые данные модели и связанных характеристик
        if 'model' in ad_data:
            del ad_data['model']
        if 'memory' in ad_data:
            del ad_data['memory']
        if 'condition' in ad_data:
            del ad_data['condition']
        if 'battery' in ad_data:
            del ad_data['battery']
        if 'color' in ad_data:
            del ad_data['color']
        if 'package' in ad_data:
            del ad_data['package']
        
        set_ad_state(user_id, "iphone_model", ad_data)
        
        # Показываем интерфейс ввода модели iPhone
        text = "📱 Введите модель iPhone:\n\nПример: <i>iPhone 11 / 12 Pro / 13 Pro Max / 14 / 15 Pro</i>"
        keyboard = get_back_cancel_inline_keyboard()
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
        safe_send_message(
            user_id,
            "Редактирование модели iPhone. Введите новую модель:",
            reply_markup=get_main_keyboard()
        )
        
    else:  # Android
        # Удаляем старые данные модели и связанных характеристик
        if 'model' in ad_data:
            del ad_data['model']
        if 'ram' in ad_data:
            del ad_data['ram']
        if 'rom' in ad_data:
            del ad_data['rom']
        if 'processor' in ad_data:
            del ad_data['processor']
        if 'condition' in ad_data:
            del ad_data['condition']
        if 'battery' in ad_data:
            del ad_data['battery']
        if 'color' in ad_data:
            del ad_data['color']
        
        set_ad_state(user_id, "android_model", ad_data)
        
        # Показываем интерфейс ввода модели Android
        text = "📱 Введите модель смартфона:"
        keyboard = get_back_cancel_inline_keyboard()
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
        
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
        safe_send_message(
            user_id,
            "Редактирование модели Android. Введите новую модель:",
            reply_markup=get_main_keyboard()
        )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "edit_field:price")
def edit_field_price(call):
    """Редактирование цены"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not ad_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные объявления не найдены", show_alert=True)
        return
    
    # Сохраняем текущие значения для подсказки
    current_price_usd = ad_data.get('price_usd', '')
    current_price_kgs = ad_data.get('price_kgs', '')
    
    # Удаляем старые цены
    if 'price_usd' in ad_data:
        del ad_data['price_usd']
    if 'price_kgs' in ad_data:
        del ad_data['price_kgs']
    
    set_ad_state(user_id, "price_usd", ad_data)
    
    # Показываем интерфейс ввода цены в USD с подсказкой
    hint = f"\n\nТекущее значение: {current_price_usd} USD" if current_price_usd else ""
    text = f"💰 Введите цену в долларах (USD):\n\nТолько число, например: <code>500</code>{hint}"
    keyboard = get_back_cancel_inline_keyboard()
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        "Редактирование цены. Введите новую цену в USD:",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "edit_field:specs")
def edit_field_specs(call):
    """Редактирование характеристик устройства"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not ad_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные объявления не найдены", show_alert=True)
        return
    
    device_type = ad_data.get('device_type')
    
    if device_type == 'iphone':
        # Сохраняем модель, но удаляем характеристики
        model = ad_data.get('model', '')
        
        # Удаляем характеристики iPhone
        if 'memory' in ad_data:
            del ad_data['memory']
        if 'condition' in ad_data:
            del ad_data['condition']
        if 'battery' in ad_data:
            del ad_data['battery']
        if 'color' in ad_data:
            del ad_data['color']
        if 'package' in ad_data:
            del ad_data['package']
        
        set_ad_state(user_id, "iphone_memory", ad_data)
        
        # Показываем выбор памяти iPhone
        text = "💾 Выберите объем памяти:"
        memories = ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"]
        buttons = [types.InlineKeyboardButton(mem, callback_data=f"iphone_memory:{mem}") for mem in memories]
        keyboard = get_navigation_keyboard(buttons)
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
        
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
        safe_send_message(
            user_id,
            f"Редактирование характеристик iPhone {model}. Начнем с выбора памяти:",
            reply_markup=get_main_keyboard()
        )
        
    else:  # Android
        # Сохраняем модель, но удаляем характеристики
        model = ad_data.get('model', '')
        
        # Удаляем характеристики Android
        if 'ram' in ad_data:
            del ad_data['ram']
        if 'rom' in ad_data:
            del ad_data['rom']
        if 'processor' in ad_data:
            del ad_data['processor']
        if 'condition' in ad_data:
            del ad_data['condition']
        if 'battery' in ad_data:
            del ad_data['battery']
        if 'color' in ad_data:
            del ad_data['color']
        
        set_ad_state(user_id, "android_ram", ad_data)
        
        # Показываем выбор оперативной памяти Android
        text = "🧠 Выберите оперативную память (RAM):"
        ram_options = ["2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "12 GB", "16 GB"]
        buttons = [types.InlineKeyboardButton(ram, callback_data=f"android_ram:{ram}") for ram in ram_options]
        keyboard = get_navigation_keyboard(buttons)
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
        
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
        safe_send_message(
            user_id,
            f"Редактирование характеристик {ad_data.get('brand', '')} {model}. Начнем с выбора оперативной памяти:",
            reply_markup=get_main_keyboard()
        )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "edit_field:contact")
def edit_field_contact(call):
    """Редактирование контактных данных"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not ad_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные объявления не найдены", show_alert=True)
        return
    
    # Удаляем старые контактные данные
    if 'contact_type' in ad_data:
        del ad_data['contact_type']
    if 'contact' in ad_data:
        del ad_data['contact']
    
    # Удаляем также фото, так как после изменения контактов нужно будет перезагрузить фото
    if 'ad_photos' in storage.states.get(user_id, {}):
        storage.states[user_id]['ad_photos'] = []
    
    set_ad_state(user_id, "contact", ad_data)
    
    # Показываем интерфейс выбора способа связи
    text = "📞 Выберите способ связи с покупателями:"
    
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True
    )
    keyboard.add(
        types.KeyboardButton("📞 Поделиться номером", request_contact=True),
        types.KeyboardButton("💬 Связь через Telegram")
    )
    keyboard.add(types.KeyboardButton("🔙 Назад"))
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    
    # Отправляем новое сообщение с reply-клавиатурой
    bot.send_message(user_id, text, reply_markup=keyboard)
    
    # Редактируем исходное сообщение, чтобы убрать inline-клавиатуру
    bot.edit_message_text(
        text="✏️ Редактирование контактных данных",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        "Редактирование контактных данных. Выберите новый способ связи:",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "edit_field:photos")
def edit_field_photos(call):
    """Редактирование фотографий"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not ad_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные объявления не найдены", show_alert=True)
        return
    
    # Очищаем список фотографий
    if 'ad_photos' in storage.states.get(user_id, {}):
        storage.states[user_id]['ad_photos'] = []
    
    set_ad_state(user_id, "photos", ad_data)
    
    # Показываем интерфейс загрузки фото
    text = f"📷 Теперь отправьте фото телефона (2-4 фото):\n" \
           f"Минимум: 2 фото\n" \
           f"Максимум: 4 фото\n\n" \
           f"Загружено: 0 фото\n" \
           f"Осталось: 2 фото (минимум)"
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🔙 Назад"))
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    
    # Отправляем новое сообщение с reply-клавиатурой
    bot.send_message(user_id, text, reply_markup=keyboard)
    
    # Редактируем исходное сообщение, чтобы убрать inline-клавиатуру
    bot.edit_message_text(
        text="✏️ Редактирование фотографий",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    
    # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
    safe_send_message(
        user_id,
        "Редактирование фотографий. Загрузите новые фотографии:",
        reply_markup=get_main_keyboard()
    )
    
    bot.answer_callback_query(call.id)

# ===== ЗАПУСК БОТА С НОВЫМ ФУНКЦИОНАЛОМ =====
if __name__ == '__main__':
    print("=" * 60)
    print("🤖 БОТ ДЛЯ ОБЪЯВЛЕНИЙ О ТЕЛЕФОНАХ")
    print("=" * 60)
    print(f"Telegram Bot Token: {'✅ Установлен' if TOKEN != '8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"CryptoBot API Key: {'✅ Установлен' if CRYPTO_BOT_API_KEY != '498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Канал для публикаций: {CHANNEL_ID}")
    print(f"Чат поддержки: {SUPPORT_CHAT_ID}")
    print(f"CEO Admin ID: {ADMIN_CEO_ID or '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Support Admin ID: {ADMIN_SUPPORT_ID or '❌ НЕ УСТАНОВЛЕН'}")
    print("=" * 60)
    print("📢 Основные команды:")
    print("• /start - Начать работу с кнопкой создания объявления")
    print("• /mytickets - Мои обращения в поддержку")
    print("• 📞 Поддержка - Обратиться в поддержку")
    print("• 💎 Донат - Поддержать бота")
    print("=" * 60)
    print("🆕 ДОБАВЛЕН ФУНКЦИОНАЛ СОЗДАНИЯ ОБЪЯВЛЕНИЙ:")
    print("✅ Поддержка iPhone и Android")
    print("✅ Пошаговое создание с валидацией")
    print("✅ Загрузка 2-4 фото")
    print("✅ Публикация в канал с кнопкой связи")
    print("✅ Предпросмотр перед публикацией")
    print("✅ Возможность редактирования")
    print("✅ Кнопка 'Назад' на каждом шаге")
    print("=" * 60)
    print("🔧 Фоновые процессы запущены:")
    print("• Проверка платежей CryptoBot")
    print("• Очистка старых данных")
    print("• Очистка старых тикетов")
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