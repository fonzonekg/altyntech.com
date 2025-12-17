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

# ===== ИМПОРТ ДЛЯ ИНТЕЛЛЕКТУАЛЬНЫХ ФУНКЦИЙ =====
try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    print("⚠️ RapidFuzz не установлен. Установите: pip install rapidfuzz")

try:
    from profanity_filter import ProfanityFilter
    pf = ProfanityFilter()
    HAS_PROFANITY_FILTER = True
except ImportError:
    HAS_PROFANITY_FILTER = False
    print("⚠️ Profanity-filter не установлен. Установите: pip install profanity-filter")

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

# ===== БАЗА ДАННЫХ МОДЕЛЕЙ СМАРТФОНОВ =====
SMARTPHONE_MODELS = {
    "Apple": [
        "iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 15 Plus", "iPhone 15",
        "iPhone 14 Pro Max", "iPhone 14 Pro", "iPhone 14 Plus", "iPhone 14",
        "iPhone 13 Pro Max", "iPhone 13 Pro", "iPhone 13", "iPhone 13 mini",
        "iPhone 12 Pro Max", "iPhone 12 Pro", "iPhone 12", "iPhone 12 mini",
        "iPhone 11 Pro Max", "iPhone 11 Pro", "iPhone 11", "iPhone SE (2022)",
        "iPhone SE (2020)", "iPhone XS Max", "iPhone XS", "iPhone XR", "iPhone X"
    ],
    "Samsung": [
        "Galaxy S24 Ultra", "Galaxy S24 Plus", "Galaxy S24",
        "Galaxy S23 Ultra", "Galaxy S23 Plus", "Galaxy S23",
        "Galaxy S22 Ultra", "Galaxy S22 Plus", "Galaxy S22",
        "Galaxy S21 Ultra", "Galaxy S21 Plus", "Galaxy S21",
        "Galaxy Z Fold 5", "Galaxy Z Flip 5", "Galaxy Z Fold 4", "Galaxy Z Flip 4",
        "Galaxy A54", "Galaxy A34", "Galaxy A14", "Galaxy M54", "Galaxy M34"
    ],
    "Xiaomi": [
        "Xiaomi 14 Pro", "Xiaomi 14", "Xiaomi 13 Pro", "Xiaomi 13",
        "Xiaomi 12 Pro", "Xiaomi 12", "Xiaomi 11 Pro", "Xiaomi 11",
        "Redmi Note 13 Pro+", "Redmi Note 13 Pro", "Redmi Note 13",
        "Redmi Note 12 Pro+", "Redmi Note 12 Pro", "Redmi Note 12",
        "Poco F5", "Poco X5 Pro", "Poco M5", "Poco C65"
    ],
    "Redmi": [
        "Redmi Note 13 Pro+", "Redmi Note 13 Pro", "Redmi Note 13",
        "Redmi Note 12 Pro+", "Redmi Note 12 Pro", "Redmi Note 12",
        "Redmi Note 11 Pro+", "Redmi Note 11 Pro", "Redmi Note 11",
        "Redmi 13C", "Redmi 12", "Redmi 10", "Redmi 9"
    ],
    "POCO": [
        "POCO F5", "POCO F4", "POCO X5 Pro", "POCO X5",
        "POCO M5", "POCO M4 Pro", "POCO C65", "POCO C55"
    ],
    "Realme": [
        "Realme GT 5 Pro", "Realme GT 5", "Realme GT Neo 5",
        "Realme 11 Pro+", "Realme 11 Pro", "Realme 11",
        "Realme 10 Pro+", "Realme 10 Pro", "Realme 10",
        "Realme Narzo 60 Pro", "Realme Narzo 60", "Realme C55"
    ],
    "Oppo": [
        "Oppo Find X6 Pro", "Oppo Find X6", "Oppo Find X5 Pro",
        "Oppo Reno 11 Pro", "Oppo Reno 11", "Oppo Reno 10 Pro",
        "Oppo A98", "Oppo A78", "Oppo A58", "Oppo A38"
    ],
    "Vivo": [
        "Vivo X100 Pro", "Vivo X100", "Vivo X90 Pro",
        "Vivo V29 Pro", "Vivo V29", "Vivo V27",
        "Vivo Y100", "Vivo Y78", "Vivo Y56", "Vivo T2"
    ],
    "Huawei": [
        "Huawei P60 Pro", "Huawei P60", "Huawei P50 Pro",
        "Huawei Mate 60 Pro", "Huawei Mate 50 Pro",
        "Huawei Nova 11", "Huawei Nova 10", "Huawei Enjoy 70"
    ],
    "Honor": [
        "Honor Magic 6 Pro", "Honor Magic 5 Pro", "Honor Magic 4 Pro",
        "Honor 90", "Honor 80", "Honor X9b", "Honor X8b", "Honor X7b"
    ],
    "Google Pixel": [
        "Pixel 8 Pro", "Pixel 8", "Pixel 7 Pro", "Pixel 7",
        "Pixel 6 Pro", "Pixel 6", "Pixel 5", "Pixel 4a"
    ],
    "OnePlus": [
        "OnePlus 12", "OnePlus 11", "OnePlus 10 Pro",
        "OnePlus Nord 3", "OnePlus Nord CE 3", "OnePlus Nord N30"
    ],
    "Nokia": [
        "Nokia G42", "Nokia G22", "Nokia C32", "Nokia C22",
        "Nokia X30", "Nokia X20", "Nokia 8.3", "Nokia 7.2"
    ],
    "Sony": [
        "Xperia 1 V", "Xperia 5 V", "Xperia 10 V",
        "Xperia 1 IV", "Xperia 5 IV", "Xperia 10 IV"
    ],
    "Asus": [
        "ROG Phone 7", "ROG Phone 6", "ZenFone 10",
        "ZenFone 9", "Zenfone 8", "ROG Phone 5"
    ],
    "Infinix": [
        "Infinix Zero 30", "Infinix Zero 20", "Infinix Hot 40 Pro",
        "Infinix Hot 30", "Infinix Smart 8", "Infinix Note 30"
    ],
    "Tecno": [
        "Tecno Phantom V Fold", "Tecno Phantom V Flip",
        "Tecno Camon 20 Pro", "Tecno Spark 20 Pro", "Tecno Pova 5"
    ],
    "ZTE": [
        "ZTE Nubia Z50", "ZTE Nubia Z40 Pro",
        "ZTE Blade V40", "ZTE Blade V30", "ZTE Axon 40"
    ],
    "Meizu": [
        "Meizu 20 Pro", "Meizu 20", "Meizu 18s Pro",
        "Meizu 18 Pro", "Meizu 18", "Meizu 17 Pro"
    ]
}

