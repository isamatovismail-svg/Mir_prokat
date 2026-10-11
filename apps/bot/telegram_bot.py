import logging
import math
from datetime import datetime
from decimal import Decimal
from django.db import models
from django.conf import settings
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

# Состояния диалога для калькулятора
GUESTS, EVENT_TYPE, PACKAGE, EXTRAS, EVENT_DATE, CLIENT_NAME, CLIENT_PHONE, ADDRESS, COMMENT = range(9)


# --- Синхронные функции работы с базой данных (вызываются через sync_to_async) ---

@sync_to_async
def db_get_event_types():
    from apps.catalog.models import EventType
    return list(EventType.objects.filter(is_active=True).values('id', 'name'))

@sync_to_async
def db_get_packages():
    from apps.catalog.models import Package
    return list(Package.objects.filter(is_active=True).values('id', 'name', 'tier', 'description'))

@sync_to_async
def db_check_availability(date_str, guests):
    from apps.catalog.models import Product
    from apps.warehouse.models import StockReservation
    try:
        ev_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return False, "Неверный формат даты. Используйте ГГГГ-ММ-ДД (например: 2026-10-15)"

    # Проверяем стулья и столы
    chairs_needed = guests
    tables_needed = math.ceil(guests / 10)

    chair_prod = Product.objects.filter(category__slug='stulya', is_active=True).first()
    table_prod = Product.objects.filter(category__slug='stoly', is_active=True).first()

    issues = []
    if chair_prod:
        res = StockReservation.objects.filter(product=chair_prod, date=ev_date, is_active=True).aggregate(t=models.Sum('quantity'))['t'] or 0
        avail = max(0, chair_prod.available_quantity - res)
        if avail < chairs_needed:
            issues.append(f"Стулья: свободно {avail}, нужно {chairs_needed}")

    if table_prod:
        res = StockReservation.objects.filter(product=table_prod, date=ev_date, is_active=True).aggregate(t=models.Sum('quantity'))['t'] or 0
        avail = max(0, table_prod.available_quantity - res)
        if avail < tables_needed:
            issues.append(f"Столы: свободно {avail}, нужно {tables_needed}")

    if issues:
        return False, "На выбранную дату недостаточно товара: " + ", ".join(issues)
    return True, f"На {ev_date.strftime('%d.%m.%Y')} всё необходимое оборудование свободно и доступно!"

@sync_to_async
def db_create_order(data, telegram_user):
    from apps.orders.models import Order, OrderItem, OrderStatusHistory
    from apps.clients.models import Client
    from apps.catalog.models import Package, Product, EventType
    from apps.notifications.models import notify_admin_new_order

    phone = data['phone']
    name = data['name']
    client, _ = Client.objects.get_or_create(
        phone=phone,
        defaults={
            'name': name,
            'telegram': f"@{telegram_user.username}" if telegram_user.username else "",
            'telegram_id': telegram_user.id
        }
    )
    if not client.telegram_id:
        client.telegram_id = telegram_user.id
        client.save(update_fields=['telegram_id'])

    ev_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    package = Package.objects.filter(id=data['package_id']).first()
    event_type = EventType.objects.filter(id=data.get('event_type_id')).first()

    order = Order.objects.create(
        order_number=Order.generate_order_number(),
        client=client,
        event_date=ev_date,
        guest_count=data['guests'],
        package=package,
        event_type=event_type,
        address=data.get('address', ''),
        comment=data.get('comment', ''),
        need_delivery=True,
        delivery_price=Decimal('6000.00'),
        source='telegram_bot'
    )

    if package:
        for item in package.items.all():
            qty = item.get_quantity_for_guests(data['guests'])
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=qty,
                rental_price=item.product.rental_price,
                total_price=item.product.rental_price * qty
            )

    order.recalculate_totals()
    OrderStatusHistory.objects.create(
        order=order,
        old_status='',
        new_status=Order.STATUS_NEW,
        comment='Заявка создана клиентом в Telegram-боте'
    )

    try:
        notify_admin_new_order(order)
    except Exception:
        pass

    return order.order_number, order.total_price

@sync_to_async
def db_get_client_orders(telegram_id):
    from apps.orders.models import Order
    return list(Order.objects.filter(client__telegram_id=telegram_id).order_by('-created_at')[:5].values(
        'order_number', 'event_date', 'total_price', 'status', 'guest_count'
    ))

