### WEB-приложение  
Структура проекта:  
django-chat-bot
markdown# Django Chat Bot

### Описание проекта
Web-приложение чат-бота на Django с интеграцией Google Cloud Function.

### Структура проекта
django-chat-bot/
+ manage.py              # Главный файл Django
+ requirements.txt       # Зависимости проекта
+ db.sqlite3            # База данных SQLite
- /chatbot_project
  + settings.py         # Настройки Django
  + urls.py            # Главные маршруты
  + wsgi.py            # WSGI конфигурация
  + asgi.py            # ASGI конфигурация
- /chat
  + models.py          # Модели базы данных
  + views.py           # Логика приложения
  + urls.py            # Маршруты приложения
  - /templates/chat
    + base.html        # Базовый шаблон
    + chat.html        # Страница чата
    + about.html       # Страница О проекте
    + history.html     # История сообщений
  - /static/chat
    - /images          # Изображения
  - /migrations        # Миграции базы данных
+ main.py            # Код для чат-бота, он задеплоен в облачный сервис

### Установка и запуск

**Установка зависимостей:**
`pip install -r requirements.txt`

**Применение миграций:**
`python manage.py migrate`

**Запуск сервера:**
`python manage.py runserver`

**Доступ к приложению:**
Откройте браузер и перейдите по адресу:
`http://127.0.0.1:8000/`

### Использование

**Главная страница (Чат):**
Введите сообщение в поле ввода и нажмите Отправить или Enter.
Бот обработает запрос и отправит ответ.

**Страница О проекте:**
Перейдите по ссылке /about/ для просмотра информации о проекте.

**История сообщений:**
Перейдите по ссылке /history/ для просмотра всех сохраненных сообщений.

### Технологии
- Django 5.1.4
- Python 3.13
- SQLite
- Google Cloud Functions
- HTML/CSS/JavaScript


### Автор
Алексей Скрипкин