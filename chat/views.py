from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import requests
import json
from .models import ChatMessage


def chat_page(request):
    """Главная страница с чатом"""
    return render(request, 'chat/chat.html')


def history_page(request):
    """Страница истории сообщений"""
    messages = ChatMessage.objects.all()
    return render(request, 'chat/history.html', {'messages': messages})


def call_cloud_function_bot(user_message):
    """Вызов Cloud Function бота"""
    API_URL = "https://my-telegram-bot-620646991187.us-central1.run.app"

    payload = {
        "message": user_message
    }

    print(f"Отправляю запрос на {API_URL}")
    print(f"Payload: {payload}")

    try:
        response = requests.post(
            API_URL,
            json=payload,
            timeout=60,
            headers={'Content-Type': 'application/json'}
        )

        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.text[:200]}...")

        # Проверяем, что сервер вернул JSON
        try:
            result = response.json()
        except ValueError:
            return f"Ошибка: сервер вернул не JSON ({response.text[:100]})"

        if response.status_code == 200:
            return result.get("response", "Ошибка: нет поля 'response' в ответе")
        else:
            return f"Ошибка сервера: {response.status_code} - {result.get('error', response.text[:100])}"

    except requests.exceptions.Timeout:
        print("Таймаут запроса")
        return "Бот не ответил за 60 секунд"

    except requests.exceptions.ConnectionError as e:
        print(f"Ошибка соединения: {e}")
        return "Не удалось подключиться к серверу бота"

    except Exception as e:
        print(f"Ошибка в call_cloud_function_bot: {e}")
        import traceback
        traceback.print_exc()
        return f"Ошибка: {str(e)}"


@csrf_exempt  # для локального тестирования
@require_http_methods(["POST"])
def send_message(request):
    """API endpoint для отправки сообщения боту"""
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()

        if not user_message:
            return JsonResponse({'error': 'Сообщение не может быть пустым'}, status=400)

        # Отправляем запрос в Cloud Function
        bot_response = call_cloud_function_bot(user_message)

        # Сохраняем в базу
        chat_msg = ChatMessage.objects.create(
            user_message=user_message,
            bot_response=bot_response
        )

        return JsonResponse({
            'user_message': user_message,
            'bot_response': bot_response,
            'id': chat_msg.id
        }, status=200)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Неверный формат JSON'}, status=400)

    except Exception as e:
        print(f"Ошибка в send_message: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
