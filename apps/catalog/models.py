from django.db import models
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    """Категория товара (стулья, столы, посуда и т.д.)"""
    name = models.CharField(_('Название'), max_length=100)
    slug = models.SlugField(_('URL'), unique=True)
    icon = models.CharField(_('Иконка (emoji)'), max_length=10, default='📦')
    description = models.TextField(_('Описание'), blank=True)
    image = models.ImageField(_('Изображение'), upload_to='categories/', blank=True, null=True)
    order = models.PositiveIntegerField(_('Порядок'), default=0)
    is_active = models.BooleanField(_('Активна'), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Категория')
        verbose_name_plural = _('Категории')
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Product(models.Model):
    """Товар для аренды"""
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        related_name='products', verbose_name=_('Категория')
    )
    name = models.CharField(_('Название'), max_length=200)
    slug = models.SlugField(_('URL'), unique=True)
    description = models.TextField(_('Описание'), blank=True)
    image = models.ImageField(_('Фото'), upload_to='products/', blank=True, null=True)

    # Количество
    total_quantity = models.PositiveIntegerField(_('Всего на складе'), default=0)
    in_repair = models.PositiveIntegerField(_('На ремонте'), default=0)
    min_stock = models.PositiveIntegerField(_('Минимальный остаток'), default=5)

    # Цены
    rental_price = models.DecimalField(_('Цена аренды (₸)'), max_digits=10, decimal_places=2, default=0)
    deposit = models.DecimalField(_('Залог (₸)'), max_digits=10, decimal_places=2, default=0)

    # Правило расчёта (количество на 1 гостя или на N гостей)
    guests_per_unit = models.PositiveIntegerField(
        _('Гостей на единицу'),
        default=1,
        help_text='Например: 10 — значит 1 единица на 10 гостей (для столов). 1 — одна единица на гостя.'
    )

    is_active = models.BooleanField(_('Активен'), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Товар')
        verbose_name_plural = _('Товары')
        ordering = ['category', 'name']

    def __str__(self):
        return self.name

    @property
    def available_quantity(self):
        """Доступное количество (без учёта бронирований на дату)"""
        return max(0, self.total_quantity - self.in_repair)

    def available_on_date(self, date):
        """Доступное количество на конкретную дату с учётом всех бронирований"""
        from apps.warehouse.models import StockReservation
        reserved = StockReservation.objects.filter(
            product=self,
            date=date,
            is_active=True
        ).aggregate(total=models.Sum('quantity'))['total'] or 0
        return max(0, self.available_quantity - reserved)

    def quantity_for_guests(self, guest_count):
        """Рассчитать количество товара для N гостей"""
        import math
        return math.ceil(guest_count / self.guests_per_unit)


class EventType(models.Model):
    """Тип мероприятия"""
    name = models.CharField(_('Название'), max_length=100)
    slug = models.SlugField(_('URL'), unique=True)
    icon = models.CharField(_('Иконка (emoji)'), max_length=10, default='🎉')
    description = models.TextField(_('Описание'), blank=True)
    is_active = models.BooleanField(_('Активен'), default=True)
    order = models.PositiveIntegerField(_('Порядок'), default=0)

    class Meta:
        verbose_name = _('Тип мероприятия')
        verbose_name_plural = _('Типы мероприятий')
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Package(models.Model):
    """Готовый пакет для мероприятия (BASIC / STANDARD / PREMIUM)"""
    TIER_BASIC = 'basic'
    TIER_STANDARD = 'standard'
    TIER_PREMIUM = 'premium'
    TIER_CHOICES = [
        (TIER_BASIC, 'BASIC'),
        (TIER_STANDARD, 'STANDARD'),
        (TIER_PREMIUM, 'PREMIUM'),
    ]

    name = models.CharField(_('Название'), max_length=100)
    slug = models.SlugField(_('URL'), unique=True)
    tier = models.CharField(_('Уровень'), max_length=20, choices=TIER_CHOICES, default=TIER_BASIC)
    description = models.TextField(_('Описание'), blank=True)
    image = models.ImageField(_('Фото'), upload_to='packages/', blank=True, null=True)

    # Базовая цена рассчитывается автоматически из товаров, но можно задать вручную
    base_price_override = models.DecimalField(
        _('Фиксированная цена (если задана, используется вместо расчётной)'),
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_per_guest = models.DecimalField(
        _('Цена за гостя (если 0 — рассчитывается из товаров)'),
        max_digits=10, decimal_places=2, default=0
    )

    is_active = models.BooleanField(_('Активен'), default=True)
    is_featured = models.BooleanField(_('Рекомендуемый'), default=False)
    order = models.PositiveIntegerField(_('Порядок отображения'), default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Пакет')
        verbose_name_plural = _('Пакеты')
        ordering = ['order', 'tier']

    def __str__(self):
        return self.name

    def calculate_price(self, guest_count):
        """Рассчитать стоимость пакета для N гостей"""
        if self.base_price_override:
            return self.base_price_override
        if self.price_per_guest > 0:
            return self.price_per_guest * guest_count
        # Рассчитываем из состава
        total = 0
        for item in self.items.select_related('product'):
            qty = item.get_quantity_for_guests(guest_count)
            total += qty * item.product.rental_price
        return total

    def get_items_for_guests(self, guest_count):
        """Получить список позиций с количеством для N гостей"""
        result = []
        for item in self.items.select_related('product'):
            qty = item.get_quantity_for_guests(guest_count)
            result.append({
                'product': item.product,
                'quantity': qty,
                'price': qty * item.product.rental_price,
            })
        return result


class PackageItem(models.Model):
    """Товар в пакете с правилом расчёта количества"""
    package = models.ForeignKey(
        Package, on_delete=models.CASCADE,
        related_name='items', verbose_name=_('Пакет')
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        related_name='package_items', verbose_name=_('Товар')
    )
    # Коэффициент: сколько единиц товара на 1 гостя
    quantity_per_guest = models.DecimalField(
        _('Количество на гостя'),
        max_digits=6, decimal_places=3, default=1.0,
        help_text='0.1 = 1 стол на 10 гостей; 1 = 1 стул на гостя; 2 = 2 бокала на гостя'
    )
    # Минимальное количество
    min_quantity = models.PositiveIntegerField(_('Минимальное количество'), default=1)
    order = models.PositiveIntegerField(_('Порядок'), default=0)

    class Meta:
        verbose_name = _('Товар в пакете')
        verbose_name_plural = _('Товары в пакете')
        ordering = ['order']
        unique_together = ['package', 'product']

    def __str__(self):
        return f'{self.package.name} — {self.product.name}'

    def get_quantity_for_guests(self, guest_count):
        import math
        qty = math.ceil(float(self.quantity_per_guest) * guest_count)
        return max(qty, self.min_quantity)
