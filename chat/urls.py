from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_page, name='chat'),
    path('history/', views.history_page, name='history'),
    path('api/send-message/', views.send_message, name='send_message'),
]