@sync_to_async
def db_get_catalog_summary():
    from apps.catalog.models import Category
    cats = Category.objects.filter(is_active=True).prefetch_related('products')
    res = []
    for c in cats:
        res.append(f"{c.icon} <b>{c.name}</b> ({c.products.filter(is_active=True).count()} тов.)")
    return "\n".join(res)

@sync_to_async
def db_update_order_status(order_id, new_status, comment=""):
    from apps.orders.models import Order, OrderStatusHistory
    from apps.notifications.models import notify_client_status_update
    order = Order.objects.filter(id=order_id).first()
    if not order:
        return False, "Заказ не найден"
    old = order.status
    order.status = new_status
    order.save(update_fields=['status'])
    order.sync_reservations()
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old,
        new_status=new_status,
        comment=comment or 'Смена статуса через Telegram inline-кнопку'
    )
    notify_client_status_update(order)
    return True, order.order_number


# --- Telegram Bot Command Handlers ---

MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        ['🎉 Рассчитать заказ', '📦 Каталог'],
        ['📅 Проверить дату', '📋 Мои заявки'],
        ['📞 Связаться с менеджером']
    ],
    resize_keyboard=True
)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Секция 14 & 15: Приветствие и главное меню"""
    user_name = update.effective_user.first_name or "Гость"
    text = f"""Здравствуйте, {user_name}! 👋

Добро пожаловать в <b>Mir Prokat</b> — сервис аренды оборудования и декора для мероприятий.

Мы предоставляем:
▫️ Столы и стулья (банкетные, золотые Кьявари)
▫️ Ресторанную посуду, бокалы и столовые приборы
▫️ Текстиль и скатерти в пол
▫️ Свадебные арки и декор

Поможем подобрать всё необходимое для вашего праздника! Что вы хотите сделать?"""

    await update.message.reply_text(text, parse_mode='HTML', reply_markup=MAIN_MENU_KEYBOARD)

async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр основных категорий каталога"""
    cats_text = await db_get_catalog_summary()
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')

    msg = f"""📦 <b>Каталог оборудования Mir Prokat:</b>

{cats_text}

Вы можете посмотреть подробные фотографии и цены на нашем сайте или рассчитать готовый комплект прямо в боте:"""

    inline_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Открыть полный каталог на сайте", url=f"{site_url}/catalog/")]
    ])
    await update.message.reply_text(msg, parse_mode='HTML', reply_markup=inline_btn)

async def my_orders_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Секция 14: Просмотр моих заявок"""
    orders = await db_get_client_orders(update.effective_user.id)
    if not orders:
        await update.message.reply_text("У вас пока нет активных заявок. Нажмите «🎉 Рассчитать заказ», чтобы оформить аренду.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    text = "📋 <b>Ваши последние заявки:</b>\n\n"
    for ord in orders:
        text += f"▫️ <b>#{ord['order_number']}</b> ({ord['event_date'].strftime('%d.%m.%Y')})\n"
        text += f"   Гостей: {ord['guest_count']}, Статус: {ord['status']}\n"
        text += f"   Сумма: {ord['total_price']:,.0f} ₸\n\n"

    await update.message.reply_text(text, parse_mode='HTML')

async def manager_contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Связь с менеджером"""
    text = """📞 <b>Контакты для связи:</b>

▫️ Телефон: +7 (777) 123-45-67
▫️ Отдел аренды: +7 (701) 555-88-99
▫️ Склад / Шоурум: г. Алматы, ул. Достык, 180
▫️ Время работы: с 09:00 до 20:00 (заявки 24/7)

Менеджер в Telegram: @mir_prokat_manager"""
    await update.message.reply_text(text, parse_mode='HTML')

async def check_date_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка занятости даты"""
    text = """📅 <b>Проверка доступности оборудования на дату:</b>

Чтобы проверить свободные остатки, запустите расчёт через кнопку <b>«🎉 Рассчитать заказ»</b> или перейдите в интерактивный онлайн-калькулятор на сайте.

Система в реальном времени проверит наличие стульев, столов, текстиля и посуды!"""
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')
    inline_btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ Открыть калькулятор на сайте", url=f"{site_url}/calculator/")]
    ])
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=inline_btn)


# --- Пошаговый сценарий «Рассчитать заказ» (Секция 15 ТЗ) ---

async def calc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: Количество гостей"""
    context.user_data.clear()
    kb = ReplyKeyboardMarkup(
        [['20', '30', '50'], ['70', '100', '150'], ['200', '300'], ['❌ Отмена']],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "🎉 <b>Шаг 1: Сколько будет гостей на мероприятии?</b>\nВыберите из вариантов или введите своё число:",
        parse_mode='HTML',
        reply_markup=kb
    )
    return GUESTS

