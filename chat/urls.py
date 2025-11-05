from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

urlpatterns = [
    path('', views.chat_page, name='chat_page'),
    path('history/', views.history_page, name='history_page'),
    path('about/', views.about_page, name='about_page'),  # Новый маршрут
    path('api/send-message/', views.send_message, name='send_message'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)