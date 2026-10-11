import json
from datetime import datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.db import models
from django.db.models import Q, Sum
from .models import Category, Product, Package, PackageItem, EventType
from apps.services.models import Service, DeliveryZone
from apps.warehouse.models import StockReservation


def home_view(request):
    """Главная страница: витрина, популярные категории, пакеты, калькулятор"""
    categories = Category.objects.filter(is_active=True).order_by('order', 'name')
    packages = Package.objects.filter(is_active=True).prefetch_related('items__product').order_by('order')
    featured_products = Product.objects.filter(is_active=True).select_related('category')[:8]
    event_types = EventType.objects.filter(is_active=True).order_by('order')
    services = Service.objects.filter(is_active=True).order_by('order')

    context = {
        'categories': categories,
        'packages': packages,
        'featured_products': featured_products,
        'event_types': event_types,
        'services': services,
    }
    return render(request, 'site/home.html', context)


def catalog_view(request, category_slug=None):
    """Каталог товаров с фильтрами, поиском и категориями"""
    categories = Category.objects.filter(is_active=True).order_by('order', 'name')
    selected_category = None
    products = Product.objects.filter(is_active=True).select_related('category')

    if category_slug:
        selected_category = get_object_or_404(Category, slug=category_slug, is_active=True)
        products = products.filter(category=selected_category)

    # Поиск по названию или описанию
    q = request.GET.get('q', '').strip()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(description__icontains=q))

    # Сортировка
    sort = request.GET.get('sort', 'default')
    if sort == 'price_asc':
        products = products.order_by('rental_price')
    elif sort == 'price_desc':
        products = products.order_by('-rental_price')
    elif sort == 'name':
        products = products.order_by('name')

    context = {
        'categories': categories,
        'selected_category': selected_category,
        'products': products,
        'q': q,
        'sort': sort,
    }
    return render(request, 'site/catalog.html', context)


def product_detail_view(request, slug):
    """Страница отдельного товара"""
    product = get_object_or_404(Product, slug=slug, is_active=True)
    related_products = Product.objects.filter(
        category=product.category, is_active=True
    ).exclude(id=product.id)[:4]

    context = {
        'product': product,
        'related_products': related_products,
    }
    return render(request, 'site/product_detail.html', context)


def packages_view(request):
    """Страница готовых пакетов (BASIC, STANDARD, PREMIUM)"""
    packages = Package.objects.filter(is_active=True).prefetch_related('items__product').order_by('order')
    sample_guests = int(request.GET.get('guests', 100))

    # Рассчитанные данные для каждого пакета под выбранное количество гостей
    package_data = []
    for pkg in packages:
        items = pkg.get_items_for_guests(sample_guests)
        calculated_price = pkg.calculate_price(sample_guests)
        package_data.append({
            'package': pkg,
            'items': items,
            'price': calculated_price,
        })

    context = {
        'package_data': package_data,
        'sample_guests': sample_guests,
    }
    return render(request, 'site/packages.html', context)


def package_detail_view(request, slug):
    """Детальная информация о пакете"""
    package = get_object_or_404(Package, slug=slug, is_active=True)
    guests = int(request.GET.get('guests', 100))
    items = package.get_items_for_guests(guests)
    price = package.calculate_price(guests)

    context = {
        'package': package,
        'guests': guests,
        'items': items,
        'price': price,
    }
    return render(request, 'site/package_detail.html', context)


def calculator_view(request):
    """Интерактивный калькулятор мероприятия"""
    event_types = EventType.objects.filter(is_active=True).order_by('order')
    packages = Package.objects.filter(is_active=True).prefetch_related('items__product').order_by('order')
    extra_products = Product.objects.filter(is_active=True).select_related('category')
    services = Service.objects.filter(is_active=True).order_by('order')
    delivery_zones = DeliveryZone.objects.filter(is_active=True).order_by('order')

    context = {
        'event_types': event_types,
        'packages': packages,
        'extra_products': extra_products,
        'services': services,
        'delivery_zones': delivery_zones,
    }
    return render(request, 'site/calculator.html', context)


