from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from django.http import HttpResponse


def home(request):
    return HttpResponse(
        "<!doctype html><meta charset=utf-8>"
        "<h1>Приложение работает</h1>"
        "<p>Бэкенд на Django запущен. Админка: <a href='/admin/'>/admin/</a>.</p>"
    )


urlpatterns = [
    path("", home),
    # Django's default LOGIN_URL is /accounts/login/, so @login_required
    # (and LoginRequiredMiddleware) send every guest here — the address has to
    # be real or the app 404s for whoever opens the link first. Only these two:
    # Django's full auth url conf also mounts password-reset views that need
    # their own templates and a mail backend, and would 500 instead.
    path("accounts/login/", LoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]

