from django.urls import path
from . import views

app_name = 'catalog'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('catalog/', views.catalog_view, name='catalog'),
    path('catalog/<slug:category_slug>/', views.catalog_view, name='category_products'),
    path('product/<slug:slug>/', views.product_detail_view, name='product_detail'),
    path('packages/', views.packages_view, name='packages'),
    path('packages/<slug:slug>/', views.package_detail_view, name='package_detail'),
    path('calculator/', views.calculator_view, name='calculator'),
    path('how-it-works/', views.how_it_works_view, name='how_it_works'),
    path('contacts/', views.contacts_view, name='contacts'),

    # API endpoints
    path('api/check-date/', views.api_check_date, name='api_check_date'),
    path('api/calculate-package/', views.api_calculate_package, name='api_calculate_package'),
    path('api/quick-calculate/', views.api_quick_calculate, name='api_quick_calculate'),
]