# Стандартные характеристики для популярных моделей
MODEL_PRESETS = {
    # Apple iPhone
    "iPhone 15 Pro Max": {"memory_options": ["256 GB", "512 GB", "1 TB"], "colors": ["Титановый", "Синий", "Белый", "Черный"]},
    "iPhone 15 Pro": {"memory_options": ["128 GB", "256 GB", "512 GB", "1 TB"], "colors": ["Титановый", "Синий", "Белый", "Черный"]},
    "iPhone 15": {"memory_options": ["128 GB", "256 GB", "512 GB"], "colors": ["Черный", "Синий", "Зеленый", "Желтый", "Розовый"]},
    "iPhone 14 Pro Max": {"memory_options": ["128 GB", "256 GB", "512 GB", "1 TB"], "colors": ["Фиолетовый", "Золотой", "Серебристый", "Графитовый"]},
    "iPhone 14": {"memory_options": ["128 GB", "256 GB", "512 GB"], "colors": ["Синий", "Фиолетовый", "Полночь", "Звездный свет", "Красный"]},
    
    # Samsung
    "Galaxy S24 Ultra": {"ram_options": ["12 GB"], "rom_options": ["256 GB", "512 GB", "1 TB"], "colors": ["Титановый", "Черный", "Фиолетовый", "Желтый"]},
    "Galaxy S23 Ultra": {"ram_options": ["8 GB", "12 GB"], "rom_options": ["256 GB", "512 GB", "1 TB"], "colors": ["Черный", "Кремовый", "Зеленый", "Фиолетовый"]},
    "Galaxy A54": {"ram_options": ["6 GB", "8 GB"], "rom_options": ["128 GB", "256 GB"], "colors": ["Черный", "Белый", "Фиолетовый", "Зеленый"]},
    
    # Xiaomi
    "Xiaomi 14 Pro": {"ram_options": ["12 GB", "16 GB"], "rom_options": ["256 GB", "512 GB", "1 TB"], "colors": ["Черный", "Белый", "Зеленый"]},
    "Redmi Note 13 Pro": {"ram_options": ["8 GB", "12 GB"], "rom_options": ["128 GB", "256 GB", "512 GB"], "colors": ["Черный", "Белый", "Синий", "Фиолетовый"]},
    
    # Google Pixel
    "Pixel 8 Pro": {"ram_options": ["12 GB"], "rom_options": ["128 GB", "256 GB", "512 GB"], "colors": ["Черный", "Белый", "Синий"]},
}

# ===== ФУНКЦИИ ИНТЕЛЛЕКТУАЛЬНОЙ СИСТЕМЫ =====

def suggest_models(brand, query=None, limit=8):
    """Предлагает модели по бренду с фильтрацией по запросу"""
    models = SMARTPHONE_MODELS.get(brand, [])
    
    if not query:
        return models[:limit]
    
    if HAS_RAPIDFUZZ:
        # Нечеткий поиск с использованием RapidFuzz
        results = process.extract(query, models, limit=limit, scorer=fuzz.partial_ratio)
        return [result[0] for result in results if result[1] > 50]  # Порог схожести 50%
    else:
        # Простой префиксный поиск
        query_lower = query.lower()
        return [model for model in models if query_lower in model.lower()][:limit]

def predict_next_steps(ad_data):
    """Предсказывает следующие шаги на основе уже заполненных данных"""
    brand = ad_data.get('brand')
    model = ad_data.get('model')
    device_type = ad_data.get('device_type')
    
    steps = []
    
    if brand and not model:
        steps.append(("model", "Введите модель телефона"))
    
    if model and device_type == "iphone":
        if not ad_data.get('memory'):
            steps.append(("memory", "Выберите объем памяти"))
        elif not ad_data.get('condition'):
            steps.append(("condition", "Выберите состояние телефона"))
        elif not ad_data.get('battery'):
            steps.append(("battery", "Введите состояние аккумулятора"))
        elif not ad_data.get('color'):
            steps.append(("color", "Введите цвет телефона"))
        elif not ad_data.get('package'):
            steps.append(("package", "Выберите комплектацию"))
    
    if model and device_type == "android":
        if not ad_data.get('ram'):
            steps.append(("ram", "Выберите оперативную память"))
        elif not ad_data.get('rom'):
            steps.append(("rom", "Выберите встроенную память"))
        elif not ad_data.get('processor'):
            steps.append(("processor", "Введите модель процессора"))
        elif not ad_data.get('condition'):
            steps.append(("condition", "Выберите состояние телефона"))
        elif not ad_data.get('battery'):
            steps.append(("battery", "Выберите состояние аккумулятора"))
        elif not ad_data.get('color'):
            steps.append(("color", "Введите цвет телефона"))
    
    if not ad_data.get('price_usd'):
        steps.append(("price_usd", "Введите цену в USD"))
    elif not ad_data.get('price_kgs'):
        steps.append(("price_kgs", "Введите цену в KGS"))
    
    if not ad_data.get('contact'):
        steps.append(("contact", "Выберите способ связи"))
    
    return steps

def get_model_preset_suggestions(model_name):
    """Получает предустановленные значения для модели"""
    return MODEL_PRESETS.get(model_name, {})

def check_duplicate_ads(user_id, new_ad_text, threshold=85):
    """Проверяет наличие дубликатов объявлений"""
    if not HAS_RAPIDFUZZ:
        return []
    
    duplicates = []
    
    # Ищем объявления пользователя в истории
    # В реальной системе здесь был бы запрос к базе данных
    # Сейчас используем простую эмуляцию
    user_ads = []
    
    # Получаем все тикеты пользователя как пример
    user_tickets = smart_support.get_user_tickets(user_id)
    for ticket in user_tickets:
        if "объявление" in ticket['messages'][0]['text'].lower():
            user_ads.append(ticket['messages'][0]['text'])
    
    # Проверяем схожесть
    for ad_text in user_ads[-10:]:  # Проверяем последние 10 объявлений
        similarity = fuzz.ratio(new_ad_text.lower(), ad_text.lower())
        if similarity > threshold:
            duplicates.append({"text": ad_text[:100], "similarity": similarity})
    
    return duplicates

