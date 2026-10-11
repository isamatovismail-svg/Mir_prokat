from datetime import date
from decimal import Decimal
from django.test import TestCase, Client
from apps.catalog.models import Category, Product, Package, PackageItem, EventType
from apps.orders.models import Order, OrderItem
from apps.warehouse.models import StockReservation
from apps.clients.models import Client as RentalClient


class RentalSystemTests(TestCase):
    def setUp(self):
        self.client_http = Client()

        # Создаем категорию и товары
        self.cat_chairs = Category.objects.create(name='Стулья', slug='chairs')
        self.cat_tables = Category.objects.create(name='Столы', slug='tables')

        self.chair = Product.objects.create(
            name='Банкетный стул',
            slug='banket-chair',
            category=self.cat_chairs,
            total_quantity=200,
            in_repair=0,
            min_stock=20,
            rental_price=Decimal('500.00'),
            deposit=Decimal('1000.00'),
            guests_per_unit=1
        )

        self.table = Product.objects.create(
            name='Банкетный стол (10 чел)',
            slug='banket-table',
            category=self.cat_tables,
            total_quantity=20,
            in_repair=0,
            min_stock=2,
            rental_price=Decimal('3500.00'),
            deposit=Decimal('5000.00'),
            guests_per_unit=10
        )

        # Пакет STANDARD
        self.pkg = Package.objects.create(
            name='STANDARD',
            slug='standard',
            tier=Package.TIER_STANDARD
        )
        PackageItem.objects.create(
            package=self.pkg,
            product=self.chair,
            quantity_per_guest=Decimal('1.0')
        )
        PackageItem.objects.create(
            package=self.pkg,
            product=self.table,
            quantity_per_guest=Decimal('0.1')
        )

        self.event_type = EventType.objects.create(name='Свадьба', slug='wedding')
        self.test_date = date(2026, 10, 15)

    def test_package_item_calculation_for_guests(self):
        """Проверка автоматического расчёта количества под число гостей"""
        items_100 = self.pkg.get_items_for_guests(100)
        items_dict = {i['product'].slug: i['quantity'] for i in items_100}

        self.assertEqual(items_dict['banket-chair'], 100)
        self.assertEqual(items_dict['banket-table'], 10)

        # Пересчет на 150 гостей
        items_150 = self.pkg.get_items_for_guests(150)
        items_150_dict = {i['product'].slug: i['quantity'] for i in items_150}
        self.assertEqual(items_150_dict['banket-chair'], 150)
        self.assertEqual(items_150_dict['banket-table'], 15)

    def test_prevent_double_booking(self):
        """Проверка предотвращения двойного бронирования при нехватке товара"""
        # Клиент 1 бронирует 120 стульев
        client1 = RentalClient.objects.create(name='Иван', phone='+77770001122')
        ord1 = Order.objects.create(
            order_number='ORD-TEST-1',
            client=client1,
            event_date=self.test_date,
            guest_count=120,
            status=Order.STATUS_CONFIRMED
        )
        OrderItem.objects.create(
            order=ord1, product=self.chair, quantity=120, rental_price=Decimal('500.00'), total_price=Decimal('60000.00')
        )
        ord1.sync_reservations()

        # Доступно стульев на эту дату: 200 - 120 = 80
        avail = self.chair.available_on_date(self.test_date)
        self.assertEqual(avail, 80)

        # Клиент 2 пробует заказать 100 стульев на ту же дату через API
        payload = {
            'client_name': 'Арман',
            'client_phone': '+77779998877',
            'event_date': '2026-10-15',
            'guest_count': 100,
            'items': [
                {'product_id': self.chair.id, 'quantity': 100}
            ]
        }
        response = self.client_http.post(
            '/orders/submit/',
            data=payload,
            content_type='application/json'
        )
        # Сервер должен отклонить заявку с ошибкой о дефиците
        self.assertEqual(response.status_code, 400)
        res_data = response.json()
        self.assertFalse(res_data['success'])
        self.assertIn('Недостаточно товара', res_data['error'])

    def test_order_submission_success(self):
        """Успешное создание заказа, когда товаров достаточно"""
        payload = {
            'client_name': 'Алия',
            'client_phone': '+77011112233',
            'client_telegram': '@aliya',
            'event_date': '2026-10-20',
            'guest_count': 50,
            'package_id': self.pkg.id,
            'address': 'Алматы, Медео',
            'need_delivery': True
        }
        response = self.client_http.post(
            '/orders/submit/',
            data=payload,
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['order_number'].startswith('ORD-'))

        # Проверяем запись в БД
        order = Order.objects.get(order_number=data['order_number'])
        self.assertEqual(order.client.name, 'Алия')
        self.assertEqual(order.guest_count, 50)
        self.assertEqual(order.status, Order.STATUS_NEW)
        self.assertGreater(order.total_price, 0)
