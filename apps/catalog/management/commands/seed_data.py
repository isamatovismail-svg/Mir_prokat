from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.catalog.models import Category, Product, Package, PackageItem, EventType
from apps.services.models import Service, DeliveryZone
from apps.clients.models import Client
from apps.orders.models import Order, OrderItem, OrderService, OrderStatusHistory
from apps.warehouse.models import StockReservation

User = get_user_model()


class Command(BaseCommand):
    help = 'Заполняет базу данных первоначальными демо-данными для проката'

    def handle(self, *args, **options):
        self.stdout.write('Запуск сидирования базы данных...')

        # 1. Superuser
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@mirprokat.kz', 'admin123')
            self.stdout.write(self.style.SUCCESS('Суперпользователь создан: admin / admin123'))

        # 2. Категории
        categories_data = [
            {'name': 'Стулья', 'slug': 'stulya', 'icon': '🪑', 'order': 1},
            {'name': 'Столы', 'slug': 'stoly', 'icon': '🪵', 'order': 2},
            {'name': 'Посуда', 'slug': 'posuda', 'icon': '🍽', 'order': 3},
            {'name': 'Бокалы и стаканы', 'slug': 'bokaly', 'icon': '🥂', 'order': 4},
            {'name': 'Приборы', 'slug': 'pribory', 'icon': '🍴', 'order': 5},
            {'name': 'Текстиль', 'slug': 'tekstil', 'icon': '🧵', 'order': 6},
            {'name': 'Декор и свет', 'slug': 'dekor', 'icon': '🎀', 'order': 7},
            {'name': 'Оформление', 'slug': 'oformlenie', 'icon': '🎉', 'order': 8},
        ]
        cat_map = {}
        for c in categories_data:
            cat, _ = Category.objects.get_or_create(slug=c['slug'], defaults=c)
            cat_map[c['slug']] = cat

        # 3. Товары
        products_data = [
            {
                'name': 'Стул банкетный классический белый',
                'slug': 'stul-banketny-bely',
                'category': cat_map['stulya'],
                'total_quantity': 250,
                'in_repair': 5,
                'min_stock': 20,
                'rental_price': Decimal('500.00'),
                'deposit': Decimal('1000.00'),
                'guests_per_unit': 1,
                'description': 'Элегантный белый банкетный стул с мягким сиденьем. Идеален для свадеб и юбилеев.'
            },
            {
                'name': 'Стул Кьявари золотой (Chiavari)',
                'slug': 'stul-chiavari-gold',
                'category': cat_map['stulya'],
                'total_quantity': 180,
                'in_repair': 0,
                'min_stock': 20,
                'rental_price': Decimal('850.00'),
                'deposit': Decimal('1500.00'),
                'guests_per_unit': 1,
                'description': 'Премиальный стул Кьявари золотого цвета. Украсит любое торжественное событие.'
            },
            {
                'name': 'Стол круглый банкетный (d=180 см на 10 персон)',
                'slug': 'stol-krugly-180',
                'category': cat_map['stoly'],
                'total_quantity': 35,
                'in_repair': 1,
                'min_stock': 5,
                'rental_price': Decimal('3500.00'),
                'deposit': Decimal('5000.00'),
                'guests_per_unit': 10,
                'description': 'Классический банкетный круглый стол диаметром 180 см. Рассчитан ровно на 10 человек.'
            },
            {
                'name': 'Стол прямоугольный 180×80 см',
                'slug': 'stol-pryamougolny-180',
                'category': cat_map['stoly'],
                'total_quantity': 40,
                'in_repair': 0,
                'min_stock': 5,
                'rental_price': Decimal('3000.00'),
                'deposit': Decimal('4000.00'),
                'guests_per_unit': 6,
                'description': 'Универсальный стол для рассадки или фуршетной линии.'
            },
            {
                'name': 'Стол коктейльный высокий (d=80 см)',
                'slug': 'stol-kokteylny-vysoky',
                'category': cat_map['stoly'],
                'total_quantity': 25,
                'in_repair': 0,
                'min_stock': 3,
                'rental_price': Decimal('2500.00'),
                'deposit': Decimal('3500.00'),
                'guests_per_unit': 4,
                'description': 'Высокий барный стол для велкам-зоны и фуршетов.'
            },
            {
                'name': 'Тарелка подстановочная фарфор (27 см)',
                'slug': 'tarelka-podstanovochnaya',
                'category': cat_map['posuda'],
                'total_quantity': 350,
                'in_repair': 0,
                'min_stock': 30,
                'rental_price': Decimal('150.00'),
                'deposit': Decimal('300.00'),
                'guests_per_unit': 1,
                'description': 'Белоснежный ресторанный фарфор европейского стандарта.'
            },
            {
                'name': 'Тарелка десертная фарфор (20 см)',
                'slug': 'tarelka-desertnaya',
                'category': cat_map['posuda'],
                'total_quantity': 350,
                'in_repair': 0,
                'min_stock': 30,
                'rental_price': Decimal('120.00'),
                'deposit': Decimal('250.00'),
                'guests_per_unit': 1,
                'description': 'Фарфоровая тарелка для салатов, холодных закусок и десертов.'
            },
            {
                'name': 'Бокал для вина (450 мл)',
                'slug': 'bokal-dlya-vina',
                'category': cat_map['bokaly'],
                'total_quantity': 450,
                'in_repair': 0,
                'min_stock': 50,
                'rental_price': Decimal('120.00'),
                'deposit': Decimal('250.00'),
                'guests_per_unit': 1,
                'description': 'Классический хрустальный бокал для красного и белого вина.'
            },
            {
                'name': 'Бокал флейта для шампанского (220 мл)',
                'slug': 'bokal-shampanskoe',
                'category': cat_map['bokaly'],
                'total_quantity': 400,
                'in_repair': 0,
                'min_stock': 50,
                'rental_price': Decimal('120.00'),
                'deposit': Decimal('250.00'),
                'guests_per_unit': 1,
                'description': 'Изящный тонкий бокал для игристого вина.'
            },
            {
                'name': 'Стакан хайбол для воды и сока (330 мл)',
                'slug': 'stakan-haybol',
                'category': cat_map['bokaly'],
                'total_quantity': 500,
                'in_repair': 0,
                'min_stock': 50,
                'rental_price': Decimal('80.00'),
                'deposit': Decimal('150.00'),
                'guests_per_unit': 1,
                'description': 'Универсальный стеклянный стакан для безалкогольных напитков.'
            },
            {
                'name': 'Вилка столовая (сталь)',
                'slug': 'vilka-stolovaya',
                'category': cat_map['pribory'],
                'total_quantity': 450,
                'in_repair': 0,
                'min_stock': 50,
                'rental_price': Decimal('70.00'),
                'deposit': Decimal('100.00'),
                'guests_per_unit': 1,
                'description': 'Качественные полированные столовые вилки.'
            },
            {
                'name': 'Ложка столовая (сталь)',
                'slug': 'lozhka-stolovaya',
                'category': cat_map['pribory'],
                'total_quantity': 450,
                'in_repair': 0,
                'min_stock': 50,
                'rental_price': Decimal('70.00'),
                'deposit': Decimal('100.00'),
                'guests_per_unit': 1,
                'description': 'Глянцевая столовая ложка.'
            },
            {
                'name': 'Нож столовый (сталь)',
                'slug': 'nozh-stolovoy',
                'category': cat_map['pribory'],
                'total_quantity': 450,
                'in_repair': 0,
                'min_stock': 50,
                'rental_price': Decimal('70.00'),
                'deposit': Decimal('100.00'),
                'guests_per_unit': 1,
                'description': 'Столовый нож ресторанного качества.'
            },
            {
                'name': 'Скатерть круглая белая (d=320 см)',
                'slug': 'skatert-kruglaya-belaya',
                'category': cat_map['tekstil'],
                'total_quantity': 50,
                'in_repair': 2,
                'min_stock': 5,
                'rental_price': Decimal('1500.00'),
                'deposit': Decimal('2000.00'),
                'guests_per_unit': 10,
                'description': 'Плотная хлопко-полиэстеровая скатерть в пол для круглого стола d=180 см.'
            },
            {
                'name': 'Салфетка текстильная тканевая (45×45 см)',
                'slug': 'salfetka-tekstilnaya',
                'category': cat_map['tekstil'],
                'total_quantity': 400,
                'in_repair': 0,
                'min_stock': 40,
                'rental_price': Decimal('100.00'),
                'deposit': Decimal('150.00'),
                'guests_per_unit': 1,
                'description': 'Текстильная сервировочная салфетка белого или кремового цвета.'
            },
            {
                'name': 'Арка свадебная кованая / круглая',
                'slug': 'arka-svadebnaya',
                'category': cat_map['dekor'],
                'total_quantity': 6,
                'in_repair': 0,
                'min_stock': 1,
                'rental_price': Decimal('15000.00'),
                'deposit': Decimal('20000.00'),
                'guests_per_unit': 100,
                'description': 'Основа для свадебной церемонии и фотозоны.'
            },
            {
                'name': 'Цветочная композиция на стол гостей',
                'slug': 'cvetochnaya-kompoziciya',
                'category': cat_map['oformlenie'],
                'total_quantity': 30,
                'in_repair': 0,
                'min_stock': 5,
                'rental_price': Decimal('3000.00'),
                'deposit': Decimal('4000.00'),
                'guests_per_unit': 10,
                'description': 'Изящная композиция из премиальных искусственных цветов на высокой стойке.'
            }
        ]

        prod_map = {}
        for p in products_data:
            prod, _ = Product.objects.get_or_create(slug=p['slug'], defaults=p)
            prod_map[p['slug']] = prod

        # 4. Типы мероприятий
        events_data = [
            {'name': 'Свадьба', 'slug': 'wedding', 'icon': '💍', 'order': 1},
            {'name': 'День рождения', 'slug': 'birthday', 'icon': '🎂', 'order': 2},
            {'name': 'Юбилей', 'slug': 'anniversary', 'icon': '🥂', 'order': 3},
            {'name': 'Корпоратив', 'slug': 'corporate', 'icon': '💼', 'order': 4},
            {'name': 'Банкет', 'slug': 'banquet', 'icon': '🍽', 'order': 5},
            {'name': 'Выпускной', 'slug': 'prom', 'icon': '🎓', 'order': 6},
            {'name': 'Детский праздник', 'slug': 'kids', 'icon': '🎈', 'order': 7},
            {'name': 'Фуршет', 'slug': 'buffet', 'icon': '🍾', 'order': 8},
            {'name': 'Другое', 'slug': 'other', 'icon': '✨', 'order': 9},
        ]
        for e in events_data:
            EventType.objects.get_or_create(slug=e['slug'], defaults=e)

        # 5. Услуги и Зоны доставки
        services_data = [
            {'name': 'Монтаж оборудования', 'slug': 'montazh', 'service_type': 'setup', 'price': Decimal('15000.00'), 'is_per_guest': False, 'icon': '🛠', 'order': 1},
            {'name': 'Демонтаж оборудования', 'slug': 'demontazh', 'service_type': 'teardown', 'price': Decimal('10000.00'), 'is_per_guest': False, 'icon': '🧹', 'order': 2},
            {'name': 'Сервировка столов', 'slug': 'servirovka', 'service_type': 'serving', 'price': Decimal('500.00'), 'is_per_guest': True, 'price_per_guest': Decimal('150.00'), 'icon': '🍷', 'order': 3},
            {'name': 'Оформление зоны президиума', 'slug': 'decor-prezidium', 'service_type': 'decor', 'price': Decimal('25000.00'), 'is_per_guest': False, 'icon': '🎀', 'order': 4},
            {'name': 'Уборка после мероприятия', 'slug': 'cleaning', 'service_type': 'cleaning', 'price': Decimal('12000.00'), 'is_per_guest': False, 'icon': '✨', 'order': 5},
        ]
        for s in services_data:
            Service.objects.get_or_create(slug=s['slug'], defaults=s)

        zones_data = [
            {'name': 'Зона 1: В черте города (Алматы)', 'price': Decimal('6000.00'), 'order': 1, 'description': 'Доставка и вывоз в пределах границ города'},
            {'name': 'Зона 2: Пригород (до 20 км)', 'price': Decimal('12000.00'), 'order': 2, 'description': 'Доставка в ближайшие поселки и коттеджные городки'},
            {'name': 'Зона 3: Область (до 50 км)', 'price': Decimal('20000.00'), 'order': 3, 'description': 'Загородные зоны отдыха и загородные комплексы'},
        ]
        for z in zones_data:
            DeliveryZone.objects.get_or_create(name=z['name'], defaults=z)

        # 6. Пакеты: BASIC, STANDARD, PREMIUM
        pkg_basic, _ = Package.objects.get_or_create(
            slug='basic',
            defaults={
                'name': 'BASIC',
                'tier': Package.TIER_BASIC,
                'description': 'Для простого и аккуратного мероприятия. Включает стулья, столы, тарелки, приборы, стаканы и скатерти.',
                'order': 1,
            }
        )
        # Состав BASIC
        basic_items = [
            ('stul-banketny-bely', Decimal('1.0'), 10),      # 1 стул на гостя
            ('stol-krugly-180', Decimal('0.1'), 1),          # 1 стол на 10 гостей
            ('tarelka-podstanovochnaya', Decimal('1.0'), 10),# 1 тарелка на гостя
            ('vilka-stolovaya', Decimal('1.0'), 10),         # 1 вилка
            ('lozhka-stolovaya', Decimal('1.0'), 10),        # 1 ложка
            ('nozh-stolovoy', Decimal('1.0'), 10),           # 1 нож
            ('stakan-haybol', Decimal('1.0'), 10),           # 1 стакан
            ('skatert-kruglaya-belaya', Decimal('0.1'), 1),  # 1 скатерть на стол
        ]
        for p_slug, qty_guest, min_q in basic_items:
            if p_slug in prod_map:
                PackageItem.objects.update_or_create(
                    package=pkg_basic,
                    product=prod_map[p_slug],
                    defaults={'quantity_per_guest': qty_guest, 'min_quantity': min_q}
                )

        pkg_standard, _ = Package.objects.get_or_create(
            slug='standard',
            defaults={
                'name': 'STANDARD',
                'tier': Package.TIER_STANDARD,
                'description': 'Оптимальный и самый популярный выбор. Включает столы, стулья, посуду, текстильные салфетки, бокалы для вина и базовое оформление.',
                'order': 2,
                'is_featured': True,
            }
        )
        standard_items = basic_items + [
            ('bokal-dlya-vina', Decimal('1.0'), 10),
            ('salfetka-tekstilnaya', Decimal('1.0'), 10),
            ('cvetochnaya-kompoziciya', Decimal('0.1'), 1),
        ]
        for p_slug, qty_guest, min_q in standard_items:
            if p_slug in prod_map:
                PackageItem.objects.update_or_create(
                    package=pkg_standard,
                    product=prod_map[p_slug],
                    defaults={'quantity_per_guest': qty_guest, 'min_quantity': min_q}
                )

        pkg_premium, _ = Package.objects.get_or_create(
            slug='premium',
            defaults={
                'name': 'PREMIUM',
                'tier': Package.TIER_PREMIUM,
                'description': 'Премиум-комплект для статусных свадеб и банкетных торжеств. Золотые стулья Кьявари, бокалы под вино и шампанское, десертная посуда, арка и полное оформление.',
                'order': 3,
            }
        )
        premium_items = [
            ('stul-chiavari-gold', Decimal('1.0'), 10),
            ('stol-krugly-180', Decimal('0.1'), 1),
            ('tarelka-podstanovochnaya', Decimal('1.0'), 10),
            ('tarelka-desertnaya', Decimal('1.0'), 10),
            ('vilka-stolovaya', Decimal('1.0'), 10),
            ('lozhka-stolovaya', Decimal('1.0'), 10),
            ('nozh-stolovoy', Decimal('1.0'), 10),
            ('stakan-haybol', Decimal('1.0'), 10),
            ('bokal-dlya-vina', Decimal('1.0'), 10),
            ('bokal-shampanskoe', Decimal('1.0'), 10),
            ('skatert-kruglaya-belaya', Decimal('0.1'), 1),
            ('salfetka-tekstilnaya', Decimal('1.0'), 10),
            ('cvetochnaya-kompoziciya', Decimal('0.1'), 1),
            ('arka-svadebnaya', Decimal('0.01'), 1),
        ]
        for p_slug, qty_guest, min_q in premium_items:
            if p_slug in prod_map:
                PackageItem.objects.update_or_create(
                    package=pkg_premium,
                    product=prod_map[p_slug],
                    defaults={'quantity_per_guest': qty_guest, 'min_quantity': min_q}
                )

        # 7. Клиенты и тестовые заказы для Dashboard/Календаря/Аналитики
        client1, _ = Client.objects.get_or_create(
            phone='+7 777 123 4567',
            defaults={'name': 'Иван Петров', 'telegram': '@ivan_petrov', 'comment': 'Постоянный клиент, организатор'}
        )
        client2, _ = Client.objects.get_or_create(
            phone='+7 701 555 8899',
            defaults={'name': 'Арман Сериков', 'telegram': '@arman_s', 'is_vip': True}
        )
        client3, _ = Client.objects.get_or_create(
            phone='+7 775 333 2211',
            defaults={'name': 'Алия Нурланова', 'telegram': '@aliya_events'}
        )

        today = date.today()

        # Заказ 1: Подтвержден на 15 октября 2026 (как в промпте!)
        sample_date = date(2026, 10, 15)
        if not Order.objects.filter(order_number='ORD-1042').exists():
            ord1 = Order.objects.create(
                order_number='ORD-1042',
                client=client1,
                event_date=sample_date,
                guest_count=100,
                package=pkg_standard,
                status=Order.STATUS_CONFIRMED,
                address='г. Алматы, ул. Достык, 180',
                need_delivery=True,
                delivery_price=Decimal('10000.00'),
                need_setup=True,
                need_teardown=True,
                comment='Свадебный банкет, начало в 16:00'
            )
            # Добавим товары
            for item in pkg_standard.items.all():
                qty = item.get_quantity_for_guests(100)
                OrderItem.objects.create(
                    order=ord1,
                    product=item.product,
                    quantity=qty,
                    rental_price=item.product.rental_price,
                    total_price=item.product.rental_price * qty
                )
            ord1.recalculate_totals()
            ord1.sync_reservations()

        # Заказ 2: Завершен
        if not Order.objects.filter(order_number='ORD-1041').exists():
            ord2 = Order.objects.create(
                order_number='ORD-1041',
                client=client2,
                event_date=today - timedelta(days=2),
                guest_count=120,
                package=pkg_premium,
                status=Order.STATUS_COMPLETED,
                address='Загородный комплекс "Alatau Hills"',
                need_delivery=True,
                delivery_price=Decimal('20000.00'),
                total_price=Decimal('120000.00'),
                paid_amount=Decimal('120000.00')
            )
            for item in pkg_premium.items.all()[:5]:
                qty = item.get_quantity_for_guests(120)
                OrderItem.objects.create(
                    order=ord2,
                    product=item.product,
                    quantity=qty,
                    rental_price=item.product.rental_price,
                    total_price=item.product.rental_price * qty
                )

        # Заказ 3: Новая заявка на сегодня
        if not Order.objects.filter(order_number='ORD-1043').exists():
            ord3 = Order.objects.create(
                order_number='ORD-1043',
                client=client3,
                event_date=today + timedelta(days=5),
                guest_count=50,
                package=pkg_basic,
                status=Order.STATUS_NEW,
                address='г. Алматы, проспект Абая 52',
                need_delivery=True,
                delivery_price=Decimal('6000.00'),
                comment='Юбилей 50 лет'
            )
            for item in pkg_basic.items.all():
                qty = item.get_quantity_for_guests(50)
                OrderItem.objects.create(
                    order=ord3,
                    product=item.product,
                    quantity=qty,
                    rental_price=item.product.rental_price,
                    total_price=item.product.rental_price * qty
                )
            ord3.recalculate_totals()

        self.stdout.write(self.style.SUCCESS('База данных успешно наполнена всеми необходимыми товарами, пакетами и заказами!'))