def validate_input(text, field_type, min_length=1, max_length=500):
    """Валидация вводимых данных"""
    if not text or len(text.strip()) < min_length:
        return False, f"Текст должен содержать не менее {min_length} символа"
    
    if len(text) > max_length:
        return False, f"Текст не должен превышать {max_length} символов"
    
    # Фильтрация нежелательной лексики
    if HAS_PROFANITY_FILTER and pf.is_profane(text):
        return False, "Текст содержит недопустимые выражения"
    
    # Проверка на спам (множество ссылок)
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)
    if len(urls) > 3:
        return False, "Обнаружено слишком много ссылок. Возможен спам"
    
    # Специфичная валидация для разных типов полей
    if field_type == "price":
        try:
            price = float(text.replace(',', '.'))
            if price <= 0:
                return False, "Цена должна быть больше 0"
            if price > 1000000:
                return False, "Цена слишком высокая"
        except ValueError:
            return False, "Введите корректное число"
    
    elif field_type == "battery":
        try:
            battery = int(text)
            if not (0 <= battery <= 100):
                return False, "Процент батареи должен быть от 0 до 100"
        except ValueError:
            if text not in ["Отличный", "Нормальный", "Требует замены"]:
                return False, "Введите число от 0 до 100 или выберите из списка"
    
    return True, ""

def filter_profanity(text):
    """Фильтрация нецензурной лексики"""
    if HAS_PROFANITY_FILTER:
        return pf.censor(text)
    return text

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
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back"),
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
    """Обработка команды /start с видео и кнопкой умного создания"""
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
    
    # Создаем inline-клавиатуру ТОЛЬКО с кнопкой умного создания согласно ТЗ
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🤖 Умное создание", callback_data="smart_create_ad"))
    
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
    
    # ВАЖНО: УДАЛЕНЫ все дополнительные сообщения после приветствия
    # согласно ТЗ: "После отправки приветствия с видео и кнопкой не должно следовать никаких дополнительных сообщений"

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

# ===== НОВЫЙ ФУНКЦИОНАЛ: СОЗДАНИЕ ОБЪЯВЛЕНИЙ О СМАРТФОНОХ =====

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