def how_it_works_view(request):
    """Страница «Как это работает»"""
    return render(request, 'site/how_it_works.html')


def contacts_view(request):
    """Страница контактов"""
    return render(request, 'site/contacts.html')


# ---------------- API ENDPOINTS ---------------- #

def api_check_date(request):
    """
    Проверка наличия товаров на конкретную дату.
    GET /api/check-date/?date=YYYY-MM-DD&items=[{"product_id": 1, "quantity": 100}]
    """
    date_str = request.GET.get('date')
    items_raw = request.GET.get('items')

    if not date_str:
        return JsonResponse({'success': False, 'error': 'Дата не указана'}, status=400)

    try:
        event_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Неверный формат даты (требуется YYYY-MM-DD)'}, status=400)

    items_list = []
    if items_raw:
        try:
            items_list = json.loads(items_raw)
        except Exception:
            pass

    results = []
    all_available = True

    for itm in items_list:
        p_id = itm.get('product_id')
        qty = int(itm.get('quantity', 0))
        try:
            prod = Product.objects.get(id=p_id, is_active=True)
            # Занято на складе в эту дату
            reserved = StockReservation.objects.filter(
                product=prod, date=event_date, is_active=True
            ).aggregate(total=models.Sum('quantity'))['total'] or 0

            available = max(0, prod.available_quantity - reserved)
            is_ok = available >= qty
            if not is_ok:
                all_available = False

            results.append({
                'product_id': prod.id,
                'name': prod.name,
                'requested': qty,
                'total_stock': prod.total_quantity,
                'reserved': reserved,
                'available': available,
                'is_available': is_ok,
                'shortage': max(0, qty - available)
            })
        except Product.DoesNotExist:
            continue

    return JsonResponse({
        'success': True,
        'date': date_str,
        'all_available': all_available,
        'results': results
    })


def api_calculate_package(request):
    """
    Рассчитать состав и стоимость пакета для заданного числа гостей
    GET /api/calculate-package/?package_id=1&guests=100
    """
    pkg_id = request.GET.get('package_id')
    guests = int(request.GET.get('guests', 100))

    try:
        package = Package.objects.get(id=pkg_id, is_active=True)
    except Package.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Пакет не найден'}, status=404)

    items_data = []
    total_price = 0
    total_deposit = 0

    for item in package.items.select_related('product'):
        qty = item.get_quantity_for_guests(guests)
        subtotal = qty * float(item.product.rental_price)
        total_price += subtotal
        total_deposit += qty * float(item.product.deposit)

        items_data.append({
            'product_id': item.product.id,
            'name': item.product.name,
            'quantity': qty,
            'unit_price': float(item.product.rental_price),
            'deposit': float(item.product.deposit),
            'subtotal': subtotal,
            'image': item.product.image.url if item.product.image else None,
        })

    if package.base_price_override:
        total_price = float(package.base_price_override)
    elif package.price_per_guest > 0:
        total_price = float(package.price_per_guest * guests)

    return JsonResponse({
        'success': True,
        'package_id': package.id,
        'package_name': package.name,
        'guests': guests,
        'items': items_data,
        'total_price': total_price,
        'total_deposit': total_deposit
    })


def api_quick_calculate(request):
    """Быстрый расчет состава по правилам без жесткого пакета"""
    guests = int(request.GET.get('guests', 100))

    # Стандартные правила:
    # 1 стул = 1 гость
    # 1 стол = 10 гостей
    # 1 тарелка, вилка, ложка, нож, стакан = 1 гость
    # 1 скатерть = 1 стол (10 гостей)
    import math
    calc = {
        'guests': guests,
        'chairs': guests,
        'tables': math.ceil(guests / 10),
        'plates': guests,
        'forks': guests,
        'spoons': guests,
        'knives': guests,
        'glasses': guests,
        'tablecloths': math.ceil(guests / 10),
    }
    return JsonResponse({'success': True, 'calculation': calc})
