from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import requests
import json
from .models import ChatMessage


def chat_page(request):
    return render(request, 'chat/chat.html')


def history_page(request):
    messages = ChatMessage.objects.all()
    return render(request, 'chat/history.html', {'messages': messages})


def about_page(request):
    return render(request, 'chat/about.html')


def call_cloud_function_bot(user_message):
    API_URL = "https://my-telegram-bot-620646991187.us-central1.run.app"

    try:
        # POST запрос
        response = requests.post(
            API_URL,
            json={"message": user_message},
            timeout=120
        )

        #  ответ в формате JSON
        result = response.json()

        if response.status_code == 200:
            return result.get("response", "Бот не прислал ответ")
        else:
            return f"Ошибка: {response.status_code}"

    except requests.exceptions.Timeout:
        return "Бот не ответил"

    except Exception as e:
        return f"Ошибка: {str(e)}"


@csrf_exempt
@require_http_methods(["POST"])
def send_message(request):
    try:
        # Читаем JSON из запроса
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()

        # Проверяем, что сообщение не пустое
        if not user_message:
            return JsonResponse({'error': 'Напишите сообщение'}, status=400)

        # Отправляем сообщение боту
        bot_response = call_cloud_function_bot(user_message)

        # Сохраняем в базу данных
        ChatMessage.objects.create(
            user_message=user_message,
            bot_response=bot_response
        )

        # Возвращаем результат
        return JsonResponse({
            'user_message': user_message,
            'bot_response': bot_response
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)