from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import requests
import os
from .models import ChatMessage


def chat_page(request):
    """Главная страница с чатом"""
    return render(request, 'chat/chat.html')


def history_page(request):
    """Страница истории сообщений"""
    messages = ChatMessage.objects.all()
    return render(request, 'chat/history.html', {'messages': messages})


@require_http_methods(["POST"])
def send_message(request):
    """API endpoint для отправки сообщения боту"""
    import json

    try:
        data = json.loads(request.body)
        user_message = data.get('message', '')

        if not user_message:
            return JsonResponse({'error': 'Сообщение не может быть пустым'}, status=400)

        # Вызываем OpenRouter API
        bot_response = get_bot_response(user_message)

        # Сохраняем в БД
        chat_msg = ChatMessage.objects.create(
            user_message=user_message,
            bot_response=bot_response
        )

        return JsonResponse({
            'user_message': user_message,
            'bot_response': bot_response,
            'id': chat_msg.id
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def call_cloud_function_bot(user_message):
    """Отправить сообщение в новый API endpoint Cloud Function"""
    import requests

    # URL вашего нового API endpoint
    API_URL = "https://us-central1-charged-atlas-472011-r3.cloudfunctions.net/chat_api"

    payload = {"message": user_message}

    try:
        response = requests.post(API_URL, json=payload, timeout=30)

        if response.status_code == 200:
            result = response.json()
            return result.get("response", "Ошибка получения ответа")
        else:
            return f"Ошибка: {response.status_code}"

    except Exception as e:
        return f"Ошибка соединения: {str(e)}"
