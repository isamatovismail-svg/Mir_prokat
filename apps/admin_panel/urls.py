from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('login/', views.admin_login_view, name='login'),
    path('logout/', views.admin_logout_view, name='logout'),
    path('', views.dashboard_view, name='dashboard'),
    path('orders/', views.orders_list_view, name='orders_list'),
    path('orders/<int:pk>/', views.order_detail_view, name='order_detail'),
    path('orders/<int:pk>/status/', views.order_status_update_view, name='order_status_update'),
    path('orders/<int:pk>/check-stock/', views.order_check_stock_view, name='order_check_stock'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('calendar/data/', views.calendar_data_api, name='calendar_data'),
    path('warehouse/', views.warehouse_view, name='warehouse'),
    path('products/', views.products_list_view, name='products_list'),
    path('products/create/', views.product_create_view, name='product_create'),
    path('products/<int:pk>/edit/', views.product_edit_view, name='product_edit'),
    path('packages/', views.packages_list_view, name='packages_list'),
    path('packages/create/', views.package_create_view, name='package_create'),
    path('packages/<int:pk>/edit/', views.package_edit_view, name='package_edit'),
    path('clients/', views.clients_list_view, name='clients_list'),
    path('clients/<int:pk>/', views.client_detail_view, name='client_detail'),
    path('services/', views.services_view, name='services'),
    path('analytics/', views.analytics_view, name='analytics'),
]
