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
ADMIN_CEO_ID = os.getenv("7577716374", "7577716374")
ADMIN_SUPPORT_ID = os.getenv("6764228404", "6764228404")

def is_admin(user_id, username=None):
    """Проверяет, является ли пользователь администратором"""
    user_id_str = str(user_id)
    if username:
        if username in [ADMIN_CEO_ID, ADMIN_SUPPORT_ID]:
            return True
    return user_id_str in [ADMIN_CEO_ID, ADMIN_SUPPORT_ID]

# ===== СТРУКТУРЫ ДАННЫХ =====
class DataStorage:
    """Управление всеми данными бота"""
    def __init__(self):
        self.users = OrderedDict()
        self.states = OrderedDict()
        self.invoices = OrderedDict()
        self.premium_users = set()
        self.support_messages = OrderedDict()
        self.contacts = OrderedDict()
        self.message_cache = OrderedDict()
        self.user_invoices = OrderedDict()
        self.admin_reply_context = OrderedDict()
        self.admin_messages = OrderedDict()
        self.ads_in_progress = OrderedDict()  # Для умных объявлений
        self.published_ads = OrderedDict()    # Опубликованные объявления
        self.ad_stats = OrderedDict()         # Статистика по объявлениям
        
    def cleanup_old_data(self, max_age_hours=24):
        """Очистка старых данных"""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        # Очистка старых состояний
        for user_id, state in list(self.states.items()):
            if state.get('last_activity', datetime.min) < cutoff:
                del self.states[user_id]
        
        # Очистка старых объявлений в процессе (старше 1 часа)
        ad_cutoff = datetime.now() - timedelta(hours=1)
        for user_id, ad_data in list(self.ads_in_progress.items()):
            if ad_data.get('last_activity', datetime.min) < ad_cutoff:
                del self.ads_in_progress[user_id]

storage = DataStorage()

