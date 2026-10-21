from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'repair'

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('repair/new/', views.submit_repair, name='submit_repair'),
    path('repair/<int:pk>/', views.work_order_detail, name='work_order_detail'),
    path(
        'login/',
        auth_views.LoginView.as_view(template_name='repair/login.html'),
        name='login',
    ),
    path('logout/', views.logout_view, name='logout'),
]
