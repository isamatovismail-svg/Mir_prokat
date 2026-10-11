from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
import random
import string

User = get_user_model()


class Order(models.Model):
    """Заказ на прокат оборудования"""
    STATUS_NEW = 'NEW'
    STATUS_PENDING = 'PENDING'
    STATUS_CONFIRMED = 'CONFIRMED'
    STATUS_PAYMENT_PENDING = 'PAYMENT_PENDING'
    STATUS_PAID = 'PAID'
    STATUS_PREPARING = 'PREPARING'
    STATUS_READY = 'READY'
    STATUS_DELIVERING = 'DELIVERING'
    STATUS_EVENT = 'EVENT'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_NEW, _('Новая заявка')),
        (STATUS_PENDING, _('На рассмотрении')),
        (STATUS_CONFIRMED, _('Подтверждена (Зарезервировано)')),
        (STATUS_PAYMENT_PENDING, _('Ожидает оплаты')),
        (STATUS_PAID, _('Оплачена')),
        (STATUS_PREPARING, _('Подготовка к выдаче')),
        (STATUS_READY, _('Готов к выдаче')),
        (STATUS_DELIVERING, _('В доставке')),
        (STATUS_EVENT, _('Мероприятие сегодня')),
        (STATUS_COMPLETED, _('Завершена')),
        (STATUS_CANCELLED, _('Отменена')),
    ]

    order_number = models.CharField(_('Номер заказа'), max_length=20, unique=True, db_index=True)
    client = models.ForeignKey(
        'clients.Client', on_delete=models.CASCADE,
        related_name='orders', verbose_name=_('Клиент')
    )
    event_date = models.DateField(_('Дата мероприятия'), db_index=True)
    event_time = models.TimeField(_('Время начала мероприятия'), null=True, blank=True)
    guest_count = models.PositiveIntegerField(_('Количество гостей'), default=10)
    event_type = models.ForeignKey(
        'catalog.EventType', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders', verbose_name=_('Тип мероприятия')
    )
    package = models.ForeignKey(
        'catalog.Package', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders', verbose_name=_('Выбранный пакет')
    )
    status = models.CharField(
        _('Статус заказа'), max_length=25,
        choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True
    )

    # Адрес и логистика
    address = models.CharField(_('Адрес мероприятия'), max_length=255, blank=True)
    need_delivery = models.BooleanField(_('Требуется доставка'), default=False)
    delivery_zone = models.ForeignKey(
        'services.DeliveryZone', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders', verbose_name=_('Зона доставки')
    )
    need_setup = models.BooleanField(_('Требуется монтаж'), default=False)
    need_teardown = models.BooleanField(_('Требуется демонтаж'), default=False)

    # Финансы (в тенге ₸)
    items_price = models.DecimalField(_('Стоимость аренды товаров'), max_digits=12, decimal_places=2, default=0)
    delivery_price = models.DecimalField(_('Стоимость доставки'), max_digits=10, decimal_places=2, default=0)
    services_price = models.DecimalField(_('Стоимость услуг (монтаж/демонтаж/декор)'), max_digits=10, decimal_places=2, default=0)
    deposit_price = models.DecimalField(_('Залог'), max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField(_('Итоговая сумма'), max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(_('Оплаченная сумма'), max_digits=12, decimal_places=2, default=0)

    # Комментарии
    comment = models.TextField(_('Комментарий клиента'), blank=True)
    manager_comment = models.TextField(_('Комментарий менеджера'), blank=True)

    # Исходный канал заявки
    source = models.CharField(_('Источник'), max_length=30, default='website', choices=[
        ('website', 'Веб-сайт'),
        ('telegram_bot', 'Telegram-бот'),
        ('manager', 'Менеджер вручную')
    ])

    created_at = models.DateTimeField(_('Создан'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Обновлен'), auto_now=True)

    class Meta:
        verbose_name = _('Заказ')
        verbose_name_plural = _('Заказы')
        ordering = ['-created_at']

    def __str__(self):
        return f"№{self.order_number} — {self.client.name} ({self.event_date})"

    @classmethod
    def generate_order_number(cls):
        """Генерация уникального номера заказа #ORD-XXXX"""
        last_order = cls.objects.order_by('-id').first()
        next_id = 1001 if not last_order else last_order.id + 1001
        return f"ORD-{next_id}"

    @property
    def remaining_amount(self):
        """Остаток к доплате"""
        return max(0, self.total_price - self.paid_amount)

    @property
    def is_reserved(self):
        """Считается ли товар зарезервированным"""
        return self.status in [
            self.STATUS_CONFIRMED,
            self.STATUS_PAYMENT_PENDING,
            self.STATUS_PAID,
            self.STATUS_PREPARING,
            self.STATUS_READY,
            self.STATUS_DELIVERING,
            self.STATUS_EVENT,
        ]

    def recalculate_totals(self, save=True):
        """Пересчет всех сумм заказа"""
        items_sum = sum(item.total_price for item in self.items.all())
        services_sum = sum(srv.total_price for srv in self.services.all())
        deposits_sum = sum(item.product.deposit * item.quantity for item in self.items.all() if item.product)

        self.items_price = items_sum
        self.services_price = services_sum
        self.deposit_price = deposits_sum
        self.total_price = items_sum + services_sum + self.delivery_price
        if save:
            self.save(update_fields=['items_price', 'services_price', 'deposit_price', 'total_price'])

    def check_availability(self):
        """
        Проверить физическую доступность всех позиций на дату заказа.
        Возвращает: (is_available, issues_list)
        """
        from apps.warehouse.models import StockReservation
        issues = []
        for item in self.items.select_related('product'):
            product = item.product
            # Считаем уже зарезервированное количество на эту дату другими заказами
            reserved = StockReservation.objects.filter(
                product=product,
                date=self.event_date,
                is_active=True
            ).exclude(order=self).aggregate(total=models.Sum('quantity'))['total'] or 0

            available = max(0, product.available_quantity - reserved)
            if available < item.quantity:
                issues.append({
                    'product': product,
                    'requested': item.quantity,
                    'available': available,
                    'shortage': item.quantity - available
                })
        return len(issues) == 0, issues

    def sync_reservations(self):
        """Синхронизировать складские резервы в зависимости от статуса"""
        from apps.warehouse.models import StockReservation
        if self.is_reserved:
            # Создаем или обновляем резервы
            for item in self.items.select_related('product'):
                StockReservation.objects.update_or_create(
                    order=self,
                    product=item.product,
                    defaults={
                        'date': self.event_date,
                        'quantity': item.quantity,
                        'is_active': True
                    }
                )
        else:
            # Если отменен или завершен или просто новая заявка без резерва
            StockReservation.objects.filter(order=self).update(is_active=False)


class OrderItem(models.Model):
    """Позиция товара в заказе"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', verbose_name=_('Заказ'))
    product = models.ForeignKey('catalog.Product', on_delete=models.PROTECT, related_name='order_items', verbose_name=_('Товар'))
    quantity = models.PositiveIntegerField(_('Количество'), default=1)
    rental_price = models.DecimalField(_('Цена за единицу (₸)'), max_digits=10, decimal_places=2)
    total_price = models.DecimalField(_('Общая стоимость (₸)'), max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = _('Позиция заказа')
        verbose_name_plural = _('Позиции заказа')

    def __str__(self):
        return f"{self.product.name} × {self.quantity}"

    def save(self, *args, **kwargs):
        if not self.rental_price and self.product:
            self.rental_price = self.product.rental_price
        self.total_price = self.rental_price * self.quantity
        super().save(*args, **kwargs)


class OrderService(models.Model):
    """Услуга в заказе (монтаж, демонтаж, сервировка, зона доставки и т.д.)"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='services', verbose_name=_('Заказ'))
    service = models.ForeignKey('services.Service', on_delete=models.PROTECT, verbose_name=_('Услуга'))
    quantity = models.PositiveIntegerField(_('Количество/Объем'), default=1)
    price = models.DecimalField(_('Стоимость за единицу (₸)'), max_digits=10, decimal_places=2)
    total_price = models.DecimalField(_('Общая сумма (₸)'), max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = _('Услуга в заказе')
        verbose_name_plural = _('Услуги в заказе')

    def __str__(self):
        return f"{self.service.name} ({self.total_price} ₸)"

    def save(self, *args, **kwargs):
        self.total_price = self.price * self.quantity
        super().save(*args, **kwargs)


class OrderStatusHistory(models.Model):
    """История изменения статусов заказа"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history', verbose_name=_('Заказ'))
    old_status = models.CharField(_('Старый статус'), max_length=25, blank=True)
    new_status = models.CharField(_('Новый статус'), max_length=25)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name=_('Кто изменил'))
    comment = models.TextField(_('Комментарий к смене статуса'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('История статуса заказа')
        verbose_name_plural = _('История статусов заказов')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_number}: {self.old_status} -> {self.new_status}"