# ===== УМНАЯ СИСТЕМА СОЗДАНИЯ ОБЪЯВЛЕНИЙ =====
class SmartAdCreator:
    """Интеллектуальный создатель объявлений"""
    
    def __init__(self, user_id):
        self.user_id = user_id
        self.device_type = None
        self.current_step = None
        self.ad_data = {}
        self.photos = []
        self.step_history = []
        self.errors_count = {}
        self.start_time = datetime.now()
        self.last_activity = datetime.now()
        
        # База знаний для рекомендаций
        self.market_prices = {
            'iPhone': {
                'iPhone 11': {'min': 300, 'max': 400},
                'iPhone 12': {'min': 400, 'max': 550},
                'iPhone 13': {'min': 500, 'max': 700},
                'iPhone 14': {'min': 600, 'max': 800},
                'iPhone 15': {'min': 700, 'max': 1000},
            },
            'Samsung': {
                'Galaxy S21': {'min': 300, 'max': 450},
                'Galaxy S22': {'min': 400, 'max': 600},
                'Galaxy S23': {'min': 500, 'max': 750},
            }
        }
        
        # Популярные модели для автодополнения
        self.popular_models = {
            'Apple': ['iPhone 11', 'iPhone 12', 'iPhone 13', 'iPhone 14', 'iPhone 15', 'iPhone 11 Pro', 'iPhone 12 Pro', 'iPhone 13 Pro', 'iPhone 14 Pro', 'iPhone 15 Pro'],
            'Samsung': ['Galaxy S21', 'Galaxy S22', 'Galaxy S23', 'Galaxy A52', 'Galaxy A53', 'Galaxy A73', 'Galaxy Z Flip', 'Galaxy Z Fold'],
            'Xiaomi': ['Redmi Note 10', 'Redmi Note 11', 'Redmi Note 12', 'Mi 11', 'Mi 12', 'Poco X3', 'Poco X4'],
            'Huawei': ['P30', 'P40', 'P50', 'Mate 30', 'Mate 40', 'Nova 9'],
        }
        
    def set_device_type(self, brand):
        """Автоматическое определение типа устройства по бренду"""
        if brand == 'Apple':
            self.device_type = 'iphone'
        elif brand in ['Samsung', 'Xiaomi', 'Huawei', 'Google', 'OnePlus', 'Oppo', 'Vivo', 'Realme', 'Nokia', 'Sony', 'Asus']:
            self.device_type = 'android'
        else:
            self.device_type = 'other'
        
        self.ad_data['brand'] = brand
        self.ad_data['device_type'] = self.device_type
        return self.device_type
    
    def get_next_step(self, current_step=None):
        """Интеллектуальное определение следующего шага"""
        if not self.device_type:
            return 'choose_brand'
        
        if self.device_type == 'iphone':
            steps = [
                'choose_brand',
                'enter_iphone_model',
                'choose_iphone_memory',
                'choose_condition',
                'enter_battery',
                'enter_color',
                'choose_package',
                'enter_price_usd',
                'enter_price_kgs',
                'choose_contact',
                'upload_photos',
                'preview'
            ]
        else:
            steps = [
                'choose_brand',
                'enter_android_model',
                'choose_ram',
                'choose_rom',
                'enter_processor',
                'choose_condition',
                'choose_battery_state',
                'enter_color',
                'enter_price_usd',
                'enter_price_kgs',
                'choose_contact',
                'upload_photos',
                'preview'
            ]
        
        if current_step:
            current_index = steps.index(current_step) if current_step in steps else -1
            if current_index < len(steps) - 1:
                return steps[current_index + 1]
        
        return steps[0]
    
    def validate_input(self, field_type, value):
        """Интеллектуальная валидация ввода"""
        self.errors_count[field_type] = self.errors_count.get(field_type, 0) + 1
        
        if field_type == 'model':
            if len(value.strip()) < 3:
                return False, "❌ Слишком короткая модель. Введите не менее 3 символов."
            return True, ""
        
        elif field_type == 'price_usd':
            try:
                price = float(value)
                if price < 10:
                    return False, "❌ Цена слишком низкая. Минимальная цена 10 USD."
                if price > 10000:
                    return False, "❌ Цена слишком высокая. Максимальная цена 10000 USD."
                
                # Проверка рыночной цены
                brand = self.ad_data.get('brand')
                model = self.ad_data.get('model', '')
                if brand in self.market_prices:
                    for model_pattern, price_range in self.market_prices[brand].items():
                        if model_pattern.lower() in model.lower():
                            if price < price_range['min']:
                                return False, f"⚠️ Цена ниже рыночной ({price_range['min']}-{price_range['max']} USD)"
                            if price > price_range['max'] * 1.5:
                                return False, f"⚠️ Цена выше рыночной ({price_range['min']}-{price_range['max']} USD)"
                
                return True, ""
            except ValueError:
                return False, "❌ Введите число (например: 500)"
        
        elif field_type == 'battery_iphone':
            try:
                battery = int(value)
                if battery < 70:
                    return False, "❌ Аккумулятор должен быть от 70% для iPhone"
                if battery > 100:
                    return False, "❌ Аккумулятор не может быть больше 100%"
                return True, ""
            except ValueError:
                return False, "❌ Введите число от 70 до 100"
        
        elif field_type == 'contact':
            if value.startswith('@'):
                return True, ""
            elif re.match(r'^\+?[1-9]\d{1,14}$', value.replace(' ', '')):
                return True, ""
            else:
                return False, "❌ Введите номер телефона (например: +996555123456) или @username"
        
        return True, ""
    
    def generate_smart_hint(self, step):
        """Генерация умных подсказок"""
        hints = {
            'enter_iphone_model': "📱 <b>Примеры моделей:</b>\n• iPhone 12 Pro\n• iPhone 13 Pro Max\n• iPhone 14 Plus\n• iPhone 15 Pro\n\n💡 <i>Укажите точную модель для лучшего отклика</i>",
            'enter_android_model': "📱 <b>Примеры моделей:</b>\n• Galaxy S23 Ultra\n• Redmi Note 12 Pro\n• Pixel 7 Pro\n• OnePlus 11\n\n💡 <i>Чем точнее модель, тем быстрее продажа</i>",
            'enter_price_usd': "💰 <b>Советы по ценообразованию:</b>\n\n• Сравните цены на аналогичные модели\n• Учтите состояние и комплектацию\n• Оставьте место для торга (10-15%)\n\n💡 <i>Адекватная цена = быстрая продажа</i>",
            'enter_battery': "🔋 <b>Состояние аккумулятора iPhone:</b>\n\n• 100% = Новый или недавно заменен\n• 90-99% = Отличное состояние\n• 80-89% = Хорошее, хватает на день\n• 70-79% = Может требовать замены\n\n💡 <i>Честность повышает доверие</i>",
            'choose_condition': "📊 <b>Критерии состояния:</b>\n\n• <b>Новый</b> - с гарантией, в коробке\n• <b>Отличное</b> - нет царапин, как новый\n• <b>Хорошее</b> - мелкие следы использования\n• <b>Удовлетворительное</b> - видны следы использования\n\n💡 <i>Честная оценка = меньше вопросов</i>",
            'upload_photos': "📸 <b>Советы по фото:</b>\n\n1. Первое фото - лицевая сторона (экран включен)\n2. Второе - задняя панель\n3. Третье - боковые грани\n4. Четвертое - комплектация\n\n💡 <i>Хорошие фото = в 2 раза больше просмотров</i>"
        }
        
        return hints.get(step, "")
    
    def get_adaptive_keyboard(self, step):
        """Создание адаптивных клавиатур"""
        keyboard = None
        
        if step == 'choose_brand':
            keyboard = types.InlineKeyboardMarkup(row_width=4)
            brands = [
                "Apple", "Samsung", "Xiaomi", "Redmi",
                "POCO", "Realme", "Oppo", "Vivo",
                "Huawei", "Honor", "Google Pixel", "OnePlus",
                "Nokia", "Sony", "Asus", "Другое"
            ]
            buttons = []
            for brand in brands:
                buttons.append(types.InlineKeyboardButton(brand, callback_data=f"smart_brand:{brand}"))
            
            for i in range(0, len(buttons), 4):
                keyboard.row(*buttons[i:i+4])
        
        elif step == 'choose_iphone_memory':
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            memories = ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"]
            buttons = [types.InlineKeyboardButton(mem, callback_data=f"smart_memory:{mem}") for mem in memories]
            for i in range(0, len(buttons), 2):
                keyboard.row(*buttons[i:i+2])
        
        elif step == 'choose_condition':
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            conditions = ["Новый", "Отличное", "Хорошее", "Удовлетворительное"]
            buttons = [types.InlineKeyboardButton(f"{cond}", callback_data=f"smart_condition:{cond}") for cond in conditions]
            for i in range(0, len(buttons), 2):
                keyboard.row(*buttons[i:i+2])
        
        elif step == 'choose_package':
            keyboard = types.InlineKeyboardMarkup(row_width=1)
            packages = ["Полный комплект", "Только телефон", "Без коробки"]
            buttons = [types.InlineKeyboardButton(pkg, callback_data=f"smart_package:{pkg}") for pkg in packages]
            for btn in buttons:
                keyboard.row(btn)
        
        elif step == 'choose_ram':
            keyboard = types.InlineKeyboardMarkup(row_width=3)
            ram_options = ["2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "12 GB", "16 GB"]
            buttons = [types.InlineKeyboardButton(ram, callback_data=f"smart_ram:{ram}") for ram in ram_options]
            for i in range(0, len(buttons), 3):
                keyboard.row(*buttons[i:i+3])
        
        elif step == 'choose_rom':
            keyboard = types.InlineKeyboardMarkup(row_width=3)
            rom_options = ["32 GB", "64 GB", "128 GB", "256 GB", "512 GB"]
            buttons = [types.InlineKeyboardButton(rom, callback_data=f"smart_rom:{rom}") for rom in rom_options]
            for i in range(0, len(buttons), 3):
                keyboard.row(*buttons[i:i+3])
        
        elif step == 'choose_battery_state':
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            battery_states = ["Отличный", "Нормальный", "Требует замены"]
            buttons = [types.InlineKeyboardButton(state, callback_data=f"smart_battery_state:{state}") for state in battery_states]
            for i in range(0, len(buttons), 2):
                keyboard.row(*buttons[i:i+2])
        
        elif step == 'choose_contact':
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            keyboard.add(
                types.KeyboardButton("📞 Поделиться номером", request_contact=True),
                types.KeyboardButton("💬 Связь через Telegram")
            )
        
        return keyboard
    
    def get_model_suggestions(self, brand):
        """Получение предложений моделей для автодополнения"""
        return self.popular_models.get(brand, [])
    
    def optimize_ad_text(self):
        """Автоматическая оптимизация текста объявления"""
        device_type = self.ad_data.get('device_type', 'android')
        brand = self.ad_data.get('brand', '')
        model = self.ad_data.get('model', '')
        
        # Генерация хэштегов
        hashtags = []
        
        if brand:
            hashtags.append(f"#{brand.replace(' ', '')}")
        
        if model:
            model_clean = model.replace(' ', '').replace('-', '')
            hashtags.append(f"#{model_clean}")
        
        if device_type == 'iphone':
            memory = self.ad_data.get('memory', '')
            if memory:
                hashtags.append(f"#{memory.replace(' ', '')}")
        
        # Добавление общих хэштегов
        hashtags.extend(["#Смартфон", "#Продажа", "#БУ", "#Телефон"])
        
        # Форматирование текста
        if device_type == 'iphone':
            text = f"""
📱 <b>Apple iPhone {model}</b>

📊 <b>Характеристики:</b>
• Память: {self.ad_data.get('memory', 'Не указано')}
• Состояние: {self.ad_data.get('condition', 'Не указано')}
• Аккумулятор: {self.ad_data.get('battery', 'Не указано')}%
• Цвет: {self.ad_data.get('color', 'Не указан')}
• Комплектация: {self.ad_data.get('package', 'Не указана')}

💰 <b>Цена:</b>
• {float(self.ad_data.get('price_usd', 0)):.0f} USD
• {float(self.ad_data.get('price_kgs', 0)):.0f} KGS

👤 <b>Контакты:</b>
• {self.ad_data.get('contact', 'Не указаны')}

🕐 <i>Опубликовано: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>

{' '.join(hashtags[:5])}
"""
        else:
            text = f"""
📱 <b>{brand} {model}</b>

📊 <b>Характеристики:</b>
• ОЗУ: {self.ad_data.get('ram', 'Не указано')}
• ПЗУ: {self.ad_data.get('rom', 'Не указано')}
• Процессор: {self.ad_data.get('processor', 'Не указан')}
• Состояние: {self.ad_data.get('condition', 'Не указано')}
• Аккумулятор: {self.ad_data.get('battery_state', 'Не указано')}
• Цвет: {self.ad_data.get('color', 'Не указан')}

💰 <b>Цена:</b>
• {float(self.ad_data.get('price_usd', 0)):.0f} USD
• {float(self.ad_data.get('price_kgs', 0)):.0f} KGS

👤 <b>Контакты:</b>
• {self.ad_data.get('contact', 'Не указаны')}

🕐 <i>Опубликовано: {datetime.now().strftime('%d.%m.%Y %H:%M')}</i>

{' '.join(hashtags[:5])}
"""
        
        return text
    
    def get_photo_recommendations(self):
        """Рекомендации по фото"""
        device_type = self.ad_data.get('device_type', 'android')
        
        if device_type == 'iphone':
            return [
                "1. 📱 Лицевая сторона с включенным экраном",
                "2. 🔋 Задняя панель (покажите цвет)",
                "3. 🔍 Боковые грани (особенно углы)",
                "4. 📦 Комплектация (зарядка, наушники)"
            ]
        else:
            return [
                "1. 📱 Передняя часть с работающим экраном",
                "2. 🎨 Задняя крышка (покажите дизайн)",
                "3. ⚙️ Боковые кнопки и разъемы",
                "4. 🔋 Комплектация и аксессуары"
            ]
    
    def calculate_completion_percentage(self):
        """Расчет процента завершенности"""
        total_fields = len(self.ad_data)
        filled_fields = sum(1 for v in self.ad_data.values() if v)
        photos_count = len(self.photos)
        
        if photos_count >= 2:
            filled_fields += 1
        if photos_count >= 4:
            filled_fields += 1
        
        max_fields = 12  # Максимальное количество полей
        return min(100, int((filled_fields / max_fields) * 100))

# ===== УМНАЯ СИСТЕМА ПОДДЕРЖКИ =====
class SmartSupportSystem:
    """Интеллектуальная система поддержки"""
    
    def __init__(self):
        self.tickets = OrderedDict()
        self.user_last_tickets = OrderedDict()
        self.categories = {
            'payment': ['оплат', 'деньг', 'средств', 'платёж', 'платеж', 'донат', 'premium', 'премиум'],
            'technical': ['ошибк', 'баг', 'глюк', 'не работ', 'сбой', 'техническ', 'видео', 'файл'],
            'suggestion': ['предложен', 'идея', 'улучшен', 'функц', 'хочу', 'можно', 'добав'],
            'general': ['как', 'что', 'вопрос', 'интерес', 'помощь', 'подскаж']
        }
        self.ticket_counter = 0
        
    def _generate_ticket_id(self):
        self.ticket_counter += 1
        return f"TKT{self.ticket_counter:06d}"
    
    def _categorize_text(self, text):
        text_lower = text.lower()
        for category, keywords in self.categories.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return category
        return 'other'
    
    def _find_duplicate_tickets(self, user_id, text):
        duplicates = []
        if user_id in self.user_last_tickets:
            for ticket_id in self.user_last_tickets[user_id][-5:]:
                ticket = self.tickets.get(ticket_id)
                if ticket and ticket['status'] in ['new', 'pending']:
                    ticket_text = ticket['messages'][0]['text'].lower()
                    new_text = text.lower()
                    
                    ticket_words = set(re.findall(r'\b\w{4,}\b', ticket_text))
                    new_words = set(re.findall(r'\b\w{4,}\b', new_text))
                    common_words = ticket_words.intersection(new_words)
                    
                    if len(common_words) >= 3:
                        duplicates.append(ticket)
        
        return duplicates
    
    def create_ticket(self, user_id, username, first_name, last_name, text):
        duplicates = self._find_duplicate_tickets(user_id, text)
        category = self._categorize_text(text)
        ticket_id = self._generate_ticket_id()
        
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
        
        self.tickets[ticket_id] = ticket
        
        if user_id not in self.user_last_tickets:
            self.user_last_tickets[user_id] = []
        self.user_last_tickets[user_id].append(ticket_id)
        
        logger.info(f"Создан тикет {ticket_id} для пользователя {user_id}. Категория: {category}")
        
        return ticket, duplicates
    
    def add_message(self, ticket_id, sender, text, action=None):
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
                'details': text[:100]
            })
        
        ticket['updated_at'] = datetime.now()
        
        logger.info(f"Добавлено сообщение в тикет {ticket_id} от {sender}")
        return True
    
    def update_status(self, ticket_id, status, admin_id=None):
        if ticket_id not in self.tickets:
            return False
        
        ticket = self.tickets[ticket_id]
        old_status = ticket['status']
        ticket['status'] = status
        ticket['updated_at'] = datetime.now()
        
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
        return self.tickets.get(ticket_id)
    
    def get_user_tickets(self, user_id, limit=10):
        if user_id not in self.user_last_tickets:
            return []
        
        user_tickets = []
        for ticket_id in reversed(self.user_last_tickets[user_id][-limit:]):
            ticket = self.tickets.get(ticket_id)
            if ticket:
                user_tickets.append(ticket)
        
        return user_tickets

