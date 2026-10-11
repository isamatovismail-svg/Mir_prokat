from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
import logging
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)


class Notification(models.Model):
    """Журнал отправленных уведомлений"""
    TYPE_CHOICES = [
        ('telegram_admin', 'Telegram Администратору'),
        ('telegram_client', 'Telegram Клиенту'),
        ('sms', 'SMS'),
        ('email', 'Email'),
    ]

    STATUS_CHOICES = [
        ('SENT', 'Отправлено'),
        ('FAILED', 'Ошибка'),
        ('QUEUED', 'В очереди'),
    ]

    notification_type = models.CharField(_('Тип'), max_length=30, choices=TYPE_CHOICES)
    recipient = models.CharField(_('Получатель'), max_length=150)
    order = models.ForeignKey(
        'orders.Order', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='notifications', verbose_name=_('Заказ')
    )
    title = models.CharField(_('Тема/Заголовок'), max_length=255, blank=True)
    message = models.TextField(_('Текст сообщения'))
    status = models.CharField(_('Статус'), max_length=20, choices=STATUS_CHOICES, default='SENT')
    error_message = models.TextField(_('Ошибка при отправке'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Уведомление')
        verbose_name_plural = _('Уведомления')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.notification_type} -> {self.recipient} [{self.status}]"


def send_telegram_message(chat_id, text, reply_markup=None):
    """
    Отправка сообщения через Telegram Bot HTTP API
    (без необходимости запускать фоновый worker)
    """
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not bot_token or not chat_id:
        logger.warning(f"Telegram bot_token or chat_id not configured. Message skipped: {text[:50]}...")
        return False, "Bot token or chat ID is empty"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': str(chat_id),
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read()
            res_json = json.loads(res_body.decode('utf-8'))
            if res_json.get('ok'):
                return True, "OK"
            return False, res_json.get('description', 'Unknown telegram API error')
    except Exception as e:
        logger.error(f"Failed to send telegram message to {chat_id}: {e}")
        return False, str(e)


def notify_admin_new_order(order):
    """
    Формирование и отправка уведомления администратору о новом заказе
    """
    admin_chat_id = getattr(settings, 'TELEGRAM_ADMIN_CHAT_ID', '')
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')

    # Формируем состав заказа
    items_lines = []
    for item in order.items.select_related('product'):
        items_lines.append(f"▫️ {item.product.name} — <b>{item.quantity} шт.</b> ({item.total_price:,.0f} ₸)")
    items_text = "\n".join(items_lines) if items_lines else "<i>Не выбраны отдельные товары</i>"

    services_lines = []
    for srv in order.services.select_related('service'):
        services_lines.append(f"🔧 {srv.service.name} — <b>{srv.total_price:,.0f} ₸</b>")
    services_text = "\n".join(services_lines) if services_lines else ""

    text = f"""🔔 <b>НОВАЯ ЗАЯВКА #{order.order_number}</b>

👤 <b>Клиент:</b> {order.client.name}
📞 <b>Телефон:</b> {order.client.phone}
✈️ <b>Telegram:</b> {order.client.telegram or 'не указан'}
📅 <b>Дата мероприятия:</b> {order.event_date.strftime('%d.%m.%Y')}
👥 <b>Гостей:</b> {order.guest_count}
🎉 <b>Тип:</b> {order.event_type.name if order.event_type else 'Общее'}
📦 <b>Пакет:</b> {order.package.name if order.package else 'Индивидуальный набор'}

💰 <b>Ориентировочная сумма: {order.total_price:,.0f} ₸</b>
<i>(Залог: {order.deposit_price:,.0f} ₸)</i>

📋 <b>Состав:</b>
{items_text}
{services_text}

📍 <b>Адрес:</b> {order.address or 'Уточняется'}
🚚 <b>Доставка:</b> {'Да' if order.need_delivery else 'Нет'}
🛠 <b>Монтаж:</b> {'Да' if order.need_setup else 'Нет'}
🧹 <b>Демонтаж:</b> {'Да' if order.need_teardown else 'Нет'}

💬 <b>Комментарий:</b>
«{order.comment or 'Без комментария'}»
"""

    reply_markup = {
        'inline_keyboard': [
            [
                {'text': '✅ Принять', 'callback_data': f'order_confirm_{order.id}'},
                {'text': '❌ Отклонить', 'callback_data': f'order_cancel_{order.id}'}
            ],
            [
                {'text': '📦 Проверить склад', 'callback_data': f'order_stock_{order.id}'},
                {'text': '✏️ В админку', 'url': f"{site_url}/admin-panel/orders/{order.id}/"}
            ]
        ]
    }

    success, err = send_telegram_message(admin_chat_id, text, reply_markup=reply_markup)
    Notification.objects.create(
        notification_type='telegram_admin',
        recipient=str(admin_chat_id or 'ADMIN_NOT_SET'),
        order=order,
        title=f"Новая заявка #{order.order_number}",
        message=text,
        status='SENT' if success else 'FAILED',
        error_message='' if success else err
    )
    return success


def notify_client_status_update(order):
    """Уведомление клиенту о смене статуса заказа"""
    if not order.client.telegram_id:
        return False

    status_name = dict(order.STATUS_CHOICES).get(order.status, order.status)
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')

    msg = f"""👋 Здравствуйте, {order.client.name}!

Статус вашей заявки <b>#{order.order_number}</b> изменился:
👉 <b>{status_name}</b>

📅 Дата мероприятия: {order.event_date.strftime('%d.%m.%Y')}
💰 Сумма: {order.total_price:,.0f} ₸
💳 Оплачено: {order.paid_amount:,.0f} ₸
Остаток: {order.remaining_amount:,.0f} ₸

Посмотреть детали заказа можно по ссылке:
{site_url}/orders/{order.order_number}/
"""
    success, err = send_telegram_message(order.client.telegram_id, msg)
    Notification.objects.create(
        notification_type='telegram_client',
        recipient=str(order.client.telegram_id),
        order=order,
        title=f"Статус заказа #{order.order_number}: {status_name}",
        message=msg,
        status='SENT' if success else 'FAILED',
        error_message='' if success else err
    )
    return success
