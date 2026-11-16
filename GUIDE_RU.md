# StudyCloud AI — гайд по проекту

## 1. Структура

```text
StudyCloudAI/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py
│   ├── tests/
│   │   └── test_app.py
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── i18n.js
│   ├── sw.js
│   ├── manifest.webmanifest
│   └── icon.svg
├── data/
│   ├── studycloud.db
│   ├── jwt-secret.key
│   └── uploads/
├── run.ps1
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

`backend/` и `frontend/` содержат исходный код. `data/` — рабочие данные пользователя. База и старые загрузки остались на прежнем месте, поэтому разделение папок их не удаляет.

## 2. Что находится в backend

Главный файл — `backend/app/main.py`.

Он отвечает за:

- запуск FastAPI;
- регистрацию, вход и проверку JWT;
- хеширование паролей Argon2;
- SQLite-таблицы пользователей, материалов, попыток тестов и пробелов знаний;
- проверку владельца материала;
- загрузку и разбор PDF, PPTX, DOCX, EPUB, HTML, CSV, TXT, Markdown и субтитров;
- генерацию конспекта, карточек и теста;
- работу ProofLoop, BlindSpot Detector и Feynman Defense;
- раздачу файлов из папки `frontend/`.

Основные таблицы базы:

- `users` — аккаунты и хеши паролей;
- `lectures` — материалы с полем `owner_id`;
- `quiz_attempts` — результаты тестов с `user_id`;
- `knowledge_gaps` — персональные пробелы знаний и интервалы повторения.

Пароль в открытом виде не сохраняется. После входа сервер выдаёт JWT на 8 часов. Браузер отправляет его в каждом защищённом запросе:

```text
Authorization: Bearer <token>
```

Swagger находится по адресу <http://127.0.0.1:8000/docs>. Сначала зарегистрируйтесь в приложении, затем нажмите в Swagger `Authorize` и укажите тот же логин и пароль.

## 3. Что находится во frontend

- `frontend/index.html` — разметка экрана входа и всех разделов приложения.
- `frontend/styles.css` — адаптивный дизайн для компьютера и телефона.
- `frontend/app.js` — запросы к API, авторизация, загрузка файлов, тесты, карточки, голосовой ввод и навигация.
- `frontend/i18n.js` — английский, русский и казахский языки.
- `frontend/sw.js` — кеш PWA и офлайн-оболочка.
- `frontend/manifest.webmanifest` и `icon.svg` — установка приложения на устройство.

Отдельный frontend-сервер не нужен: FastAPI раздаёт эту папку по `/static`, а `index.html` — по `/`. Поэтому frontend и API работают на одном адресе и дополнительная настройка CORS не требуется.

## 4. Как проходит запрос

```text
Браузер
  → frontend/app.js
  → запрос /api/... с JWT
  → backend/app/main.py
  → проверка пользователя и owner_id
  → SQLite / обработка документа
  → JSON-ответ
  → обновление интерфейса
```

Пример: пользователь загружает PDF. `app.js` отправляет `FormData` на `POST /api/lectures`. FastAPI проверяет JWT, извлекает текст, создаёт учебный пакет, записывает его с `owner_id` и возвращает JSON для интерфейса.

## 5. Запуск на Windows

Самый простой способ из корня проекта:

```powershell
.\run.ps1
```

Скрипт создаёт `.venv`, устанавливает `backend/requirements.txt` и запускает сервер на <http://127.0.0.1:8000>.

Ручной запуск:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python -m uvicorn backend.app.main:app --reload
```

## 6. Настройка PyCharm

1. Откройте папку `C:\Users\D\Documents\Claude\StudyCloudAI` как проект.
2. В `Settings → Python Interpreter` выберите:

```text
C:\Users\D\Documents\Claude\StudyCloudAI\.venv\Scripts\python.exe
```

3. Откройте `Run → Edit Configurations`.
4. Создайте конфигурацию `Python`.
5. Выберите `Module name` и укажите `uvicorn`.
6. В `Parameters` укажите:

```text
backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

7. `Working directory`:

```text
C:\Users\D\Documents\Claude\StudyCloudAI
```

Запускать `main.py` как обычный скрипт не нужно: приложение запускается ASGI-сервером Uvicorn.

## 7. Переменные окружения

Скопируйте пример:

```powershell
Copy-Item .env.example .env
```

Основные параметры:

```text
GEMINI_API_KEY=          # необязательно
GEMINI_MODEL=gemini-2.5-flash
STUDYCLOUD_SECRET_KEY=   # для продакшена: случайная строка от 32 символов
```

Без Gemini приложение использует локальный алгоритм. Без `STUDYCLOUD_SECRET_KEY` локальная версия сама создаёт `data/jwt-secret.key`.

## 8. Тесты

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Тесты проверяют регистрацию и вход, Swagger OAuth2, запрет анонимного доступа, разделение данных двух пользователей, загрузку разных форматов, тесты, ProofLoop, Feynman Defense, экспорт и PWA-файлы.

## 9. Docker

```powershell
docker compose up --build
```

Контейнер копирует `backend/` и `frontend/`, а корневая папка `data/` подключается как volume. Поэтому база и загрузки переживают пересборку контейнера.

## 10. Что сделано сверх обычного конспектора

- ProofLoop превращает ошибку в отслеживаемый пробел знаний со ссылкой на источник.
- BlindSpot Detector находит ошибки, в которых пользователь был уверен.
- Feynman Defense проверяет объяснение темы своими словами и находит пропущенные понятия.
- Каждый вывод связан со страницей, слайдом, разделом или другим местом исходного файла.
- Для каждого аккаунта отдельно хранятся материалы, попытки, уверенность и график повторений.