# Инициализация систем
smart_support = SmartSupportSystem()

# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2,
        one_time_keyboard=False
    )
    keyboard.add(
        types.KeyboardButton("📖 FAQ"),
        types.KeyboardButton("💎 Донат"),
        types.KeyboardButton("📞 Поддержка")
    )
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
    """Inline-клавиатура для администратора"""
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    keyboard.add(
        types.InlineKeyboardButton("📝 Ответить", callback_data=f"admin_reply:{user_id}:{ticket_id}"),
        types.InlineKeyboardButton("✅ Решено", callback_data=f"admin_solved:{user_id}:{ticket_id}"),
        types.InlineKeyboardButton("⏳ В работе", callback_data=f"admin_pending:{user_id}:{ticket_id}")
    )
    keyboard.row(types.InlineKeyboardButton("📊 История тикетов", callback_data=f"admin_history:{user_id}"))
    return keyboard

# ===== ИНИЦИАЛИЗАЦИЯ БОТА =====
try:
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o")
    CRYPTO_BOT_API_KEY = os.getenv("CRYPTO_BOT_API_KEY", "498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy")
    CHANNEL_ID = os.getenv("CHANNEL_ID", "@FonZoneKg")
    SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "@FONZONE_CL")
    
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
    
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
    """Безопасная отправка сообщения"""
    try:
        if 'reply_markup' not in kwargs:
            kwargs['reply_markup'] = get_main_keyboard()
        
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

def reset_user_state(user_id):
    """Сброс состояния пользователя"""
    if user_id in storage.states:
        del storage.states[user_id]
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
        storage.states[user_id] = {
            'state': state_name,
            'data': data or {},
            'timestamp': datetime.now(),
            'last_activity': datetime.now()
        }
        logger.info(f"Установлено состояние {state_name} для пользователя {user_id}")
    
    @staticmethod
    def get_state(user_id):
        return storage.states.get(user_id, {}).get('state')
    
    @staticmethod
    def get_data(user_id, key=None):
        state = storage.states.get(user_id, {})
        if key:
            return state.get('data', {}).get(key)
        return state.get('data', {})

# ===== CRYPTOBOT API =====
class CryptoBotAPI:
    """Интерфейс для работы с CryptoBot API"""
    
    @staticmethod
    def create_invoice(amount, currency="USDT", description="", payload=""):
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
                
                storage.invoices[invoice_id] = {
                    "user_id": payload,
                    "amount": amount,
                    "currency": currency,
                    "status": "active",
                    "created_at": datetime.now(),
                    "pay_url": invoice["pay_url"],
                    "invoice_data": invoice
                }
                
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

