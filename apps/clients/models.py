from django.db import models
from django.utils.translation import gettext_lazy as _


class Client(models.Model):
    """Клиент системы"""
    name = models.CharField(_('Имя'), max_length=200)
    phone = models.CharField(_('Телефон'), max_length=20, unique=True)
    telegram = models.CharField(_('Telegram'), max_length=100, blank=True)
    telegram_id = models.BigIntegerField(_('Telegram ID'), null=True, blank=True, unique=True)
    email = models.EmailField(_('Email'), blank=True)
    comment = models.TextField(_('Комментарий менеджера'), blank=True)
    is_vip = models.BooleanField(_('VIP-клиент'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Клиент')
        verbose_name_plural = _('Клиенты')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.phone})'

    @property
    def orders_count(self):
        return self.orders.count()

    @property
    def total_spent(self):
        from django.db.models import Sum
        result = self.orders.filter(
            status__in=['COMPLETED', 'PAID', 'PREPARING', 'READY', 'DELIVERING', 'EVENT']
        ).aggregate(total=Sum('total_price'))
        return result['total'] or 0

    @property
    def last_order(self):
        return self.orders.order_by('-created_at').first()
