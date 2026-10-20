from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import StudentRegistrationForm
from .models import User


def register(request):
    """学生自助注册，角色固定为学生。"""
    if request.user.is_authenticated:
        return redirect('repair:home')

    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.role = User.Role.STUDENT
            user.save()
            login(request, user)
            messages.success(request, '注册成功，欢迎使用学生宿舍报修系统。')
            return redirect('repair:home')
    else:
        form = StudentRegistrationForm()

    return render(request, 'repair/register.html', {'form': form})


@login_required
def home(request):
    """登录后的首页，按角色显示不同入口。"""
    return render(request, 'repair/home.html')


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, '你已退出登录。')
    return redirect('repair:login')