# ===== ПРОВЕРКА ПЛАТЕЖЕЙ =====
def payment_checker_loop():
    """Фоновая проверка статуса платежей"""
    logger.info("Запущен фоновый процесс проверки платежей")
    
    while True:
        try:
            current_time = datetime.now()
            
            for invoice_id, invoice_data in list(storage.invoices.items()):
                try:
                    if (current_time - invoice_data.get("created_at", current_time)).total_seconds() > 86400:
                        continue
                    
                    if invoice_data.get("status") == "active":
                        status = CryptoBotAPI.get_invoice_status(invoice_id)
                        
                        if status:
                            invoice_data["status"] = status
                            
                            if status == "paid":
                                user_id = invoice_data.get("user_id")
                                amount = invoice_data.get("amount", 0)
                                
                                if user_id:
                                    if amount >= 3:
                                        storage.premium_users.add(user_id)
                                        
                                        if user_id in storage.users:
                                            storage.users[user_id]["is_premium"] = True
                                            storage.users[user_id]["premium_until"] = (
                                                datetime.now() + timedelta(days=PREMIUM_DURATION_DAYS)
                                            ).isoformat()
                                        
                                        try:
                                            bot.send_message(
                                                user_id,
                                                "🎉 <b>Поздравляем!</b>\n\nВаш PREMIUM статус успешно активирован!",
                                                reply_markup=get_main_keyboard()
                                            )
                                            logger.info(f"Активирован PREMIUM для пользователя {user_id}")
                                        except Exception as e:
                                            logger.error(f"Ошибка уведомления о премиуме: {e}")
                                    else:
                                        try:
                                            bot.send_message(
                                                user_id,
                                                "❤️ <b>Спасибо за поддержку!</b>\n\nВаш донат помогает развивать бота.",
                                                reply_markup=get_main_keyboard()
                                            )
                                            logger.info(f"Поддержка от пользователя {user_id}: {amount} {invoice_data.get('currency')}")
                                        except Exception as e:
                                            logger.error(f"Ошибка благодарности за донат: {e}")
                                    
                                    invoice_data["paid_at"] = datetime.now()
                
                except Exception as e:
                    logger.error(f"Ошибка проверки инвойса {invoice_id}: {e}")
            
            time.sleep(PAYMENT_CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Критическая ошибка в проверке платежей: {e}")
            time.sleep(60)

# Запускаем фоновую проверку
payment_thread = threading.Thread(target=payment_checker_loop, daemon=True)
payment_thread.start()

# ===== ИНТЕЛЛЕКТУАЛЬНАЯ СИСТЕМА СОЗДАНИЯ ОБЪЯВЛЕНИЙ =====

@bot.message_handler(commands=['start'])
def start_command_with_ad_button(message):
    """Обработка команды /start с интегрированной кнопкой создания объявления"""
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
            "premium_until": None,
            "ads_created": 0,
            "last_ad_date": None
        }
        logger.info(f"Новый пользователь: {user_id} ({user_name})")
    
    # Сбрасываем состояние пользователя
    reset_user_state(user_id)
    
    # Приветственный текст
    welcome_text = """<b>Добро пожаловать в FonZone 📱</b>
Платформа, созданная для комфортного размещения объявлений о смартфонах.

✅ Быстрое добавление  
✅ Понятный интерфейс  
✅ Удобный формат

Всё, чтобы подать объявление без лишних сложностей!"""
    
    # Создаем inline-клавиатуру с кнопкой создания объявления
    inline_keyboard = types.InlineKeyboardMarkup()
    if user_id in storage.premium_users:
        inline_keyboard.add(types.InlineKeyboardButton("🌟 Создать объявление", callback_data="smart_create_ad"))
    else:
        inline_keyboard.add(types.InlineKeyboardButton("➕ Создать объявление", callback_data="smart_create_ad"))
    
    try:
        video_path = "welcome.mp4"
        if os.path.exists(video_path):
            # Отправляем видео с inline-кнопкой
            with open(video_path, 'rb') as video:
                bot.send_video(
                    user_id, 
                    video, 
                    caption=welcome_text, 
                    parse_mode="HTML",
                    reply_markup=inline_keyboard
                )
            logger.info(f"Отправлено видео приветствия пользователю {user_id}")
        else:
            # Отправляем текст с inline-кнопкой
            bot.send_message(
                user_id, 
                welcome_text, 
                parse_mode="HTML",
                reply_markup=inline_keyboard
            )
            logger.warning(f"Видеофайл {video_path} не найден, отправлен текст")
    except Exception as e:
        logger.error(f"Ошибка отправки приветствия: {e}")
        bot.send_message(
            user_id, 
            welcome_text, 
            parse_mode="HTML",
            reply_markup=inline_keyboard
        )
    
    # Отправляем основную клавиатуру отдельным сообщением
    try:
        bot.send_message(
            user_id,
            "👇 <b>Основное меню:</b>",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки основной клавиатуры: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "smart_create_ad")
