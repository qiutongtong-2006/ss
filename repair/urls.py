from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'repair'

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('my-tasks/', views.repairer_orders, name='repairer_orders'),
    path('manage/orders/', views.manager_orders, name='manager_orders'),
    path('repair/new/', views.submit_repair, name='submit_repair'),
    path('repair/<int:pk>/accept/', views.accept_order, name='accept_order'),
    path('repair/<int:pk>/start/', views.start_repair, name='start_repair'),
    path('repair/<int:pk>/complete/', views.complete_repair, name='complete_repair'),
    path('repair/<int:pk>/reject/', views.reject_order, name='reject_order'),
    path('repair/<int:pk>/cancel/', views.cancel_order, name='cancel_order'),
    path('repair/<int:pk>/', views.work_order_detail, name='work_order_detail'),
    path(
        'login/',
        auth_views.LoginView.as_view(template_name='repair/login.html'),
        name='login',
    ),
    path('logout/', views.logout_view, name='logout'),
]
