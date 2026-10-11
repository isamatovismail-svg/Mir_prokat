from django.db import models
from django.utils.translation import gettext_lazy as _


class Service(models.Model):
    """Дополнительные услуги: монтаж, демонтаж, сервировка, оформление, уборка"""
    SERVICE_TYPE_CHOICES = [
        ('delivery', _('Доставка')),
        ('setup', _('Монтаж')),
        ('teardown', _('Демонтаж')),
        ('serving', _('Сервировка')),
        ('decor', _('Оформление')),
        ('cleaning', _('Уборка')),
        ('other', _('Другое')),
    ]

    name = models.CharField(_('Название услуги'), max_length=150)
    slug = models.SlugField(_('URL'), unique=True)
    service_type = models.CharField(_('Тип услуги'), max_length=30, choices=SERVICE_TYPE_CHOICES, default='other')
    description = models.TextField(_('Описание'), blank=True)
    price = models.DecimalField(_('Базовая цена (₸)'), max_digits=10, decimal_places=2, default=0)
    is_per_guest = models.BooleanField(_('Цена рассчитывается за гостя'), default=False)
    price_per_guest = models.DecimalField(_('Цена за гостя (₸)'), max_digits=10, decimal_places=2, default=0)
    icon = models.CharField(_('Иконка (emoji)'), max_length=10, default='🔧')
    is_active = models.BooleanField(_('Активна'), default=True)
    order = models.PositiveIntegerField(_('Порядок'), default=0)

    class Meta:
        verbose_name = _('Дополнительная услуга')
        verbose_name_plural = _('Дополнительные услуги')
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def calculate_price(self, guest_count=1):
        if self.is_per_guest and guest_count:
            return self.price_per_guest * guest_count
        return self.price


class DeliveryZone(models.Model):
    """Зона доставки и фиксированная стоимость"""
    name = models.CharField(_('Название зоны'), max_length=150)
    description = models.TextField(_('Описание зоны/границы'), blank=True)
    price = models.DecimalField(_('Стоимость доставки (₸)'), max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(_('Активна'), default=True)
    order = models.PositiveIntegerField(_('Порядок'), default=0)

    class Meta:
        verbose_name = _('Зона доставки')
        verbose_name_plural = _('Зоны доставки')
        ordering = ['order', 'price']

    def __str__(self):
        return f"{self.name} — {self.price:,.0f} ₸"