def smart_create_ad_callback(call):
    """Начало интеллектуального создания объявления"""
    user_id = call.from_user.id
    
    # Проверяем, есть ли уже объявление в процессе
    if user_id in storage.ads_in_progress:
        ad_creator = storage.ads_in_progress[user_id]
        
        # Предлагаем продолжить или начать заново
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("↩️ Продолжить", callback_data="continue_ad"),
            types.InlineKeyboardButton("🔄 Начать заново", callback_data="restart_ad")
        )
        keyboard.row(types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_ad"))
        
        completion = ad_creator.calculate_completion_percentage()
        bot.edit_message_text(
            text=f"📝 <b>У вас есть незавершенное объявление</b>\n\n"
                 f"Завершено: {completion}%\n"
                 f"Начато: {ad_creator.start_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                 f"Хотите продолжить или начать новое объявление?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return
    
    # Создаем новый умный создатель объявлений
    ad_creator = SmartAdCreator(user_id)
    storage.ads_in_progress[user_id] = ad_creator
    
    # Начинаем с выбора бренда
    ask_brand_question(call, ad_creator)

def ask_brand_question(call, ad_creator):
    """Задаем вопрос о выборе бренда"""
    keyboard = ad_creator.get_adaptive_keyboard('choose_brand')
    
    text = "📱 <b>Выберите бренд смартфона:</b>\n\n"
    text += "Бот автоматически определит тип устройства:\n"
    text += "• Apple → iPhone\n"
    text += "• Другие бренды → Android\n\n"
    text += "💡 <i>Выбор бренда определит дальнейшие вопросы</i>"
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except:
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_brand:'))
def smart_brand_callback(call):
    """Обработка выбора бренда"""
    user_id = call.from_user.id
    
    if user_id not in storage.ads_in_progress:
        bot.answer_callback_query(call.id, "❌ Сессия создания объявления устарела. Начните заново.", show_alert=True)
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    brand = call.data.split(':')[1]
    
    # Автоматически определяем тип устройства
    device_type = ad_creator.set_device_type(brand)
    
    # Обновляем последнюю активность
    ad_creator.last_activity = datetime.now()
    
    # Отправляем подтверждение
    device_emoji = "📱" if device_type == 'iphone' else "🤖"
    device_name = "iPhone" if device_type == 'iphone' else "Android"
    
    bot.edit_message_text(
        text=f"{device_emoji} <b>Выбран {brand} → {device_name}</b>\n\n"
             f"💡 Бот адаптирует вопросы под {device_name}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML"
    )
    
    # Переходим к следующему шагу
    next_step = ad_creator.get_next_step('choose_brand')
    ask_next_question(call.message.chat.id, user_id, next_step)

def ask_next_question(chat_id, user_id, step):
    """Задаем следующий вопрос"""
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    ad_creator.current_step = step
    ad_creator.last_activity = datetime.now()
    
    # Получаем адаптивную клавиатуру
    keyboard = ad_creator.get_adaptive_keyboard(step)
    
    # Генерируем вопрос и подсказку
    questions = {
        'enter_iphone_model': "📱 <b>Введите модель iPhone:</b>",
        'enter_android_model': "📱 <b>Введите модель смартфона:</b>",
        'choose_iphone_memory': "💾 <b>Выберите объем памяти:</b>",
        'choose_condition': "📊 <b>Выберите состояние телефона:</b>",
        'enter_battery': "🔋 <b>Введите состояние аккумулятора (%):</b>\n<i>Число от 70 до 100</i>",
        'enter_color': "🎨 <b>Введите цвет телефона:</b>",
        'choose_package': "📦 <b>Выберите комплектацию:</b>",
        'choose_ram': "🧠 <b>Выберите оперативную память (RAM):</b>",
        'choose_rom': "💾 <b>Выберите встроенную память (ROM):</b>",
        'enter_processor': "⚡️ <b>Введите модель процессора:</b>",
        'choose_battery_state': "🔋 <b>Выберите состояние аккумулятора:</b>",
        'enter_price_usd': "💰 <b>Введите цену в долларах (USD):</b>",
        'enter_price_kgs': "💰 <b>Введите цену в сомах (KGS):</b>",
        'choose_contact': "📞 <b>Выберите способ связи:</b>",
        'upload_photos': "📸 <b>Загрузите фото телефона (2-4 фото):</b>"
    }
    
    text = questions.get(step, "Продолжим создание объявления?")
    
    # Добавляем умную подсказку
    hint = ad_creator.generate_smart_hint(step)
    if hint:
        text += f"\n\n{hint}"
    
    # Добавляем прогресс
    completion = ad_creator.calculate_completion_percentage()
    text += f"\n\n📊 <i>Завершено: {completion}%</i>"
    
    # Для шага ввода модели добавляем предложения
    if step in ['enter_iphone_model', 'enter_android_model']:
        brand = ad_creator.ad_data.get('brand', '')
        suggestions = ad_creator.get_model_suggestions(brand)
        if suggestions:
            text += f"\n\n💡 <b>Популярные модели {brand}:</b>\n"
            for i, model in enumerate(suggestions[:5], 1):
                text += f"{i}. {model}\n"
    
    # Отправляем сообщение
    if keyboard:
        bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=get_cancel_keyboard())

# Обработчики для разных шагов создания объявления
@bot.callback_query_handler(func=lambda call: call.data.startswith('smart_'))
def smart_step_callback(call):
    """Обработка шагов с выбором из клавиатуры"""
    user_id = call.from_user.id
    
    if user_id not in storage.ads_in_progress:
        bot.answer_callback_query(call.id, "❌ Сессия устарела. Начните заново.", show_alert=True)
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    data = call.data.split(':')
    step_type = data[0]
    value = data[1] if len(data) > 1 else ""
    
    # Определяем тип шага
    step_mapping = {
        'smart_memory': ('memory', 'enter_iphone_model'),
        'smart_condition': ('condition', 'choose_iphone_memory'),
        'smart_package': ('package', 'enter_color'),
        'smart_ram': ('ram', 'enter_android_model'),
        'smart_rom': ('rom', 'choose_ram'),
        'smart_battery_state': ('battery_state', 'choose_condition')
    }
    
    if step_type in step_mapping:
        field, previous_step = step_mapping[step_type]
        ad_creator.ad_data[field] = value
        
        # Обновляем последнюю активность
        ad_creator.last_activity = datetime.now()
        
        # Подтверждаем выбор
        bot.answer_callback_query(call.id, f"✅ Выбрано: {value}")
        
        # Переходим к следующему шагу
        next_step = ad_creator.get_next_step(previous_step)
        ask_next_question(call.message.chat.id, user_id, next_step)

@bot.message_handler(func=lambda m: m.content_type == 'text' and m.text != "❌ Отмена")
def handle_text_input(message):
    """Обработка текстового ввода для создания объявления"""
    user_id = message.from_user.id
    
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    current_step = ad_creator.current_step
    
    if not current_step:
        return
    
    # Определяем тип поля для валидации
    field_type_map = {
        'enter_iphone_model': 'model',
        'enter_android_model': 'model',
        'enter_battery': 'battery_iphone',
        'enter_color': 'color',
        'enter_processor': 'processor',
        'enter_price_usd': 'price_usd',
        'enter_price_kgs': 'price_kgs'
    }
    
    field_type = field_type_map.get(current_step)
    if not field_type:
        return
    
    # Валидация ввода
    is_valid, error_msg = ad_creator.validate_input(field_type, message.text)
    
    if not is_valid:
        bot.send_message(user_id, error_msg, reply_markup=get_cancel_keyboard())
        return
    
    # Сохраняем данные
    field_name_map = {
        'enter_iphone_model': 'model',
        'enter_android_model': 'model',
        'enter_battery': 'battery',
        'enter_color': 'color',
        'enter_processor': 'processor',
        'enter_price_usd': 'price_usd',
        'enter_price_kgs': 'price_kgs'
    }
    
    field_name = field_name_map.get(current_step)
    if field_name:
        ad_creator.ad_data[field_name] = message.text
    
    # Обновляем последнюю активность
    ad_creator.last_activity = datetime.now()
    
    # Переходим к следующему шагу
    next_step = ad_creator.get_next_step(current_step)
    ask_next_question(message.chat.id, user_id, next_step)

@bot.message_handler(content_types=['contact'])
def handle_contact_input(message):
    """Обработка контакта"""
    user_id = message.from_user.id
    
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    if ad_creator.current_step != 'choose_contact':
        return
    
    # Сохраняем контакт
    phone = message.contact.phone_number
    ad_creator.ad_data['contact'] = phone
    ad_creator.ad_data['contact_type'] = 'phone'
    
    bot.send_message(
        user_id,
        f"✅ Номер сохранен: {phone}\n\n"
        f"📞 Покупатели смогут связаться с вами по этому номеру.",
        reply_markup=get_cancel_keyboard()
    )
    
    # Переходим к загрузке фото
    next_step = 'upload_photos'
    ask_next_question(message.chat.id, user_id, next_step)

@bot.message_handler(func=lambda m: m.text == "💬 Связь через Telegram")
def handle_telegram_contact(message):
    """Обработка выбора связи через Telegram"""
    user_id = message.from_user.id
    
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    if ad_creator.current_step != 'choose_contact':
        return
    
    # Сохраняем контакт
    username = message.from_user.username
    if username:
        contact = f"@{username}"
    else:
        contact = f"https://t.me/{message.from_user.first_name}"
    
    ad_creator.ad_data['contact'] = contact
    ad_creator.ad_data['contact_type'] = 'telegram'
    
    bot.send_message(
        user_id,
        f"✅ Контакт сохранен: {contact}\n\n"
        f"📞 Покупатели смогут связаться с вами в Telegram.",
        reply_markup=get_cancel_keyboard()
    )
    
    # Переходим к загрузке фото
    next_step = 'upload_photos'
    ask_next_question(message.chat.id, user_id, next_step)

@bot.message_handler(content_types=['photo'], func=lambda m: m.chat.id in storage.ads_in_progress)
def handle_photo_upload(message):
    """Обработка загрузки фото"""
    user_id = message.from_user.id
    
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    if ad_creator.current_step != 'upload_photos':
        return
    
    # Сохраняем фото
    photo_id = message.photo[-1].file_id
    ad_creator.photos.append(photo_id)
    
    # Обновляем последнюю активность
    ad_creator.last_activity = datetime.now()
    
    # Отправляем подтверждение
    count = len(ad_creator.photos)
    
    if count < 2:
        bot.send_message(
            user_id,
            f"✅ Фото #{count} загружено.\n"
            f"Нужно еще минимум {2 - count} фото.\n\n"
            f"💡 <i>Рекомендации по фото:</i>\n"
            f"1. 📱 Лицевая сторона с включенным экраном\n"
            f"2. 🔋 Задняя панель (покажите цвет)\n"
            f"3. 🔍 Боковые грани (особенно углы)\n"
            f"4. 📦 Комплектация (зарядка, наушники)",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()
        )
    elif count < 4:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("✅ Готово"))
        keyboard.add(types.KeyboardButton("❌ Отмена"))
        
        bot.send_message(
            user_id,
            f"✅ Фото #{count} загружено.\n"
            f"Загружено: {count} фото\n"
            f"Можно добавить еще: {4 - count} фото\n\n"
            f"💡 <i>Вы можете загрузить до 4 фото</i>\n\n"
            f"Нажмите ✅ Готово, когда загрузите все фото.",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add(types.KeyboardButton("✅ Готово"))
        keyboard.add(types.KeyboardButton("❌ Отмена"))
        
        bot.send_message(
            user_id,
            "✅ Максимальное количество фото загружено (4 фото).\n\n"
            "Нажмите ✅ Готово для перехода к предпросмотру.",
            reply_markup=keyboard
        )

@bot.message_handler(func=lambda m: m.text == "✅ Готово")
def handle_photos_done(message):
    """Обработка завершения загрузки фото"""
    user_id = message.from_user.id
    
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    if ad_creator.current_step != 'upload_photos':
        return
    
    # Проверяем минимальное количество фото
    if len(ad_creator.photos) < 2:
        bot.send_message(
            user_id,
            f"❌ Минимальное количество фото - 2.\n"
            f"Загружено: {len(ad_creator.photos)} фото\n"
            f"Нужно еще: {2 - len(ad_creator.photos)} фото"
        )
        return
    
    # Переходим к предпросмотру
    ad_creator.current_step = 'preview'
    show_smart_preview(user_id)

def show_smart_preview(user_id):
    """Показ интеллектуального предпросмотра"""
    if user_id not in storage.ads_in_progress:
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    # Генерируем оптимизированный текст
    ad_text = ad_creator.optimize_ad_text()
    
    # Создаем клавиатуру для подтверждения
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ Опубликовать", callback_data="smart_publish"),
        types.InlineKeyboardButton("✏️ Редактировать", callback_data="smart_edit")
    )
    keyboard.row(types.InlineKeyboardButton("🔄 Начать заново", callback_data="smart_restart"))
    keyboard.row(types.InlineKeyboardButton("❌ Отменить", callback_data="smart_cancel"))
    
    # Отправляем фото альбомом
    if ad_creator.photos:
        try:
            media = []
            for i, photo_id in enumerate(ad_creator.photos):
                if i == 0:
                    media.append(types.InputMediaPhoto(photo_id, caption=ad_text, parse_mode="HTML"))
                else:
                    media.append(types.InputMediaPhoto(photo_id))
            
            bot.send_media_group(user_id, media)
            bot.send_message(
                user_id,
                "📋 <b>Предварительный просмотр объявления:</b>\n\n"
                "Проверьте всю информацию перед публикацией.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки медиагруппы: {e}")
            bot.send_message(user_id, ad_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        bot.send_message(user_id, ad_text, parse_mode="HTML", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == "smart_publish")
def smart_publish_callback(call):
    """Публикация объявления"""
    user_id = call.from_user.id
    
    if user_id not in storage.ads_in_progress:
        bot.answer_callback_query(call.id, "❌ Объявление не найдено", show_alert=True)
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    # Генерируем финальный текст
    final_text = ad_creator.optimize_ad_text()
    
    # Создаем кнопку для связи
    contact_button = None
    contact = ad_creator.ad_data.get('contact', '')
    contact_type = ad_creator.ad_data.get('contact_type', '')
    
    if contact_type == 'phone' and contact:
        phone = contact.replace('+', '').replace(' ', '')
        contact_button = types.InlineKeyboardButton("📞 Позвонить", url=f"tel:+{phone}")
    elif contact_type == 'telegram' and contact:
        if contact.startswith('@'):
            contact_button = types.InlineKeyboardButton("💬 Написать", url=f"https://t.me/{contact[1:]}")
        else:
            contact_button = types.InlineKeyboardButton("💬 Написать", url=contact)
    
    try:
        # Публикуем в канал
        if ad_creator.photos:
            media = []
            for i, photo_id in enumerate(ad_creator.photos):
                if i == 0:
                    if contact_button:
                        keyboard = types.InlineKeyboardMarkup()
                        keyboard.add(contact_button)
                        media.append(types.InputMediaPhoto(photo_id, caption=final_text, parse_mode="HTML"))
                    else:
                        media.append(types.InputMediaPhoto(photo_id, caption=final_text, parse_mode="HTML"))
                else:
                    media.append(types.InputMediaPhoto(photo_id))
            
            sent_messages = bot.send_media_group(CHANNEL_ID, media)
            
            if contact_button and len(sent_messages) > 0:
                bot.send_message(CHANNEL_ID, "👇 <b>Связаться с продавцом:</b>", parse_mode="HTML", reply_markup=types.InlineKeyboardMarkup().add(contact_button))
            
        else:
            if contact_button:
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(contact_button)
                bot.send_message(CHANNEL_ID, final_text, parse_mode="HTML", reply_markup=keyboard)
            else:
                bot.send_message(CHANNEL_ID, final_text, parse_mode="HTML")
        
        # Обновляем статистику пользователя
        if user_id in storage.users:
            storage.users[user_id]["ads_created"] = storage.users[user_id].get("ads_created", 0) + 1
            storage.users[user_id]["last_ad_date"] = datetime.now().isoformat()
        
        # Сохраняем объявление в архив
        ad_id = f"AD{len(storage.published_ads) + 1:06d}"
        storage.published_ads[ad_id] = {
            'user_id': user_id,
            'ad_data': ad_creator.ad_data,
            'photos_count': len(ad_creator.photos),
            'published_at': datetime.now(),
            'channel_message_id': None
        }
        
        # Уведомляем пользователя
        bot.edit_message_text(
            text="✅ <b>Объявление успешно опубликовано!</b>\n\n"
                 f"Ваше объявление появилось в канале: {CHANNEL_ID}\n\n"
                 "📊 <i>Советы для быстрой продажи:</i>\n"
                 "• Отвечайте быстро на сообщения\n"
                 "• Будьте готовы к торгу\n"
                 "• Подготовьте телефон к показу\n\n"
                 "💰 <b>Удачи в продаже!</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
        
        logger.info(f"Пользователь {user_id} опубликовал объявление {ad_id}")
        
        # Очищаем данные
        del storage.ads_in_progress[user_id]
        
    except Exception as e:
        logger.error(f"Ошибка публикации объявления: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка публикации. Попробуйте позже.", show_alert=True)
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "smart_edit")
def smart_edit_callback(call):
    """Редактирование объявления"""
    user_id = call.from_user.id
    
    if user_id not in storage.ads_in_progress:
        bot.answer_callback_query(call.id, "❌ Объявление не найдено", show_alert=True)
        return
    
    ad_creator = storage.ads_in_progress[user_id]
    
    # Показываем меню редактирования
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    fields_to_edit = []
    if ad_creator.device_type == 'iphone':
        fields_to_edit = [
            ("📱 Модель", "edit_model"),
            ("💾 Память", "edit_memory"),
            ("📊 Состояние", "edit_condition"),
            ("🔋 Батарея", "edit_battery"),
            ("🎨 Цвет", "edit_color"),
            ("📦 Комплектация", "edit_package"),
            ("💰 Цена", "edit_price"),
            ("📞 Контакты", "edit_contact"),
            ("📷 Фото", "edit_photos")
        ]
    else:
        fields_to_edit = [
            ("📱 Модель", "edit_model"),
            ("🧠 ОЗУ", "edit_ram"),
            ("💾 ПЗУ", "edit_rom"),
            ("⚡️ Процессор", "edit_processor"),
            ("📊 Состояние", "edit_condition"),
            ("🔋 Аккумулятор", "edit_battery"),
            ("🎨 Цвет", "edit_color"),
            ("💰 Цена", "edit_price"),
            ("📞 Контакты", "edit_contact"),
            ("📷 Фото", "edit_photos")
        ]
    
    buttons = []
    for text, callback in fields_to_edit:
        buttons.append(types.InlineKeyboardButton(text, callback_data=callback))
    
    # Распределяем кнопки по рядам
    for i in range(0, len(buttons), 2):
        keyboard.row(*buttons[i:i+2])
    
    keyboard.row(types.InlineKeyboardButton("🔙 Назад к просмотру", callback_data="back_to_preview"))
    
    bot.edit_message_text(
        text="✏️ <b>Что вы хотите отредактировать?</b>\n\n"
             "Выберите поле для изменения:",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_preview")
def back_to_preview_callback(call):
    """Возврат к предпросмотру"""
    user_id = call.from_user.id
    show_smart_preview(user_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ["continue_ad", "restart_ad", "cancel_ad"])
def ad_session_management(call):
    """Управление сессией создания объявления"""
    user_id = call.from_user.id
    
    if call.data == "continue_ad":
        if user_id in storage.ads_in_progress:
            ad_creator = storage.ads_in_progress[user_id]
            # Продолжаем с текущего шага
            current_step = ad_creator.current_step or 'choose_brand'
            ask_next_question(call.message.chat.id, user_id, current_step)
        else:
            bot.answer_callback_query(call.id, "❌ Сессия устарела", show_alert=True)
    
    elif call.data == "restart_ad":
        # Удаляем текущее объявление
        if user_id in storage.ads_in_progress:
            del storage.ads_in_progress[user_id]
        
        # Создаем новое
        ad_creator = SmartAdCreator(user_id)
        storage.ads_in_progress[user_id] = ad_creator
        ask_brand_question(call, ad_creator)
    
    elif call.data == "cancel_ad":
        if user_id in storage.ads_in_progress:
            del storage.ads_in_progress[user_id]
        
        bot.edit_message_text(
            text="❌ Создание объявления отменено.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.answer_callback_query(call.id)

# ===== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (FAQ, Донат, Поддержка) остаются без изменений =====

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
        types.InlineKeyboardButton("💳 PREMIUM", callback_data="buy_premium"),
        types.InlineKeyboardButton("🎁 Поддержать", callback_data="simple_donate")
    )
    
    safe_send_message(user_id, donate_text, reply_markup=keyboard)

@bot.message_handler(func=lambda m: m.text == "❌ Отмена")
def cancel_command(message):
    """Обработка кнопки отмены"""
    user_id = message.from_user.id
    
    # Сбрасываем состояние пользователя
    reset_user_state(user_id)
    
    # Если есть объявление в процессе, предлагаем сохранить
    if user_id in storage.ads_in_progress:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("💾 Сохранить черновик", callback_data="save_draft"),
            types.InlineKeyboardButton("🗑️ Удалить", callback_data="discard_ad")
        )
        
        bot.send_message(
            user_id,
            "📝 <b>У вас есть незавершенное объявление</b>\n\n"
            "Вы можете сохранить его как черновик или удалить.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
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
🔗 <b>Username:</b> @{ticket['username'] if ticket['username'] != 'не указан' else 'не указан'}
🏷️ <b>Категория:</b> {ticket['category']}
🕐 <b>Дата:</b> {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}

📝 <b>Сообщение:</b>
"{ticket['messages'][0]['text']}"
"""
    
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

@bot.message_handler(func=lambda m: m.text == "📞 Поддержка")
def smart_support_command(message):
    """Обработка команды поддержки"""
    user_id = message.from_user.id
    
    user_tickets = smart_support.get_user_tickets(user_id)
    open_tickets = [t for t in user_tickets if t['status'] in ['new', 'pending']]
    
    support_text = """📞 <b>Техническая поддержка</b>

Опишите вашу проблему или вопрос:
• Вопросы по оплате
• Технические проблемы  
• Предложения по улучшению
• Общие вопросы

<b>Наш менеджер ответит вам в течение 24 часов.</b>"""
    
    if open_tickets:
        support_text += "\n\n⚠️ <b>У вас есть открытые обращения:</b>"
        for ticket in open_tickets[:3]:
            status_emoji = "🆕" if ticket['status'] == 'new' else "⏳"
            ticket_preview = ticket['messages'][0]['text'][:50] + "..." if len(ticket['messages'][0]['text']) > 50 else ticket['messages'][0]['text']
            support_text += f"\n{status_emoji} Тикет #{ticket['ticket_id']}: {ticket_preview}"
        
        support_text += "\n\n<i>Пожалуйста, дождитесь ответа по текущим обращениям.</i>"
    
    UserState.set_state(user_id, "waiting_support")
    safe_send_message(user_id, support_text, reply_markup=get_cancel_keyboard())

@bot.message_handler(func=lambda m: UserState.get_state(m.from_user.id) == "waiting_support")
def handle_smart_support_message(message):
    """Обработка сообщения в поддержку"""
    user_id = message.from_user.id
    message_text = message.text.strip()
    
    if not message_text or message_text == "❌ Отмена":
        reset_user_state(user_id)
        safe_send_message(user_id, "❌ Сообщение в поддержку отменено.")
        return
    
    user_data = storage.users.get(user_id, {})
    first_name = user_data.get('first_name', message.from_user.first_name)
    last_name = user_data.get('last_name', message.from_user.last_name or '')
    username = user_data.get('username', message.from_user.username or 'нет')
    
    ticket, duplicates = smart_support.create_ticket(
        user_id, username, first_name, last_name, message_text
    )
    
    if duplicates:
        duplicate_ticket = duplicates[0]
        
        smart_support.add_message(
            duplicate_ticket['ticket_id'],
            'user',
            f"📨 Дополнительное сообщение: {message_text}",
            action="duplicate_message_added"
        )
        
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
        
        notify_admins_about_update(duplicate_ticket, message_text)
        return
    
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
    
    notify_admins_about_new_ticket(ticket)

# ===== ОБРАБОТКА КНОПОК АДМИНИСТРАТОРА =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback_handler(call):
    """Обработка действий администратора"""
    admin_id = call.from_user.id
    admin_username = call.from_user.username
    
    if not is_admin(admin_id, admin_username):
        bot.answer_callback_query(call.id, "❌ У вас нет прав для этого действия", show_alert=True)
        return
    
    parts = call.data.split(':')
    action = parts[0]
    user_id = int(parts[1]) if len(parts) > 1 else None
    ticket_id = parts[2] if len(parts) > 2 else None
    
    if not user_id or not ticket_id:
        bot.answer_callback_query(call.id, "❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    ticket = smart_support.get_ticket(ticket_id)
    if not ticket:
        bot.answer_callback_query(call.id, "❌ Тикет не найден или уже обработан", show_alert=True)
        return
    
    if action == "admin_reply":
        storage.admin_reply_context[admin_id] = {
            'user_id': user_id,
            'ticket_id': ticket_id,
            'original_message_id': call.message.message_id,
            'timestamp': datetime.now()
        }
        
        remove_admin_keyboard(admin_id, call.message.message_id)
        
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
        smart_support.update_status(ticket_id, 'solved', admin_id)
        smart_support.add_message(
            ticket_id,
            'system',
            f"Тикет помечен как решенный администратором {admin_id}",
            action="marked_solved"
        )
        
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
        
        update_admin_messages(ticket_id, "✅ Решено")
        
        bot.answer_callback_query(call.id, "✅ Тикет помечен как решенный")
    
    elif action == "admin_pending":
        smart_support.update_status(ticket_id, 'pending', admin_id)
        smart_support.add_message(
            ticket_id,
            'system',
            f"Тикет помечен как 'в работе' администратором {admin_id}",
            action="marked_pending"
        )
        
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
        
        update_admin_messages(ticket_id, "⏳ В работе")
        
        bot.answer_callback_query(call.id, "⏳ Тикет помечен как 'в работе'")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПОДДЕРЖКИ =====
def notify_admins_about_update(ticket, new_message):
    """Уведомление администраторов об обновлении тикета"""
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
                    
                    bot.edit_message_text(
                        chat_id=admin_id,
                        message_id=msg_id,
                        text=updated_text,
                        parse_mode="HTML",
                        reply_markup=None
                    )
                
                del storage.admin_messages[(admin_id, msg_id)]
                
            except Exception as e:
                logger.error(f"Ошибка обновления сообщения админа {admin_id}: {e}")

# ===== ОБРАБОТКА ОТВЕТОВ АДМИНИСТРАТОРА =====
@bot.message_handler(func=lambda m: m.from_user.id in storage.admin_reply_context)
def handle_admin_reply(message):
    """Обработка ответа администратора пользователю"""
    admin_id = message.from_user.id
    
    if message.text == "❌ Отмена":
        if admin_id in storage.admin_reply_context:
            del storage.admin_reply_context[admin_id]
        bot.send_message(admin_id, "❌ Ответ отменен.")
        return
    
    context = storage.admin_reply_context.get(admin_id)
    if not context:
        bot.send_message(admin_id, "❌ Контекст ответа утерян.")
        return
    
    user_id = context.get('user_id')
    ticket_id = context.get('ticket_id')
    
    ticket = smart_support.get_ticket(ticket_id)
    if not ticket:
        bot.send_message(admin_id, "❌ Тикет не найден или уже обработан.")
        if admin_id in storage.admin_reply_context:
            del storage.admin_reply_context[admin_id]
        return
    
    smart_support.add_message(
        ticket_id,
        'admin',
        message.text,
        action="admin_reply"
    )
    
    smart_support.update_status(ticket_id, 'answered', admin_id)
    
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
        
        bot.send_message(
            admin_id,
            f"✅ <b>Ответ успешно отправлен пользователю!</b>\n\n"
            f"Тикет: #{ticket_id}\n"
            f"Пользователь: {ticket['first_name']}\n"
            f"Статус: Отвечено"
        )
        
        update_admin_messages(ticket_id, "💬 Отвечено")
    
    except Exception as e:
        logger.error(f"Ошибка отправки ответа пользователю {user_id}: {e}")
        bot.send_message(admin_id, f"❌ Ошибка отправки ответа: {e}")
    
    if admin_id in storage.admin_reply_context:
        del storage.admin_reply_context[admin_id]

# ===== ОБРАБОТЧИКИ ДОНАТА =====
@bot.callback_query_handler(func=lambda call: call.data == "simple_donate")
def simple_donate_handler(call):
    """Обработка кнопки 'Просто поддержать'"""
    user_id = call.from_user.id
    
    reset_user_state(user_id)
    
    text = ("❤️ <b>Поддержка развития бота</b>\n\n"
            "Выберите сумму поддержки или укажите свою:\n\n"
            "• Минимальная сумма: <b>1 USDT</b>\n"
            "• Максимальная сумма: <b>10000 USDT</b>\n\n"
            "Ваша поддержка помогает развивать новые функции и улучшать работу бота!")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("❤️ 1 USDT", callback_data="donate_amount:1"),
        types.InlineKeyboardButton("❤️ 2 USDT", callback_data="donate_amount:2")
    )
    markup.add(
        types.InlineKeyboardButton("❤️ 5 USDT", callback_data="donate_amount:5"),
        types.InlineKeyboardButton("❤️ 10 USDT", callback_data="donate_amount:10")
    )
    markup.row(types.InlineKeyboardButton("💰 Указать сумму", callback_data="enter_donate_amount"))
    markup.row(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_donate"))
    
    try:
        bot.edit_message_text(
            text=text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        logger.warning(f"Не удалось редактировать сообщение: {e}")
        bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=markup
        )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "buy_premium")
def buy_premium(call):
    """Покупка PREMIUM статуса"""
    user_id = call.from_user.id
    
    if user_id in storage.premium_users:
        bot.answer_callback_query(call.id, 
            "✅ У вас уже активирован PREMIUM статус!", 
            show_alert=True)
        return
    
    invoice = CryptoBotAPI.create_invoice(
        amount=3,
        currency="USDT",
        description="PREMIUM статус на 30 дней",
        payload=str(user_id)
    )
    
    if invoice:
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

@bot.callback_query_handler(func=lambda call: call.data == "back_to_donate")
def back_to_donate_handler(call):
    """Возврат в меню доната"""
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
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💳 PREMIUM", callback_data="buy_premium"),
        types.InlineKeyboardButton("🎁 Поддержать", callback_data="simple_donate")
    )
    
    try:
        bot.edit_message_text(
            text=donate_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        bot.send_message(
            user_id,
            donate_text,
            parse_mode="HTML",
            reply_markup=keyboard
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

@bot.message_handler(func=lambda m: UserState.get_state(m.from_user.id) == "entering_donate_amount")
def handle_donate_amount_input(message):
    """Обработка ввода суммы доната"""
    user_id = message.from_user.id
    amount_text = message.text.strip()
    
    if amount_text == "❌ Отмена":
        reset_user_state(user_id)
        return
    
    try:
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

def create_donate_invoice(user_id, amount):
    """Создание инвойса для доната"""
    invoice = CryptoBotAPI.create_invoice(
        amount=amount,
        currency="USDT",
        description=f"Поддержка развития бота: {amount} USDT",
        payload=str(user_id)
    )
    
    if invoice:
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
    
    # Очищаем старые сообщения поддержки
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
    
    threading.Timer(21600, cleanup_old_tickets).start()

# Запускаем очистку старых данных
cleanup_old_data()
cleanup_old_tickets()

# ===== ЗАПУСК БОТА =====
if __name__ == '__main__':
    print("=" * 60)
    print("🤖 УМНЫЙ БОТ ДЛЯ ОБЪЯВЛЕНИЙ О ТЕЛЕФОНАХ")
    print("=" * 60)
    print(f"Telegram Bot Token: {'✅ Установлен' if TOKEN != '8397567369:AAFki44pWtxP5M9iPGEn26yvUsu1Fv-9g3o' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"CryptoBot API Key: {'✅ Установлен' if CRYPTO_BOT_API_KEY != '498509:AABNPgPwTiCU9DdByIgswTvIuSz5VO9neRy' else '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Канал для публикаций: {CHANNEL_ID}")
    print(f"Чат поддержки: {SUPPORT_CHAT_ID}")
    print(f"CEO Admin ID: {ADMIN_CEO_ID or '❌ НЕ УСТАНОВЛЕН'}")
    print(f"Support Admin ID: {ADMIN_SUPPORT_ID or '❌ НЕ УСТАНОВЛЕН'}")
    print("=" * 60)
    print("📢 Основные команды:")
    print("• /start - Начать работу с интеллектуальной системой")
    print("• /mytickets - Мои обращения в поддержку")
    print("• 📞 Поддержка - Умная система поддержки")
    print("• 💎 Донат - Поддержать бота")
    print("=" * 60)
    print("🎯 ИНТЕЛЛЕКТУАЛЬНЫЕ ВОЗМОЖНОСТИ:")
    print("✅ Автоматическое определение типа устройства")
    print("✅ Адаптивные вопросы для iPhone/Android")
    print("✅ Умная валидация ввода")
    print("✅ Контекстные подсказки и рекомендации")
    print("✅ Автоматическое форматирование объявлений")
    print("✅ Автодополнение популярных моделей")
    print("✅ Проверка рыночных цен")
    print("✅ Интеллектуальный предпросмотр")
    print("✅ Автосохранение прогресса")
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