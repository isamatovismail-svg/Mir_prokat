from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('submit/', views.submit_order_view, name='submit_order'),
    path('cart/', views.cart_view, name='cart'),
    path('<str:order_number>/', views.order_detail_view, name='order_detail'),
]