# ===== УМНОЕ СОЗДАНИЕ ОБЪЯВЛЕНИЯ (ЕДИНСТВЕННЫЙ РЕЖИМ) =====
@bot.callback_query_handler(func=lambda call: call.data == "smart_create_ad")
def smart_create_ad_callback(call):
    """Начало умного создания объявления (единственный режим)"""
    user_id = call.from_user.id
    
    # Проверяем черновик
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    if ad_data:
        # Предлагаем продолжить черновик
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton("✅ Продолжить", callback_data="continue_draft"),
            types.InlineKeyboardButton("🔄 Начать заново", callback_data="restart_ad")
        )
        
        bot.edit_message_text(
            text="📝 <b>Найден незавершенный черновик!</b>\n\n"
                 f"Вы остановились на шаге: {ad_step}\n"
                 f"Модель: {ad_data.get('model', 'не указана')}\n"
                 f"Цена: {ad_data.get('price_usd', 'не указана')} USD\n\n"
                 "Хотите продолжить или начать заново?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return
    
    # Начинаем новый процесс
    clear_ad_state(user_id)
    set_ad_state(user_id, "smart_choose_brand")
    
    text = "📱 <b>Умное создание объявления</b>\n\nВыберите бренд смартфона:"
    
    # Создаем inline-клавиатуру с брендами (4 колонки)
    brands = list(SMARTPHONE_MODELS.keys())
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    buttons = []
    for brand in brands:
        buttons.append(types.InlineKeyboardButton(brand, callback_data=f"smart_brand:{brand}"))
    
    # Распределяем кнопки по рядам
    for i in range(0, len(buttons), 4):
        keyboard.row(*buttons[i:i+4])
    
    keyboard.row(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad"))
    
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
        "Начинаем создание объявления! Выберите бренд:",
        reply_markup=get_main_keyboard()
    )

# ===== УМНЫЙ ВЫБОР БРЕНДА =====

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_brand:'))
def smart_brand_callback(call):
    """Умный выбор бренда с предсказанием следующих шагов"""
    user_id = call.from_user.id
    brand = call.data.split(':')[1]
    
    # Сохраняем бренд и определяем тип устройства
    device_type = "iphone" if brand == "Apple" else "android"
    set_ad_state(user_id, "smart_model", {"brand": brand, "device_type": device_type})
    
    # Получаем популярные модели для этого бренда
    popular_models = suggest_models(brand, limit=12)
    
    text = f"📱 <b>Выбран бренд: {brand}</b>\n\n"
    text += "Выберите модель из списка или введите вручную:\n\n"
    text += "<i>Самые популярные модели:</i>"
    
    # Создаем клавиатуру с популярными моделями
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    for i in range(0, len(popular_models), 2):
        if i + 1 < len(popular_models):
            keyboard.row(
                types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"),
                types.InlineKeyboardButton(popular_models[i+1], callback_data=f"smart_model:{popular_models[i+1]}")
            )
        else:
            keyboard.row(types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"))
    
    # Кнопки для ручного ввода и поиска
    keyboard.row(types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"))
    keyboard.row(types.InlineKeyboardButton("🔍 Поиск модели", callback_data="smart_search_model"))
    
    # Кнопки навигации
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
    
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

def create_memory_keyboard(options):
    """Создает клавиатуру для выбора памяти"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    for i in range(0, len(options), 2):
        if i + 1 < len(options):
            keyboard.row(
                types.InlineKeyboardButton(options[i], callback_data=f"smart_iphone_memory:{options[i]}"),
                types.InlineKeyboardButton(options[i+1], callback_data=f"smart_iphone_memory:{options[i+1]}")
            )
        else:
            keyboard.row(types.InlineKeyboardButton(options[i], callback_data=f"smart_iphone_memory:{options[i]}"))
    
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_model"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    return keyboard

def create_ram_keyboard(options):
    """Создает клавиатуру для выбора оперативной памяти"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    for i in range(0, len(options), 2):
        if i + 1 < len(options):
            keyboard.row(
                types.InlineKeyboardButton(options[i], callback_data=f"smart_android_ram:{options[i]}"),
                types.InlineKeyboardButton(options[i+1], callback_data=f"smart_android_ram:{options[i+1]}")
            )
        else:
            keyboard.row(types.InlineKeyboardButton(options[i], callback_data=f"smart_android_ram:{options[i]}"))
    
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_model"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    return keyboard

# ===== УМНЫЙ ВЫБОР МОДЕЛИ =====

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_model:'))
def smart_model_callback(call):
    """Умный выбор модели с автоподсказками"""
    user_id = call.from_user.id
    model = call.data.split(':')[1]
    
    # Получаем текущие данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    brand = ad_data.get('brand')
    device_type = ad_data.get('device_type')
    
    # Сохраняем модель
    ad_data['model'] = model
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Получаем предустановленные значения для модели
    presets = get_model_preset_suggestions(model)
    
    text = f"✅ <b>Выбрана модель: {model}</b>\n\n"
    
    # Показываем предсказанные следующие шаги
    next_steps = predict_next_steps(ad_data)
    if next_steps:
        text += "<b>Следующие шаги:</b>\n"
        for i, (step, description) in enumerate(next_steps[:3], 1):
            text += f"{i}. {description}\n"
    
    # Показываем предустановленные характеристики, если есть
    if presets:
        text += "\n<b>Обычные характеристики для этой модели:</b>\n"
        if 'memory_options' in presets:
            text += f"• Память: {', '.join(presets['memory_options'])}\n"
        if 'ram_options' in presets:
            text += f"• ОЗУ: {', '.join(presets['ram_options'])}\n"
        if 'rom_options' in presets:
            text += f"• ПЗУ: {', '.join(presets['rom_options'])}\n"
        if 'colors' in presets:
            text += f"• Цвета: {', '.join(presets['colors'])}\n"
    
    # Определяем следующий шаг
    if device_type == "iphone":
        if not ad_data.get('memory'):
            next_step = "smart_iphone_memory"
            keyboard = create_memory_keyboard(presets.get('memory_options', ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"]))
        else:
            next_step = "smart_next_step"
            keyboard = get_back_cancel_inline_keyboard()
    else:
        if not ad_data.get('ram'):
            next_step = "smart_android_ram"
            keyboard = create_ram_keyboard(presets.get('ram_options', ["4 GB", "6 GB", "8 GB", "12 GB", "16 GB"]))
        else:
            next_step = "smart_next_step"
            keyboard = get_back_cancel_inline_keyboard()
    
    set_ad_state(user_id, next_step, ad_data)
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
    
    bot.answer_callback_query(call.id)

# ===== ОБРАБОТЧИК РУЧНОГО ВВОДА МОДЕЛИ =====

@bot.callback_query_handler(func=lambda call: call.data == "smart_enter_model")
def smart_enter_model_callback(call):
    """Ручной ввод модели с валидацией"""
    user_id = call.from_user.id
    
    # Устанавливаем состояние ручного ввода
    set_ad_state(user_id, "smart_enter_model")
    
    text = "✏️ <b>Введите модель вручную:</b>\n\n"
    text += "Укажите точное название модели.\n"
    text += "Пример: <i>Samsung Galaxy S23 Ultra, iPhone 15 Pro Max, Xiaomi 13 Pro</i>\n\n"
    text += "<b>Проверка будет выполнена автоматически:</b>\n"
    text += "✅ Корректность названия\n"
    text += "✅ Отсутствие запрещенных слов\n"
    text += "✅ Проверка на дубликаты"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
    
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_enter_model")
def handle_smart_model_input(message):
    """Обработка ручного ввода модели с интеллектуальной проверкой"""
    user_id = message.from_user.id
    model = message.text.strip()
    
    # Валидация ввода
    is_valid, error_msg = validate_input(model, "text", min_length=2, max_length=100)
    if not is_valid:
        safe_send_message(
            user_id,
            f"❌ <b>Ошибка валидации:</b>\n{error_msg}\n\nПожалуйста, введите модель еще раз:",
            reply_markup=get_back_cancel_inline_keyboard()
        )
        return
    
    # Фильтрация нецензурной лексики
    filtered_model = filter_profanity(model)
    if filtered_model != model:
        safe_send_message(
            user_id,
            f"⚠️ <b>Обнаружены недопустимые слова!</b>\n"
            f"Исправленная модель: <b>{filtered_model}</b>\n\n"
            "Продолжить с исправленным вариантом?",
            reply_markup=types.InlineKeyboardMarkup().row(
                types.InlineKeyboardButton("✅ Да", callback_data=f"smart_use_filtered_model:{filtered_model}"),
                types.InlineKeyboardButton("🔙 Ввести заново", callback_data="smart_enter_model")
            )
        )
        return
    
    # Сохраняем модель
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['model'] = model
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, message.chat.id, message.message_id)

# ===== УМНЫЕ ОБРАБОТЧИКИ ДЛЯ ОСТАЛЬНЫХ ШАГОВ =====

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_iphone_memory:'))
def smart_iphone_memory_callback(call):
    """Обработка выбора памяти iPhone с предсказанием"""
    user_id = call.from_user.id
    memory = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['memory'] = memory
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_android_ram:'))
def smart_android_ram_callback(call):
    """Обработка выбора оперативной памяти Android с предсказанием"""
    user_id = call.from_user.id
    ram = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['ram'] = ram
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

def show_smart_next_step(user_id, chat_id=None, message_id=None):
    """Показывает следующий интеллектуальный шаг"""
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Получаем предсказанные следующие шаги
    next_steps = predict_next_steps(ad_data)
    
    if not next_steps:
        # Все шаги заполнены, показываем предпросмотр
        show_ad_preview(user_id)
        return
    
    next_step, description = next_steps[0]
    device_type = ad_data.get('device_type')
    
    text = f"📝 <b>Шаг: {description}</b>\n\n"
    
    # Формируем текст в зависимости от шага
    if next_step == "model":
        brand = ad_data.get('brand')
        popular_models = suggest_models(brand, limit=8)
        
        text = f"📱 <b>Выберите модель {brand}:</b>\n\n"
        text += "<i>Популярные модели:</i>"
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        for i in range(0, len(popular_models), 2):
            if i + 1 < len(popular_models):
                keyboard.row(
                    types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"),
                    types.InlineKeyboardButton(popular_models[i+1], callback_data=f"smart_model:{popular_models[i+1]}")
                )
            else:
                keyboard.row(types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"))
        
        keyboard.row(types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"))
        
    elif next_step == "memory" and device_type == "iphone":
        model = ad_data.get('model')
        presets = get_model_preset_suggestions(model)
        options = presets.get('memory_options', ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"])
        
        text += f"Выберите объем памяти для {model}:"
        keyboard = create_memory_keyboard(options)
        set_ad_state(user_id, "smart_iphone_memory", ad_data)
    
    elif next_step == "ram" and device_type == "android":
        model = ad_data.get('model')
        presets = get_model_preset_suggestions(model)
        options = presets.get('ram_options', ["4 GB", "6 GB", "8 GB", "12 GB", "16 GB"])
        
        text += f"Выберите оперативную память для {model}:"
        keyboard = create_ram_keyboard(options)
        set_ad_state(user_id, "smart_android_ram", ad_data)
    
    elif next_step == "condition":
        conditions = ["Новый", "Отличное", "Хорошее", "Удовлетворительное"]
        text += "Выберите состояние телефона:"
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        for i in range(0, len(conditions), 2):
            if i + 1 < len(conditions):
                callback = f"smart_{device_type}_condition:{conditions[i]}" if device_type == "iphone" else f"smart_{device_type}_condition:{conditions[i]}"
                callback2 = f"smart_{device_type}_condition:{conditions[i+1]}" if device_type == "iphone" else f"smart_{device_type}_condition:{conditions[i+1]}"
                keyboard.row(
                    types.InlineKeyboardButton(conditions[i], callback_data=callback),
                    types.InlineKeyboardButton(conditions[i+1], callback_data=callback2)
                )
            else:
                callback = f"smart_{device_type}_condition:{conditions[i]}" if device_type == "iphone" else f"smart_{device_type}_condition:{conditions[i]}"
                keyboard.row(types.InlineKeyboardButton(conditions[i], callback_data=callback))
        
        set_ad_state(user_id, f"smart_{device_type}_condition", ad_data)
    
    elif next_step == "price_usd":
        model = ad_data.get('model')
        
        # Предлагаем ориентировочную цену
        avg_prices = {
            "iPhone": {"new": 1000, "used": 500},
            "Samsung": {"new": 800, "used": 400},
            "Xiaomi": {"new": 600, "used": 300},
            "default": {"new": 500, "used": 250}
        }
        
        condition = ad_data.get('condition', 'Хорошее')
        is_new = condition == "Новый"
        brand = ad_data.get('brand', 'default')
        price_type = "new" if is_new else "used"
        
        suggested_price = avg_prices.get(brand, avg_prices["default"])[price_type]
        
        text += f"💰 Введите цену в USD для {model}\n\n"
        text += f"<i>Ориентировочная цена для состояния '{condition}': ${suggested_price}</i>\n\n"
        text += "Введите число (например: 500 или 299.99):"
        
        keyboard = get_back_cancel_inline_keyboard()
        set_ad_state(user_id, "smart_price_usd", ad_data)
    
    else:
        # Для других шагов используем стандартный интерфейс
        return
    
    # Добавляем кнопки навигации
    if 'keyboard' not in locals():
        keyboard = get_back_cancel_inline_keyboard()
    else:
        # Добавляем кнопки Назад и Отмена, если их еще нет
        rows = keyboard.to_dict()['inline_keyboard']
        has_back = any(button['text'] == '🔙 Назад' for row in rows for button in row)
        if not has_back:
            keyboard.row(
                types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
            )
    
    try:
        if chat_id and message_id:
            bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            bot.send_message(user_id, text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка показа следующего шага: {e}")

# ===== УМНАЯ КНОПКА НАЗАД =====

@bot.callback_query_handler(func=lambda call: call.data == "smart_back")
def smart_back_callback(call):
    """Умная кнопка Назад - возвращает на предыдущий шаг с сохранением данных"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Определяем предыдущий шаг на основе текущего
    step_history = []
    
    # Восстанавливаем историю шагов
    if 'step_history' not in storage.states.get(user_id, {}):
        storage.states[user_id]['step_history'] = []
    
    step_history = storage.states[user_id]['step_history']
    
    if not step_history:
        # Если истории нет, определяем логически
        if ad_step == "smart_model" or "model" in ad_step:
            previous_step = "smart_choose_brand"
            if 'brand' in ad_data:
                del ad_data['brand']
        elif "memory" in ad_step or "ram" in ad_step:
            previous_step = "smart_model"
            if 'model' in ad_data:
                del ad_data['model']
        elif "condition" in ad_step:
            device_type = ad_data.get('device_type')
            if device_type == "iphone":
                previous_step = "smart_iphone_memory"
                if 'memory' in ad_data:
                    del ad_data['memory']
            else:
                previous_step = "smart_android_ram"
                if 'ram' in ad_data:
                    del ad_data['ram']
        else:
            previous_step = "smart_choose_brand"
    else:
        # Берем предыдущий шаг из истории
        previous_step = step_history.pop() if step_history else "smart_choose_brand"
        storage.states[user_id]['step_history'] = step_history
    
    # Устанавливаем предыдущий шаг
    set_ad_state(user_id, previous_step, ad_data)
    
    # Показываем интерфейс предыдущего шага
    if previous_step.startswith("smart_"):
        show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_use_filtered_model:'))
def smart_use_filtered_model_callback(call):
    """Использование исправленной модели"""
    user_id = call.from_user.id
    filtered_model = call.data.split(':')[1]
    
    # Сохраняем исправленную модель
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['model'] = filtered_model
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "smart_back_to_brand")
def smart_back_to_brand_callback(call):
    """Возврат к выбору бренда в умном режиме"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Удаляем бренд и переходим к выбору бренда
    if 'brand' in ad_data:
        del ad_data['brand']
    if 'device_type' in ad_data:
        del ad_data['device_type']
    
    set_ad_state(user_id, "smart_choose_brand", ad_data)
    
    # Показываем выбор бренда
    text = "📱 <b>Умное создание объявления</b>\n\nВыберите бренд смартфона:"
    
    brands = list(SMARTPHONE_MODELS.keys())
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    buttons = []
    for brand in brands:
        buttons.append(types.InlineKeyboardButton(brand, callback_data=f"smart_brand:{brand}"))
    
    for i in range(0, len(buttons), 4):
        keyboard.row(*buttons[i:i+4])
    
    keyboard.row(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad"))
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "smart_back_to_model")
def smart_back_to_model_callback(call):
    """Возврат к выбору модели в умном режиме"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Удаляем модель
    if 'model' in ad_data:
        del ad_data['model']
    
    set_ad_state(user_id, "smart_model", ad_data)
    
    # Показываем выбор модели
    brand = ad_data.get('brand')
    popular_models = suggest_models(brand, limit=12)
    
    text = f"📱 <b>Выбран бренд: {brand}</b>\n\n"
    text += "Выберите модель из списка или введите вручную:\n\n"
    text += "<i>Самые популярные модели:</i>"
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    for i in range(0, len(popular_models), 2):
        if i + 1 < len(popular_models):
            keyboard.row(
                types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"),
                types.InlineKeyboardButton(popular_models[i+1], callback_data=f"smart_model:{popular_models[i+1]}")
            )
        else:
            keyboard.row(types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"))
    
    keyboard.row(types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"))
    keyboard.row(types.InlineKeyboardButton("🔍 Поиск модели", callback_data="smart_search_model"))
    
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    bot.answer_callback_query(call.id)

# ===== НОВЫЕ ОБРАБОТЧИКИ ДЛЯ УМНОГО РЕЖИМА =====

@bot.callback_query_handler(func=lambda call: call.data == "smart_search_model")
def smart_search_model_callback(call):
    """Обработка поиска модели"""
    user_id = call.from_user.id
    
    text = "🔍 <b>Поиск модели</b>\n\n"
    text += "Введите часть названия модели для поиска:\n"
    text += "Пример: <i>S23, Note 13, iPhone 14</i>"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_model"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_iphone_condition:'))
def smart_iphone_condition_callback(call):
    """Обработка выбора состояния iPhone в умном режиме"""
    user_id = call.from_user.id
    condition = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['condition'] = condition
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_iphone_package:'))
def smart_iphone_package_callback(call):
    """Обработка выбора комплектации iPhone в умном режиме"""
    user_id = call.from_user.id
    package = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['package'] = package
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_android_rom:'))
def smart_android_rom_callback(call):
    """Обработка выбора встроенной памяти Android в умном режиме"""
    user_id = call.from_user.id
    rom = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['rom'] = rom
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_android_condition:'))
def smart_android_condition_callback(call):
    """Обработка выбора состояния Android в умном режиме"""
    user_id = call.from_user.id
    condition = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['condition'] = condition
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_android_battery:'))
def smart_android_battery_callback(call):
    """Обработка выбора батареи Android в умном режиме"""
    user_id = call.from_user.id
    battery = call.data.split(':')[1]
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['battery'] = battery
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_iphone_battery")
def handle_smart_iphone_battery(message):
    """Обработка ввода батареи iPhone в умном режиме"""
    user_id = message.from_user.id
    battery_text = message.text.strip()
    
    # Проверяем отмену
    if battery_text == "❌ Отмена":
        clear_ad_state(user_id)
        safe_send_message(user_id, "❌ Создание объявления отменено.")
        return
    
    # Валидация
    try:
        battery = int(battery_text)
        if 70 <= battery <= 100:
            # Сохраняем данные
            ad_step, ad_data, ad_photos = get_ad_state(user_id)
            ad_data['battery'] = battery
            set_ad_state(user_id, "smart_next_step", ad_data)
            
            # Показываем следующий шаг
            show_smart_next_step(user_id)
        else:
            bot.send_message(
                user_id,
                "❌ Введите число от 70 до 100:",
                reply_markup=get_back_cancel_inline_keyboard()
            )
    except ValueError:
        bot.send_message(
            user_id,
            "❌ Пожалуйста, введите число от 70 до 100:",
            reply_markup=get_back_cancel_inline_keyboard()
        )

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_iphone_color")
def handle_smart_iphone_color(message):
    """Обработка ввода цвета iPhone в умном режиме"""
    user_id = message.from_user.id
    color = message.text.strip()
    
    # Проверяем отмену
    if color == "❌ Отмена":
        clear_ad_state(user_id)
        safe_send_message(user_id, "❌ Создание объявления отменено.")
        return
    
    if not color:
        bot.send_message(
            user_id,
            "❌ Пожалуйста, введите цвет:",
            reply_markup=get_back_cancel_inline_keyboard()
        )
        return
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['color'] = color
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_android_processor")
def handle_smart_android_processor(message):
    """Обработка ввода процессора Android в умном режиме"""
    user_id = message.from_user.id
    processor = message.text.strip()
    
    # Проверяем отмену
    if processor == "❌ Отмена":
        clear_ad_state(user_id)
        safe_send_message(user_id, "❌ Создание объявления отменено.")
        return
    
    if not processor:
        bot.send_message(
            user_id,
            "❌ Пожалуйста, введите модель процессора:",
            reply_markup=get_back_cancel_inline_keyboard()
        )
        return
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['processor'] = processor
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_android_color")
def handle_smart_android_color(message):
    """Обработка ввода цвета Android в умном режиме"""
    user_id = message.from_user.id
    color = message.text.strip()
    
    # Проверяем отмену
    if color == "❌ Отмена":
        clear_ad_state(user_id)
        safe_send_message(user_id, "❌ Создание объявления отменено.")
        return
    
    if not color:
        bot.send_message(
            user_id,
            "❌ Пожалуйста, введите цвет:",
            reply_markup=get_back_cancel_inline_keyboard()
        )
        return
    
    # Сохраняем данные
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    ad_data['color'] = color
    set_ad_state(user_id, "smart_next_step", ad_data)
    
    # Показываем следующий шаг
    show_smart_next_step(user_id)

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_price_usd")
def handle_smart_price_usd(message):
    """Обработка ввода цены USD в умном режиме"""
    user_id = message.from_user.id
    price_text = message.text.strip()
    
    # Проверяем отмену
    if price_text == "❌ Отмена":
        clear_ad_state(user_id)
        safe_send_message(user_id, "❌ Создание объявления отменено.")
        return
    
    try:
        price_usd = float(price_text.replace(',', '.'))
        if price_usd <= 0:
            bot.send_message(
                user_id,
                "❌ Цена должна быть больше 0. Введите снова:",
                reply_markup=get_back_cancel_inline_keyboard()
            )
            return
        
        # Сохраняем данные
        ad_step, ad_data, ad_photos = get_ad_state(user_id)
        ad_data['price_usd'] = price_usd
        set_ad_state(user_id, "smart_next_step", ad_data)
        
        # Показываем следующий шаг
        show_smart_next_step(user_id)
    except ValueError:
        bot.send_message(
            user_id,
            "❌ Пожалуйста, введите число. Например: <code>500</code>",
            parse_mode="HTML",
            reply_markup=get_back_cancel_inline_keyboard()
        )

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_price_kgs")
def handle_smart_price_kgs(message):
    """Обработка ввода цены KGS в умном режиме"""
    user_id = message.from_user.id
    price_text = message.text.strip()
    
    # Проверяем отмену
    if price_text == "❌ Отмена":
        clear_ad_state(user_id)
        safe_send_message(user_id, "❌ Создание объявления отменено.")
        return
    
    try:
        price_kgs = float(price_text.replace(',', '.'))
        if price_kgs <= 0:
            bot.send_message(
                user_id,
                "❌ Цена должна быть больше 0. Введите снова:",
                reply_markup=get_back_cancel_inline_keyboard()
            )
            return
        
        # Сохраняем данные
        ad_step, ad_data, ad_photos = get_ad_state(user_id)
        ad_data['price_kgs'] = price_kgs
        set_ad_state(user_id, "smart_next_step", ad_data)
        
        # Показываем следующий шаг
        show_smart_next_step(user_id)
    except ValueError:
        bot.send_message(
            user_id,
            "❌ Пожалуйста, введите число. Например: <code>50000</code>",
            parse_mode="HTML",
            reply_markup=get_back_cancel_inline_keyboard()
        )

@bot.message_handler(func=lambda m: get_ad_state(m.from_user.id)[0] == "smart_search_model")
def handle_smart_search_model(message):
    """Обработка ввода для поиска модели"""
    user_id = message.from_user.id
    query = message.text.strip()
    
    if not query:
        bot.send_message(user_id, "❌ Пожалуйста, введите текст для поиска.")
        return
    
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    brand = ad_data.get('brand')
    
    if not brand:
        bot.send_message(user_id, "❌ Ошибка: бренд не выбран.")
        return
    
    # Ищем модели
    found_models = suggest_models(brand, query, limit=10)
    
    if not found_models:
        text = f"🔍 <b>По запросу '{query}' ничего не найдено</b>\n\n"
        text += "Попробуйте:\n"
        text += "• Упростить запрос\n"
        text += "• Использовать цифры модели\n"
        text += "• Ввести вручную"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand")
        )
        
        bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard)
        return
    
    text = f"🔍 <b>Результаты поиска для '{query}':</b>\n\n"
    for i, model in enumerate(found_models, 1):
        text += f"{i}. {model}\n"
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for model in found_models[:8]:  # Ограничиваем 8 кнопками
        buttons.append(types.InlineKeyboardButton(model, callback_data=f"smart_model:{model}"))
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            keyboard.row(buttons[i], buttons[i+1])
        else:
            keyboard.row(buttons[i])
    
    keyboard.row(types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"))
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
    )
    
    bot.send_message(user_id, text, parse_mode="HTML", reply_markup=keyboard)

# ===== ОБРАБОТЧИКИ ФОТО =====
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

def show_ad_preview(user_id):
    """Показ предпросмотра объявления"""
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Формируем текст объявления
    preview_text = format_ad_text(ad_data, preview=True)
    
    # Проверяем дубликаты
    duplicates = check_duplicate_ads(user_id, preview_text)
    
    if duplicates:
        # Добавляем предупреждение о дубликатах
        preview_text += f"\n\n⚠️ <b>Внимание:</b> Обнаружены похожие объявления (схожесть: {duplicates[0]['similarity']}%)"
    
    # Создаем клавиатуру подтверждения
    keyboard = types.InlineKeyboardMarkup()
    if duplicates:
        keyboard.row(
            types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish_ad_with_check"),
            types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_ad")
        )
    else:
        keyboard.row(
            types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish_ad"),
            types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_ad")
        )
    
    keyboard.row(
        types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back"),
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

# ===== ПРОВЕРКА ДУБЛИКАТОВ ПЕРЕД ПУБЛИКАЦИЙ =====
@bot.callback_query_handler(func=lambda call: call.data == "publish_ad_with_check")
def publish_ad_with_check_callback(call):
    """Публикация с проверкой дубликатов"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    # Формируем текст для проверки
    final_text = format_ad_text(ad_data, preview=False)
    
    # Проверяем на запрещенную лексику
    if HAS_PROFANITY_FILTER and pf.is_profane(final_text):
        bot.answer_callback_query(
            call.id,
            "❌ Текст содержит запрещенные выражения. Отредактируйте объявление.",
            show_alert=True
        )
        return
    
    # Проверяем дубликаты
    duplicates = check_duplicate_ads(user_id, final_text)
    
    if duplicates:
        # Показываем предупреждение
        warning_text = "⚠️ <b>Обнаружены похожие объявления!</b>\n\n"
        warning_text += "Схожесть с предыдущими объявлениями:\n"
        for dup in duplicates[:2]:
            warning_text += f"• {dup['similarity']}%\n"
        warning_text += "\nВы уверены, что хотите опубликовать?"
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton("✅ Да, опубликовать", callback_data="publish_ad_confirm"),
            types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit_ad")
        )
        
        bot.edit_message_text(
            text=warning_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        # Публикуем сразу
        publish_ad_confirm_callback(call)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "publish_ad_confirm")
def publish_ad_confirm_callback(call):
    """Подтвержденная публикация после проверок"""
    # Вызываем оригинальную функцию публикации
    publish_ad_callback(call)

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
        
        set_ad_state(user_id, "smart_model", ad_data)
        
        # Показываем интерфейс выбора модели
        brand = ad_data.get('brand')
        popular_models = suggest_models(brand, limit=12)
        
        text = f"📱 <b>Выбран бренд: {brand}</b>\n\n"
        text += "Выберите модель из списка или введите вручную:\n\n"
        text += "<i>Самые популярные модели:</i>"
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        
        for i in range(0, len(popular_models), 2):
            if i + 1 < len(popular_models):
                keyboard.row(
                    types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"),
                    types.InlineKeyboardButton(popular_models[i+1], callback_data=f"smart_model:{popular_models[i+1]}")
                )
            else:
                keyboard.row(types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"))
        
        keyboard.row(types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"))
        keyboard.row(types.InlineKeyboardButton("🔍 Поиск модели", callback_data="smart_search_model"))
        
        keyboard.row(
            types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
        )
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
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
        
        set_ad_state(user_id, "smart_model", ad_data)
        
        # Показываем интерфейс выбора модели
        brand = ad_data.get('brand')
        popular_models = suggest_models(brand, limit=12)
        
        text = f"📱 <b>Выбран бренд: {brand}</b>\n\n"
        text += "Выберите модель из списка или введите вручную:\n\n"
        text += "<i>Самые популярные модели:</i>"
        
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        
        for i in range(0, len(popular_models), 2):
            if i + 1 < len(popular_models):
                keyboard.row(
                    types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"),
                    types.InlineKeyboardButton(popular_models[i+1], callback_data=f"smart_model:{popular_models[i+1]}")
                )
            else:
                keyboard.row(types.InlineKeyboardButton(popular_models[i], callback_data=f"smart_model:{popular_models[i]}"))
        
        keyboard.row(types.InlineKeyboardButton("✏️ Ввести вручную", callback_data="smart_enter_model"))
        keyboard.row(types.InlineKeyboardButton("🔍 Поиск модели", callback_data="smart_search_model"))
        
        keyboard.row(
            types.InlineKeyboardButton("🔙 Назад", callback_data="smart_back_to_brand"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad")
        )
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
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
    
    set_ad_state(user_id, "smart_price_usd", ad_data)
    
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
    model = ad_data.get('model', '')
    
    if device_type == 'iphone':
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
        
        set_ad_state(user_id, "smart_iphone_memory", ad_data)
        
        # Получаем предустановленные значения для модели
        presets = get_model_preset_suggestions(model)
        
        text = f"✅ <b>Выбрана модель: {model}</b>\n\n"
        text += "<b>Следующие шаги:</b>\n"
        text += "1. Выберите объем памяти\n"
        
        # Показываем предустановленные характеристики, если есть
        if presets:
            text += "\n<b>Обычные характеристики для этой модели:</b>\n"
            if 'memory_options' in presets:
                text += f"• Память: {', '.join(presets['memory_options'])}\n"
            if 'colors' in presets:
                text += f"• Цвета: {', '.join(presets['colors'])}\n"
        
        # Создаем клавиатуру для выбора памяти
        options = presets.get('memory_options', ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"])
        keyboard = create_memory_keyboard(options)
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # ОТПРАВЛЯЕМ ОСНОВНУЮ КЛАВИАТУРУ
        safe_send_message(
            user_id,
            f"Редактирование характеристик iPhone {model}. Начнем с выбора памяти:",
            reply_markup=get_main_keyboard()
        )
        
    else:  # Android
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
        
        set_ad_state(user_id, "smart_android_ram", ad_data)
        
        # Получаем предустановленные значения для модели
        presets = get_model_preset_suggestions(model)
        
        text = f"✅ <b>Выбрана модель: {model}</b>\n\n"
        text += "<b>Следующие шаги:</b>\n"
        text += "1. Выберите оперативную память\n"
        
        # Показываем предустановленные характеристики, если есть
        if presets:
            text += "\n<b>Обычные характеристики для этой модели:</b>\n"
            if 'ram_options' in presets:
                text += f"• ОЗУ: {', '.join(presets['ram_options'])}\n"
            if 'rom_options' in presets:
                text += f"• ПЗУ: {', '.join(presets['rom_options'])}\n"
            if 'colors' in presets:
                text += f"• Цвета: {', '.join(presets['colors'])}\n"
        
        # Создаем клавиатуру для выбора оперативной памяти
        options = presets.get('ram_options', ["4 GB", "6 GB", "8 GB", "12 GB", "16 GB"])
        keyboard = create_ram_keyboard(options)
        
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
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

# ===== ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ =====
@bot.callback_query_handler(func=lambda call: call.data == "continue_draft")
def continue_draft_callback(call):
    """Продолжение черновика"""
    user_id = call.from_user.id
    ad_step, ad_data, ad_photos = get_ad_state(user_id)
    
    if not ad_step:
        bot.answer_callback_query(call.id, "❌ Черновик не найден", show_alert=True)
        return
    
    # Продолжаем с того шага, на котором остановились
    if ad_step.startswith("smart_"):
        show_smart_next_step(user_id, call.message.chat.id, call.message.message_id)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "restart_ad")
def restart_ad_callback(call):
    """Начать заново"""
    user_id = call.from_user.id
    clear_ad_state(user_id)
    
    # Начинаем умное создание
    smart_create_ad_callback(call)
    
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
    print("🎯 ИНТЕЛЛЕКТУАЛЬНЫЕ ФУНКЦИИ:")
    print(f"✅ RapidFuzz: {'Доступен' if HAS_RAPIDFUZZ else 'Не доступен'}")
    print(f"✅ Profanity Filter: {'Доступен' if HAS_PROFANITY_FILTER else 'Не доступен'}")
    print(f"✅ Моделей в базе: {sum(len(models) for models in SMARTPHONE_MODELS.values())}")
    print(f"✅ Пресетов моделей: {len(MODEL_PRESETS)}")
    print("=" * 60)
    print("📢 Основные команды:")
    print("• /start - Начать работу с выбором режима создания")
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
    print("🤖 ИНТЕЛЛЕКТУАЛЬНЫЕ ФУНКЦИИ:")
    print("• Автоподсказки моделей смартфонов")
    print("• Предсказание следующих шагов")
    print("• Проверка на дубликаты объявлений")
    print("• Валидация и фильтрация ввода")
    print("• Умная кнопка 'Назад' с сохранением состояния")
    print("• Сохранение черновиков")
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
        time.sleep(30)
        os.execv(sys.executable, ['python'] + sys.argv)