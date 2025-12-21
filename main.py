import telebot
from telebot import types
import datetime

bot = telebot.TeleBot("8508464253:AAFwysK5nYz0j_YURQy7As2u2_Cr9pfiyZA")

# Контекст для каждого пользователя
user_context = {}

def get_user_context(user_id):
    if user_id not in user_context:
        user_context[user_id] = {
            'view': 'main',
            'last_message_id': None
        }
    return user_context[user_id]

def minimalist_format(text):
    """Минималистичное форматирование текста"""
    return f"⚫️ {text}"

def update_message(chat_id, message_id, text, keyboard=None):
    """Умное обновление сообщения"""
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        return True
    except:
        return False

def create_main_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        types.InlineKeyboardButton("💳 Карты", callback_data="cards"),
        types.InlineKeyboardButton("❓ Помощь", callback_data="help")
    )
    return keyboard

def create_back_keyboard(target="main"):
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(types.InlineKeyboardButton("← Назад", callback_data=target))
    return keyboard

@bot.message_handler(commands=['start', 'menu'])
def handle_start(message):
    context = get_user_context(message.from_user.id)
    
    welcome_text = f"""
    {minimalist_format('Дебетовые карты')}

    Простота
    Надежность
    Минимализм

    Выберите раздел:
    """
    
    # Если есть предыдущее сообщение - редактируем его
    if context['last_message_id'] and update_message(
        message.chat.id, 
        context['last_message_id'], 
        welcome_text, 
        create_main_keyboard()
    ):
        context['last_message_id'] = context['last_message_id']
    else:
        # Иначе отправляем новое
        msg = bot.send_message(
            message.chat.id,
            welcome_text,
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
        context['last_message_id'] = msg.message_id
        context['view'] = 'main'

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    context = get_user_context(user_id)
    
    # Сохраняем ID текущего сообщения
    context['last_message_id'] = call.message.message_id
    
    if call.data == "main":
        handle_main_view(call)
    elif call.data == "profile":
        handle_profile_view(call)
    elif call.data == "cards":
        handle_cards_view(call)
    elif call.data == "help":
        handle_help_view(call)
    elif call.data == "order":
        handle_order_view(call)

def handle_main_view(call):
    text = f"""
    {minimalist_format('Дебетовые карты')}

    Простота
    Надежность
    Минимализм

    Выберите раздел:
    """
    
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        create_main_keyboard()
    )
    get_user_context(call.from_user.id)['view'] = 'main'

def handle_profile_view(call):
    user = call.from_user
    
    # Умное определение статуса
    reg_date = datetime.datetime.now().strftime("%d.%m.%y")
    status = "Новый" if not hasattr(user, 'cards') else "Клиент"
    
    text = f"""
    {minimalist_format('Профиль')}

    ID: `{user.id}`
    Имя: {user.first_name or '—'}
    Username: {f'@{user.username}' if user.username else '—'}
    
    Статус: {status}
    С {reg_date}
    """
    
    keyboard = create_back_keyboard("main")
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        keyboard
    )
    get_user_context(call.from_user.id)['view'] = 'profile'

def handle_cards_view(call):
    text = f"""
    {minimalist_format('Карты')}

    • Classic — 0₽/месяц
    • Premium — 499₽/месяц
    • Metal — 1999₽/месяц

    Все карты включают:
    — Бесконтактную оплату
    — Мобильный банк
    — Страхование
    """
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("📝 Оформить", callback_data="order"),
        types.InlineKeyboardButton("← Назад", callback_data="main")
    )
    
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        keyboard
    )
    get_user_context(call.from_user.id)['view'] = 'cards'

def handle_help_view(call):
    text = f"""
    {minimalist_format('Помощь')}

    Частые вопросы:

    1. Как оформить карту?
    Через раздел «Карты»

    2. Срок доставки?
    1-3 рабочих дня

    3. Стоимость обслуживания?
    От 0₽ в месяц

    Контакты:
    support@card.ru
    """
    
    keyboard = create_back_keyboard("main")
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        keyboard
    )
    get_user_context(call.from_user.id)['view'] = 'help'

def handle_order_view(call):
    text = f"""
    {minimalist_format('Оформление')}

    Выберите тип карты:

    [1] Classic
    • 0₽ в месяц
    • Кэшбек 1%

    [2] Premium
    • 499₽ в месяц
    • Кэшбек 5%
    • Lounge доступ

    [3] Metal
    • 1999₽ в месяц
    • Кэшбек 10%
    • Персональный менеджер
    """
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("1. Classic", callback_data="order_classic"),
        types.InlineKeyboardButton("2. Premium", callback_data="order_premium"),
        types.InlineKeyboardButton("3. Metal", callback_data="order_metal"),
        types.InlineKeyboardButton("← Назад", callback_data="cards")
    )
    
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        keyboard
    )
    get_user_context(call.from_user.id)['view'] = 'order'

# Обработчики выбора карты
@bot.callback_query_handler(func=lambda call: call.data.startswith('order_'))
def handle_card_selection(call):
    card_type = call.data.replace('order_', '')
    prices = {'classic': '0₽', 'premium': '499₽', 'metal': '1999₽'}
    
    text = f"""
    {minimalist_format('Подтверждение')}

    Карта: {card_type.capitalize()}
    Стоимость: {prices.get(card_type, '?')}/месяц

    Для завершения оформления:
    1. Подтвердите выбор
    2. Ожидайте звонка менеджера
    3. Получите карту курьером
    """
    
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{card_type}"),
        types.InlineKeyboardButton("← Назад", callback_data="order")
    )
    
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_'))
def handle_confirmation(call):
    bot.answer_callback_query(call.id, "✅ Заявка принята")
    
    text = f"""
    {minimalist_format('Спасибо')}

    Ваша заявка принята.
    Менеджер свяжется в течение часа.

    Номер заявки: #{call.from_user.id}{datetime.datetime.now().strftime('%H%M')}
    """
    
    keyboard = create_back_keyboard("main")
    update_message(
        call.message.chat.id,
        call.message.message_id,
        text,
        keyboard
    )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    context = get_user_context(user_id)
    
    # Умный ответ на текстовые сообщения
    responses = {
        'профиль': 'profile',
        'карты': 'cards',
        'помощь': 'help',
        'оформить': 'order',
        'меню': 'main'
    }
    
    text_lower = message.text.lower()
    for key, action in responses.items():
        if key in text_lower:
            # Создаем fake call объект
            class FakeCall:
                pass
            
            fake_call = FakeCall()
            fake_call.from_user = message.from_user
            fake_call.message = type('obj', (object,), {
                'chat': type('obj', (object,), {'id': message.chat.id})(),
                'message_id': context.get('last_message_id')
            })()
            fake_call.data = action
            
            # Обрабатываем как callback
            handle_callback(fake_call)
            return
    
    # Если команда не распознана
    if context.get('last_message_id'):
        update_message(
            message.chat.id,
            context['last_message_id'],
            f"{minimalist_format('Используйте кнопки меню')}",
            create_main_keyboard()
        )
    else:
        handle_start(message)

if __name__ == "__main__":
    print("Бот запущен в минималистичном режиме...")
    bot.infinity_polling()