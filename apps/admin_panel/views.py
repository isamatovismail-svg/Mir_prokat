from datetime import date, datetime, timedelta
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.db.models import Sum, Count, Q, F
from django.contrib import messages
from apps.orders.models import Order, OrderItem, OrderService, OrderStatusHistory
from apps.catalog.models import Product, Category, Package, PackageItem, EventType
from apps.clients.models import Client
from apps.warehouse.models import StockReservation
from apps.services.models import Service, DeliveryZone
from apps.notifications.models import notify_client_status_update


def is_staff_check(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def admin_login_view(request):
    """Страница входа в панель администратора"""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_panel:dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user and (user.is_staff or user.is_superuser):
            login(request, user)
            next_url = request.GET.get('next', '/admin-panel/')
            return redirect(next_url)
        else:
            error = 'Неверный логин, пароль или нет прав администратора'

    return render(request, 'admin_panel/login.html', {'error': error})


def admin_logout_view(request):
    """Выход из панели администратора"""
    logout(request)
    return redirect('admin_panel:login')


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def dashboard_view(request):
    """Главная страница дашборда: сводка ключевых показателей"""
    today = date.today()

    new_orders_count = Order.objects.filter(status=Order.STATUS_NEW).count()
    active_orders_count = Order.objects.filter(
        status__in=[
            Order.STATUS_CONFIRMED, Order.STATUS_PAYMENT_PENDING,
            Order.STATUS_PAID, Order.STATUS_PREPARING,
            Order.STATUS_READY, Order.STATUS_DELIVERING
        ]
    ).count()
    events_today_count = Order.objects.filter(event_date=today).exclude(status=Order.STATUS_CANCELLED).count()

    # Загрузка склада (% забронированных товаров на сегодня)
    total_stock = Product.objects.filter(is_active=True).aggregate(s=Sum('total_quantity'))['s'] or 1
    reserved_today = StockReservation.objects.filter(date=today, is_active=True).aggregate(s=Sum('quantity'))['s'] or 0
    stock_load_percent = min(100, round((reserved_today / total_stock) * 100))

    # Последние заказы
    recent_orders = Order.objects.select_related('client', 'package').order_by('-created_at')[:8]

    # Товары с остатком ниже минимального
    low_stock_products = []
    for p in Product.objects.filter(is_active=True):
        if p.available_quantity <= p.min_stock:
            low_stock_products.append(p)

    context = {
        'new_orders_count': new_orders_count,
        'active_orders_count': active_orders_count,
        'events_today_count': events_today_count,
        'stock_load_percent': stock_load_percent,
        'recent_orders': recent_orders,
        'low_stock_products': low_stock_products[:5],
        'today': today,
    }
    return render(request, 'admin_panel/dashboard.html', context)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def orders_list_view(request):
    """Список всех заказов с фильтрами по статусу и дате"""
    orders = Order.objects.select_related('client', 'package', 'event_type').order_by('-created_at')

    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)

    date_filter = request.GET.get('date')
    if date_filter:
        try:
            parsed_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            orders = orders.filter(event_date=parsed_date)
        except ValueError:
            pass

    search_q = request.GET.get('q', '').strip()
    if search_q:
        orders = orders.filter(
            Q(order_number__icontains=search_q) |
            Q(client__name__icontains=search_q) |
            Q(client__phone__icontains=search_q)
        )

    context = {
        'orders': orders,
        'status_choices': Order.STATUS_CHOICES,
        'selected_status': status,
        'search_q': search_q,
        'date_filter': date_filter,
    }
    return render(request, 'admin_panel/orders_list.html', context)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def order_detail_view(request, pk):
    """Детальная карточка заказа в админке с управлением статусом и оплатой"""
    order = get_object_or_404(
        Order.objects.select_related('client', 'package', 'event_type', 'delivery_zone')
        .prefetch_related('items__product', 'services__service', 'status_history'),
        pk=pk
    )

    # Проверка физической доступности склада на дату
    is_available, issues = order.check_availability()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = request.POST.get('status')
            comment = request.POST.get('status_comment', '')
            if new_status in dict(Order.STATUS_CHOICES) and new_status != order.status:
                old_status = order.status

                # Если подтверждаем заказ — проводим проверку склада
                if new_status in [Order.STATUS_CONFIRMED, Order.STATUS_PAYMENT_PENDING]:
                    can_reserve, stock_issues = order.check_availability()
                    if not can_reserve:
                        msg = "Невозможно подтвердить заказ: недостаточно товара на складе! " + ", ".join([f"{i['product'].name} (не хватает {i['shortage']} шт.)" for i in stock_issues])
                        messages.error(request, msg)
                        return redirect('admin_panel:order_detail', pk=order.pk)

                order.status = new_status
                order.save(update_fields=['status', 'updated_at'])
                order.sync_reservations()

                OrderStatusHistory.objects.create(
                    order=order,
                    old_status=old_status,
                    new_status=new_status,
                    changed_by=request.user,
                    comment=comment
                )

                # Уведомляем клиента в Telegram при необходимости
                if request.POST.get('notify_client'):
                    notify_client_status_update(order)

                messages.success(request, f'Статус изменен на: {dict(Order.STATUS_CHOICES).get(new_status)}')
                return redirect('admin_panel:order_detail', pk=order.pk)

        elif action == 'update_payment':
            paid_str = request.POST.get('paid_amount', '0')
            try:
                order.paid_amount = Decimal(paid_str)
                if order.paid_amount >= order.total_price and order.status in [Order.STATUS_NEW, Order.STATUS_CONFIRMED, Order.STATUS_PAYMENT_PENDING]:
                    order.status = Order.STATUS_PAID
                    order.sync_reservations()
                    OrderStatusHistory.objects.create(
                        order=order,
                        old_status=order.status,
                        new_status=Order.STATUS_PAID,
                        changed_by=request.user,
                        comment='Автоматическая смена статуса при полной оплате'
                    )
                order.save()
                messages.success(request, 'Сумма оплаты успешно обновлена')
            except Exception as e:
                messages.error(request, f'Ошибка при обновлении оплаты: {e}')
            return redirect('admin_panel:order_detail', pk=order.pk)

        elif action == 'update_notes':
            order.manager_comment = request.POST.get('manager_comment', '')
            order.save(update_fields=['manager_comment'])
            messages.success(request, 'Заметка менеджера сохранена')
            return redirect('admin_panel:order_detail', pk=order.pk)

    context = {
        'order': order,
        'status_choices': Order.STATUS_CHOICES,
        'is_available': is_available,
        'issues': issues,
    }
    return render(request, 'admin_panel/order_detail.html', context)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def order_status_update_view(request, pk):
    """Быстрое изменение статуса через AJAX"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    order = get_object_or_404(Order, pk=pk)
    new_status = request.POST.get('status')

    if new_status in dict(Order.STATUS_CHOICES):
        old_status = order.status
        order.status = new_status
        order.save(update_fields=['status'])
        order.sync_reservations()

        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status=new_status,
            changed_by=request.user,
            comment='Быстрое обновление статуса'
        )
        return JsonResponse({'success': True, 'new_status': new_status})
    return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def order_check_stock_view(request, pk):
    """AJAX проверка склада для конкретного заказа"""
    order = get_object_or_404(Order, pk=pk)
    is_available, issues = order.check_availability()
    issues_serialized = [
        {
            'product_name': i['product'].name,
            'requested': i['requested'],
            'available': i['available'],
            'shortage': i['shortage'],
        } for i in issues
    ]
    return JsonResponse({
        'success': True,
        'is_available': is_available,
        'issues': issues_serialized
    })


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def calendar_view(request):
    """Календарь занятости оборудования и заказов"""
    return render(request, 'admin_panel/calendar.html')


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def calendar_data_api(request):
    """JSON API для календаря: заказы и процент занятости на дни месяца"""
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')

    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else date.today().replace(day=1)
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else start_date + timedelta(days=35)
    except ValueError:
        start_date = date.today().replace(day=1)
        end_date = start_date + timedelta(days=35)

    orders = Order.objects.filter(
        event_date__gte=start_date,
        event_date__lte=end_date
    ).exclude(status=Order.STATUS_CANCELLED).select_related('client')

    events = []
    for ord_obj in orders:
        color = '#3b82f6' # blue default
        if ord_obj.status == Order.STATUS_NEW:
            color = '#f59e0b' # amber
        elif ord_obj.status == Order.STATUS_CONFIRMED:
            color = '#10b981' # green
        elif ord_obj.status == Order.STATUS_PAID:
            color = '#059669' # dark green

        events.append({
            'id': ord_obj.id,
            'title': f"#{ord_obj.order_number} {ord_obj.client.name} ({ord_obj.guest_count} гостей)",
            'start': ord_obj.event_date.strftime('%Y-%m-%d'),
            'url': f"/admin-panel/orders/{ord_obj.id}/",
            'backgroundColor': color,
            'borderColor': color,
        })

    return JsonResponse(events, safe=False)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def warehouse_view(request):
    """Раздел Склад: остатки, в ремонте, зарезервировано на сегодня, минимальный остаток"""
    today = date.today()
    products = Product.objects.filter(is_active=True).select_related('category').order_by('category', 'name')

    warehouse_items = []
    for prod in products:
        reserved_today = StockReservation.objects.filter(
            product=prod, date=today, is_active=True
        ).aggregate(total=Sum('quantity'))['total'] or 0

        free_today = max(0, prod.available_quantity - reserved_today)
        is_low = prod.available_quantity <= prod.min_stock

        warehouse_items.append({
            'product': prod,
            'total': prod.total_quantity,
            'in_repair': prod.in_repair,
            'reserved_today': reserved_today,
            'free_today': free_today,
            'min_stock': prod.min_stock,
            'is_low': is_low,
        })

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        prod = get_object_or_404(Product, pk=product_id)
        prod.total_quantity = int(request.POST.get('total_quantity', prod.total_quantity))
        prod.in_repair = int(request.POST.get('in_repair', prod.in_repair))
        prod.min_stock = int(request.POST.get('min_stock', prod.min_stock))
        prod.save()
        messages.success(request, f'Остатки для «{prod.name}» успешно обновлены')
        return redirect('admin_panel:warehouse')

    context = {
        'warehouse_items': warehouse_items,
        'today': today,
    }
    return render(request, 'admin_panel/warehouse.html', context)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def products_list_view(request):
    """Список товаров в админке"""
    products = Product.objects.all().select_related('category').order_by('category', 'name')
    categories = Category.objects.all()
    return render(request, 'admin_panel/products_list.html', {'products': products, 'categories': categories})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def product_create_view(request):
    """Создание нового товара"""
    categories = Category.objects.all()
    if request.method == 'POST':
        name = request.POST.get('name')
        category_id = request.POST.get('category_id')
        rental_price = request.POST.get('rental_price')
        deposit = request.POST.get('deposit', 0)
        total_quantity = request.POST.get('total_quantity', 0)
        min_stock = request.POST.get('min_stock', 5)
        guests_per_unit = request.POST.get('guests_per_unit', 1)
        description = request.POST.get('description', '')
        image = request.FILES.get('image')

        from django.utils.text import slugify
        import unidecode
        slug = slugify(unidecode.unidecode(name))

        category = get_object_or_404(Category, pk=category_id)
        prod = Product.objects.create(
            name=name,
            slug=slug,
            category=category,
            rental_price=rental_price,
            deposit=deposit,
            total_quantity=total_quantity,
            min_stock=min_stock,
            guests_per_unit=guests_per_unit,
            description=description,
            image=image
        )
        messages.success(request, f'Товар «{prod.name}» создан')
        return redirect('admin_panel:products_list')

    return render(request, 'admin_panel/product_form.html', {'categories': categories})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def product_edit_view(request, pk):
    """Редактирование товара"""
    prod = get_object_or_404(Product, pk=pk)
    categories = Category.objects.all()

    if request.method == 'POST':
        prod.name = request.POST.get('name')
        category_id = request.POST.get('category_id')
        prod.category = get_object_or_404(Category, pk=category_id)
        prod.rental_price = Decimal(request.POST.get('rental_price'))
        prod.deposit = Decimal(request.POST.get('deposit', 0))
        prod.total_quantity = int(request.POST.get('total_quantity', 0))
        prod.in_repair = int(request.POST.get('in_repair', 0))
        prod.min_stock = int(request.POST.get('min_stock', 5))
        prod.guests_per_unit = int(request.POST.get('guests_per_unit', 1))
        prod.description = request.POST.get('description', '')
        prod.is_active = bool(request.POST.get('is_active'))

        if 'image' in request.FILES:
            prod.image = request.FILES['image']

        prod.save()
        messages.success(request, f'Товар «{prod.name}» сохранен')
        return redirect('admin_panel:products_list')

    return render(request, 'admin_panel/product_form.html', {'product': prod, 'categories': categories})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def packages_list_view(request):
    """Список пакетов (BASIC, STANDARD, PREMIUM)"""
    packages = Package.objects.all().prefetch_related('items__product')
    return render(request, 'admin_panel/packages_list.html', {'packages': packages})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def package_create_view(request):
    """Создание нового пакета"""
    products = Product.objects.filter(is_active=True)
    if request.method == 'POST':
        name = request.POST.get('name')
        tier = request.POST.get('tier', 'basic')
        description = request.POST.get('description', '')
        base_price_override = request.POST.get('base_price_override') or None
        price_per_guest = request.POST.get('price_per_guest', 0)
        image = request.FILES.get('image')

        from django.utils.text import slugify
        import unidecode
        slug = slugify(unidecode.unidecode(name))

        pkg = Package.objects.create(
            name=name,
            slug=slug,
            tier=tier,
            description=description,
            base_price_override=base_price_override,
            price_per_guest=price_per_guest,
            image=image
        )
        messages.success(request, f'Пакет «{pkg.name}» создан. Теперь настройте состав.')
        return redirect('admin_panel:package_edit', pk=pkg.pk)

    return render(request, 'admin_panel/package_form.html', {'products': products})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def package_edit_view(request, pk):
    """Редактирование пакета и его состава (коэффициенты на гостя)"""
    pkg = get_object_or_404(Package.objects.prefetch_related('items__product'), pk=pk)
    all_products = Product.objects.filter(is_active=True)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_package':
            pkg.name = request.POST.get('name')
            pkg.tier = request.POST.get('tier', pkg.tier)
            pkg.description = request.POST.get('description', '')
            base_price = request.POST.get('base_price_override')
            pkg.base_price_override = Decimal(base_price) if base_price else None
            pkg.price_per_guest = Decimal(request.POST.get('price_per_guest', 0))
            pkg.is_active = bool(request.POST.get('is_active'))
            if 'image' in request.FILES:
                pkg.image = request.FILES['image']
            pkg.save()
            messages.success(request, 'Параметры пакета сохранены')

        elif action == 'add_item':
            prod_id = request.POST.get('product_id')
            qty_per_guest = request.POST.get('quantity_per_guest', 1.0)
            min_qty = request.POST.get('min_quantity', 1)
            prod = get_object_or_404(Product, pk=prod_id)

            PackageItem.objects.update_or_create(
                package=pkg,
                product=prod,
                defaults={
                    'quantity_per_guest': Decimal(qty_per_guest),
                    'min_quantity': int(min_qty)
                }
            )
            messages.success(request, f'Товар «{prod.name}» добавлен в пакет')

        elif action == 'delete_item':
            item_id = request.POST.get('item_id')
            PackageItem.objects.filter(package=pkg, id=item_id).delete()
            messages.success(request, 'Товар удален из состава пакета')

        return redirect('admin_panel:package_edit', pk=pkg.pk)

    context = {
        'package': pkg,
        'all_products': all_products,
    }
    return render(request, 'admin_panel/package_form.html', context)


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def clients_list_view(request):
    """Список клиентов с историей заказов и суммой"""
    clients = Client.objects.all().prefetch_related('orders').order_by('-created_at')
    q = request.GET.get('q', '').strip()
    if q:
        clients = clients.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(telegram__icontains=q))

    return render(request, 'admin_panel/clients_list.html', {'clients': clients, 'q': q})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def client_detail_view(request, pk):
    """Карточка клиента с полной историей заказов"""
    client = get_object_or_404(Client.objects.prefetch_related('orders__items__product'), pk=pk)

    if request.method == 'POST':
        client.comment = request.POST.get('comment', '')
        client.is_vip = bool(request.POST.get('is_vip'))
        client.save(update_fields=['comment', 'is_vip'])
        messages.success(request, 'Данные клиента обновлены')
        return redirect('admin_panel:client_detail', pk=client.pk)

    return render(request, 'admin_panel/client_detail.html', {'client': client})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def services_view(request):
    """Управление допуслугами и зонами доставки"""
    services = Service.objects.all().order_by('order')
    delivery_zones = DeliveryZone.objects.all().order_by('order')
    return render(request, 'admin_panel/services.html', {'services': services, 'delivery_zones': delivery_zones})


@login_required(login_url='/admin-panel/login/')
@user_passes_test(is_staff_check, login_url='/admin-panel/login/')
def analytics_view(request):
    """Раздел «Аналитика»: выручка, средний чек, топ товаров, загрузка склада"""
    total_orders = Order.objects.count()
    completed_orders = Order.objects.filter(status=Order.STATUS_COMPLETED).count()
    cancelled_orders = Order.objects.filter(status=Order.STATUS_CANCELLED).count()

    total_revenue = Order.objects.filter(
        status__in=[
            Order.STATUS_CONFIRMED, Order.STATUS_PAID,
            Order.STATUS_PREPARING, Order.STATUS_READY,
            Order.STATUS_DELIVERING, Order.STATUS_EVENT,
            Order.STATUS_COMPLETED
        ]
    ).aggregate(s=Sum('total_price'))['s'] or 0

    avg_check = round(total_revenue / completed_orders) if completed_orders else 0

    # Самые популярные товары
    top_products = OrderItem.objects.values('product__name').annotate(
        total_rented=Sum('quantity'),
        total_revenue=Sum('total_price'),
        orders_count=Count('order', distinct=True)
    ).order_by('-total_rented')[:10]

    # Популярные пакеты
    top_packages = Order.objects.filter(package__isnull=False).values('package__name').annotate(
        orders_count=Count('id'),
        revenue=Sum('total_price')
    ).order_by('-orders_count')[:5]

    # Новые и повторные клиенты
    clients_with_multiple_orders = Client.objects.annotate(c=Count('orders')).filter(c__gt=1).count()
    total_clients = Client.objects.count()

    context = {
        'total_orders': total_orders,
        'completed_orders': completed_orders,
        'cancelled_orders': cancelled_orders,
        'total_revenue': total_revenue,
        'avg_check': avg_check,
        'top_products': top_products,
        'top_packages': top_packages,
        'total_clients': total_clients,
        'repeat_clients': clients_with_multiple_orders,
    }
    return render(request, 'admin_panel/analytics.html', context)