async def calc_guests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == '❌ Отмена':
        await update.message.reply_text("Расчёт отменен.", reply_markup=MAIN_MENU_KEYBOARD)
        return ConversationHandler.END

    try:
        guests = int(text)
        if guests < 5 or guests > 1000:
            await update.message.reply_text("Пожалуйста, введите количество гостей от 5 до 1000:")
            return GUESTS
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите число (например, 100):")
        return GUESTS

    context.user_data['guests'] = guests

    # Шаг 2: Тип события
    event_types = await db_get_event_types()
    context.user_data['event_types_list'] = event_types

    kb_rows = [[ev['name']] for ev in event_types[:6]]
    kb_rows.append(['❌ Отмена'])
    kb = ReplyKeyboardMarkup(kb_rows, resize_keyboard=True)

    await update.message.reply_text(
        f"👍 Принято: <b>{guests} гостей</b>.\n\n<b>Шаг 2: Какое у вас мероприятие?</b>",
        parse_mode='HTML',
        reply_markup=kb
    )
    return EVENT_TYPE

async def calc_event_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == '❌ Отмена':
        await update.message.reply_text("Расчёт отменен.", reply_markup=MAIN_MENU_KEYBOARD)
        return ConversationHandler.END

    types = context.user_data.get('event_types_list', [])
    matched = next((e for e in types if e['name'].lower() == text.lower()), None)
    context.user_data['event_type_id'] = matched['id'] if matched else None
    context.user_data['event_type_name'] = text

    # Шаг 3: Выбор пакета
    packages = await db_get_packages()
    context.user_data['packages_list'] = packages

    kb = ReplyKeyboardMarkup(
        [['BASIC', 'STANDARD'], ['PREMIUM', '❌ Отмена']],
        resize_keyboard=True
    )

    guests = context.user_data['guests']
    msg = f"""✨ <b>Шаг 3: Выберите готовый пакет оборудования:</b>

▫️ <b>BASIC</b> (~{guests * 1100:,.0f} ₸):
   {guests} стульев, {math.ceil(guests/10)} столов, {guests} тарелок, приборы, стаканы, скатерти.

▫️ <b>STANDARD</b> (~{guests * 1550:,.0f} ₸):
   Все из Basic + бокалы для вина, текстильные салфетки, базовые композиции.

▫️ <b>PREMIUM</b> (~{guests * 2300 + 15000:,.0f} ₸):
   Все из Standard + золотые стулья Кьявари, бокалы флейта, десертные тарелки, арка."""

    await update.message.reply_text(msg, parse_mode='HTML', reply_markup=kb)
    return PACKAGE

async def calc_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text == '❌ ОТМЕНА':
        await update.message.reply_text("Расчёт отменен.", reply_markup=MAIN_MENU_KEYBOARD)
        return ConversationHandler.END

    packages = context.user_data.get('packages_list', [])
    matched = next((p for p in packages if p['tier'].upper() == text or p['name'].upper() == text), packages[0] if packages else None)

    if not matched:
        await update.message.reply_text("Выберите: BASIC, STANDARD или PREMIUM:")
        return PACKAGE

    context.user_data['package_id'] = matched['id']
    context.user_data['package_name'] = matched['name']

    # Шаг 4: Дата мероприятия
    kb = ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
    await update.message.reply_text(
        f"Выбран пакет <b>{matched['name']}</b>.\n\n📅 <b>Шаг 4: Укажите дату мероприятия</b> в формате ГГГГ-ММ-ДД (например: 2026-10-15):",
        parse_mode='HTML',
        reply_markup=kb
    )
    return EVENT_DATE

async def calc_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == '❌ Отмена':
        await update.message.reply_text("Расчёт отменен.", reply_markup=MAIN_MENU_KEYBOARD)
        return ConversationHandler.END

    is_ok, msg = await db_check_availability(text, context.user_data['guests'])
    if not is_ok:
        await update.message.reply_text(f"⚠️ {msg}\n\nПожалуйста, введите другую дату (ГГГГ-ММ-ДД):")
        return EVENT_DATE

    context.user_data['date'] = text
    await update.message.reply_text(f"✅ {msg}")

    # Шаг 5: Имя
    await update.message.reply_text("👤 <b>Шаг 5: Как к вам обращаться?</b> Введите ваше имя:", parse_mode='HTML')
    return CLIENT_NAME

