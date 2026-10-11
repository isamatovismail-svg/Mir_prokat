import json
from datetime import datetime
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, models
from django.db.models import Sum
from .models import Order, OrderItem, OrderService, OrderStatusHistory
from apps.clients.models import Client
from apps.catalog.models import Product, Package, EventType
from apps.services.models import Service, DeliveryZone
from apps.notifications.models import notify_admin_new_order


@csrf_exempt
def submit_order_view(request):
    """
    Создание заявки на прокат с серверной валидацией цен и проверкой склада
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Метод не поддерживается'}, status=405)

    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body.decode('utf-8'))
        else:
            data = request.POST.dict()
            if 'items' in data and isinstance(data['items'], str):
                data['items'] = json.loads(data['items'])
            if 'services' in data and isinstance(data['services'], str):
                data['services'] = json.loads(data['services'])

        # 1. Извлекаем и проверяем контактные данные клиента
        client_name = data.get('client_name', '').strip()
        client_phone = data.get('client_phone', '').strip()
        client_telegram = data.get('client_telegram', '').strip()

        if not client_name or not client_phone:
            return JsonResponse({'success': False, 'error': 'Укажите ваше имя и номер телефона'}, status=400)

        # 2. Дата мероприятия
        event_date_str = data.get('event_date')
        if not event_date_str:
            return JsonResponse({'success': False, 'error': 'Укажите дату мероприятия'}, status=400)

        try:
            event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Некорректная дата мероприятия'}, status=400)

        # 3. Детали мероприятия
        event_time_str = data.get('event_time', '')
        event_time = None
        if event_time_str:
            try:
                event_time = datetime.strptime(event_time_str, '%H:%M').time()
            except ValueError:
                pass

        guest_count = int(data.get('guest_count', 10))
        address = data.get('address', '').strip()
        comment = data.get('comment', '').strip()

        event_type_id = data.get('event_type_id')
        event_type = EventType.objects.filter(id=event_type_id).first() if event_type_id else None

        package_id = data.get('package_id')
        package = Package.objects.filter(id=package_id).first() if package_id else None

        # 4. Товары в заказе
        raw_items = data.get('items', [])
        # Если передан package_id, но нет явных items, генерируем их из пакета
        if package and not raw_items:
            for pkg_item in package.items.select_related('product'):
                qty = pkg_item.get_quantity_for_guests(guest_count)
                raw_items.append({'product_id': pkg_item.product.id, 'quantity': qty})

        # 5. СЕРВЕРНАЯ ПРОВЕРКА НАЛИЧИЯ (защита от двойного бронирования)
        from apps.warehouse.models import StockReservation
        availability_issues = []
        validated_items = []

        for itm in raw_items:
            p_id = itm.get('product_id')
            qty = int(itm.get('quantity', 0))
            if qty <= 0:
                continue

            product = Product.objects.filter(id=p_id, is_active=True).first()
            if not product:
                continue

            # Проверяем занятость на дату
            reserved = StockReservation.objects.filter(
                product=product,
                date=event_date,
                is_active=True
            ).aggregate(total=models.Sum('quantity'))['total'] or 0

            available = max(0, product.available_quantity - reserved)
            if available < qty:
                availability_issues.append(
                    f"«{product.name}»: запрошено {qty} шт., но на {event_date.strftime('%d.%m.%Y')} свободно только {available} шт."
                )
            else:
                validated_items.append({
                    'product': product,
                    'quantity': qty,
                    'unit_price': product.rental_price,
                    'total_price': product.rental_price * qty
                })

        if availability_issues:
            return JsonResponse({
                'success': False,
                'error': 'Недостаточно товара на выбранную дату: ' + '; '.join(availability_issues),
                'issues': availability_issues
            }, status=400)

        # 6. Услуги и логистика
        need_delivery = bool(data.get('need_delivery'))
        delivery_zone_id = data.get('delivery_zone_id')
        delivery_zone = DeliveryZone.objects.filter(id=delivery_zone_id).first() if delivery_zone_id else None
        delivery_price = delivery_zone.price if delivery_zone else Decimal('0.00')
        if need_delivery and not delivery_zone:
            delivery_price = Decimal(data.get('delivery_price', '5000.00'))

        need_setup = bool(data.get('need_setup'))
        need_teardown = bool(data.get('need_teardown'))

        # Транзакционное создание заявки
        with transaction.atomic():
            # Находим или создаем клиента
            client, _ = Client.objects.get_or_create(
                phone=client_phone,
                defaults={
                    'name': client_name,
                    'telegram': client_telegram,
                }
            )
            # Обновляем имя или telegram, если изменились
            if client_name and client.name != client_name:
                client.name = client_name
            if client_telegram and client.telegram != client_telegram:
                client.telegram = client_telegram
            client.save()

            # Создаем заказ
            order = Order.objects.create(
                order_number=Order.generate_order_number(),
                client=client,
                event_date=event_date,
                event_time=event_time,
                guest_count=guest_count,
                event_type=event_type,
                package=package,
                status=Order.STATUS_NEW,
                address=address,
                need_delivery=need_delivery,
                delivery_zone=delivery_zone,
                delivery_price=delivery_price,
                need_setup=need_setup,
                need_teardown=need_teardown,
                comment=comment,
                source=data.get('source', 'website')
            )

            # Создаем позиции товаров
            items_total = Decimal('0.00')
            deposits_total = Decimal('0.00')

            for item in validated_items:
                prod = item['product']
                qty = item['quantity']
                price = item['unit_price']
                subtotal = item['total_price']

                OrderItem.objects.create(
                    order=order,
                    product=prod,
                    quantity=qty,
                    rental_price=price,
                    total_price=subtotal
                )
                items_total += subtotal
                deposits_total += prod.deposit * qty

            # Создаем выбранные услуги
            services_total = Decimal('0.00')
            services_ids = data.get('services', [])
            if isinstance(services_ids, list):
                for s_id in services_ids:
                    srv = Service.objects.filter(id=s_id, is_active=True).first()
                    if srv:
                        s_price = srv.calculate_price(guest_count)
                        OrderService.objects.create(
                            order=order,
                            service=srv,
                            quantity=1,
                            price=s_price,
                            total_price=s_price
                        )
                        services_total += s_price

            # Обновляем итоговые суммы
            order.items_price = items_total
            order.services_price = services_total
            order.deposit_price = deposits_total
            order.total_price = items_total + services_total + delivery_price
            order.save()

            # Записываем историю статуса
            OrderStatusHistory.objects.create(
                order=order,
                old_status='',
                new_status=Order.STATUS_NEW,
                comment='Заявка создана клиентом на сайте'
            )

        # 7. Отправляем уведомление администратору в Telegram
        try:
            notify_admin_new_order(order)
        except Exception as e:
            pass

        return JsonResponse({
            'success': True,
            'order_number': order.order_number,
            'order_id': order.id,
            'redirect_url': f'/orders/{order.order_number}/'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Произошла ошибка: {str(e)}'}, status=500)


def order_detail_view(request, order_number):
    """
    Публичная страница просмотра и отслеживания заказа клиентом
    /orders/ORD-1042/
    """
    order = get_object_or_404(
        Order.objects.select_related('client', 'package', 'event_type', 'delivery_zone')
        .prefetch_related('items__product', 'services__service', 'status_history'),
        order_number=order_number
    )

    # Статусы в виде шагов прогресса для клиента
    steps = [
        {'code': 'NEW', 'name': 'Заявка принята', 'icon': '📝'},
        {'code': 'CONFIRMED', 'name': 'Подтвержден', 'icon': '✅'},
        {'code': 'PREPARING', 'name': 'Сборка на складе', 'icon': '📦'},
        {'code': 'DELIVERING', 'name': 'В доставке', 'icon': '🚚'},
        {'code': 'COMPLETED', 'name': 'Завершен', 'icon': '🎉'},
    ]

    status_weights = {
        'NEW': 1, 'PENDING': 1,
        'CONFIRMED': 2, 'PAYMENT_PENDING': 2, 'PAID': 2,
        'PREPARING': 3, 'READY': 3,
        'DELIVERING': 4, 'EVENT': 4,
        'COMPLETED': 5,
        'CANCELLED': 0,
    }
    current_weight = status_weights.get(order.status, 1)

    context = {
        'order': order,
        'steps': steps,
        'current_weight': current_weight,
    }
    return render(request, 'site/order_detail.html', context)


def cart_view(request):
    """Страница корзины / оформления заказа"""
    delivery_zones = DeliveryZone.objects.filter(is_active=True).order_by('order')
    services = Service.objects.filter(is_active=True).order_by('order')
    event_types = EventType.objects.filter(is_active=True).order_by('order')

    context = {
        'delivery_zones': delivery_zones,
        'services': services,
        'event_types': event_types,
    }
    return render(request, 'site/cart.html', context)
