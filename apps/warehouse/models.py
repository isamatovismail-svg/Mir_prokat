from django.db import models
from django.utils.translation import gettext_lazy as _


class StockReservation(models.Model):
    """Резерв товара на конкретную дату для конкретного заказа"""
    product = models.ForeignKey(
        'catalog.Product', on_delete=models.CASCADE,
        related_name='reservations', verbose_name=_('Товар')
    )
    order = models.ForeignKey(
        'orders.Order', on_delete=models.CASCADE,
        related_name='reservations', verbose_name=_('Заказ')
    )
    date = models.DateField(_('Дата мероприятия'))
    quantity = models.PositiveIntegerField(_('Количество'))
    is_active = models.BooleanField(_('Активен'), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Резерв')
        verbose_name_plural = _('Резервы')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.product.name} × {self.quantity} на {self.date}'

    @classmethod
    def get_reserved_quantity(cls, product, date):
        """Получить суммарный резерв по товару на дату"""
        result = cls.objects.filter(
            product=product,
            date=date,
            is_active=True
        ).aggregate(total=models.Sum('quantity'))
        return result['total'] or 0

    @classmethod
    def get_available_quantity(cls, product, date):
        """Получить доступное количество товара на дату"""
        reserved = cls.get_reserved_quantity(product, date)
        return max(0, product.available_quantity - reserved)

    @classmethod
    def check_availability(cls, product, date, quantity, exclude_order=None):
        """Проверить, доступно ли указанное количество на дату"""
        qs = cls.objects.filter(
            product=product,
            date=date,
            is_active=True
        )
        if exclude_order:
            qs = qs.exclude(order=exclude_order)
        reserved = qs.aggregate(total=models.Sum('quantity'))['total'] or 0
        available = max(0, product.available_quantity - reserved)
        return available >= quantity, available