async def calc_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text.strip()

    # Шаг 6: Телефон
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Отправить номер телефона", request_contact=True)], ['❌ Отмена']],
        resize_keyboard=True
    )
    await update.message.reply_text("📞 <b>Шаг 6: Укажите номер телефона для подтверждения:</b>", parse_mode='HTML', reply_markup=kb)
    return CLIENT_PHONE

async def calc_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    if phone == '❌ Отмена':
        await update.message.reply_text("Расчёт отменен.", reply_markup=MAIN_MENU_KEYBOARD)
        return ConversationHandler.END

    context.user_data['phone'] = phone

    # Шаг 7: Адрес
    kb = ReplyKeyboardMarkup([['Самовывоз со склада'], ['г. Алматы (уточняется)'], ['❌ Отмена']], resize_keyboard=True)
    await update.message.reply_text("📍 <b>Шаг 7: Укажите адрес проведения мероприятия:</b>", parse_mode='HTML', reply_markup=kb)
    return ADDRESS

async def calc_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == '❌ Отмена':
        await update.message.reply_text("Расчёт отменен.", reply_markup=MAIN_MENU_KEYBOARD)
        return ConversationHandler.END

    context.user_data['address'] = text

    # Создание заявки в базе данных
    order_num, total = await db_create_order(context.user_data, update.effective_user)
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')

    success_msg = f"""🎉 <b>ЗАЯВКА #{order_num} ПРИНЯТА!</b>

Ориентировочная сумма: <b>{total:,.0f} ₸</b>
📅 Дата: {context.user_data['date']}
👥 Гостей: {context.user_data['guests']}
📦 Пакет: {context.user_data['package_name']}

Наш менеджер уже получил заявку и свяжется с вами в течение 10–15 минут для подтверждения бронирования.

Ссылка для отслеживания:
{site_url}/orders/{order_num}/"""

    await update.message.reply_text(success_msg, parse_mode='HTML', reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END


# --- Обработчик админских inline кнопок (Секция 16 ТЗ: Принять, Отклонить, и т.д.) ---

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith('order_confirm_'):
        order_id = int(data.split('_')[-1])
        ok, num = await db_update_order_status(order_id, 'CONFIRMED', 'Подтвержден администратором через Telegram')
        if ok:
            await query.edit_message_text(f"{query.message.text}\n\n✅ <b>ЗАКАЗ #{num} ПОДТВЕРЖДЕН (Склад зарезервирован)</b>", parse_mode='HTML')
        else:
            await query.edit_message_text(f"{query.message.text}\n\n❌ Ошибка: {num}", parse_mode='HTML')

    elif data.startswith('order_cancel_'):
        order_id = int(data.split('_')[-1])
        ok, num = await db_update_order_status(order_id, 'CANCELLED', 'Отклонен администратором через Telegram')
        await query.edit_message_text(f"{query.message.text}\n\n❌ <b>ЗАКАЗ #{num} ОТКЛОНЕН</b>", parse_mode='HTML')


def setup_telegram_application():
    """Сборка приложения Telegram-бота"""
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан в настройках")
        return None

    app = Application.builder().token(token).build()

    # Conversation handler для расчета заказа
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^🎉 Рассчитать заказ$'), calc_start),
            CommandHandler('calculate', calc_start),
        ],
        states={
            GUESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_guests)],
            EVENT_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_event_type)],
            PACKAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_package)],
            EVENT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_date)],
            CLIENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_name)],
            CLIENT_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, calc_phone)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, calc_address)],
        },
        fallbacks=[CommandHandler('cancel', start_handler)],
    )

    app.add_handler(CommandHandler('start', start_handler))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Regex('^📦 Каталог$'), catalog_handler))
    app.add_handler(MessageHandler(filters.Regex('^📅 Проверить дату$'), check_date_menu_handler))
    app.add_handler(MessageHandler(filters.Regex('^📋 Мои заявки$'), my_orders_handler))
    app.add_handler(MessageHandler(filters.Regex('^📞 Связаться с менеджером$'), manager_contact_handler))
    app.add_handler(CallbackQueryHandler(admin_callback_handler))

    return app
