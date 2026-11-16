# StudyCloud AI — полный гайд по backend

Этот документ объясняет backend так, чтобы по нему можно было разобраться в коде, отладить проект и защитить работу перед преподавателем.

Главный файл backend: `backend/app/main.py`.

## 1. Задача backend

Backend выполняет пять основных задач:

1. Регистрирует пользователей и выдаёт JWT-токены.
2. Разделяет материалы, тесты и прогресс разных пользователей.
3. Принимает учебные файлы и извлекает из них текст с координатами источника.
4. Создаёт конспекты, карточки и вопросы локально или через Gemini.
5. Ведёт персональную модель знаний: ошибки, уверенность, пробелы и интервальные повторения.

Backend также раздаёт папку `frontend/`. Отдельный frontend-сервер в текущей локальной архитектуре не нужен.

## 2. Общая схема

```text
Браузер
   │
   │ HTTP + JSON + Bearer JWT
   ▼
FastAPI: backend/app/main.py
   ├── Pydantic: проверка входных данных
   ├── Auth: Argon2 + JWT
   ├── SQLite: пользователи и учебные данные
   ├── Extractors: PDF/PPTX/DOCX/EPUB/HTML/CSV/текст
   ├── Local engine: конспект, карточки, тест
   └── Gemini: необязательное улучшение генерации
```

Типичный запрос проходит так:

```text
app.js → /api/lectures → get_current_user()
       → проверка файла → extract_document()
       → local_study_material()
       → gemini_study_material() при наличии ключа
       → запись в SQLite с owner_id
       → JSON-ответ
```

## 3. Зависимости

Файл: `backend/requirements.txt`.

| Пакет | Для чего нужен |
|---|---|
| `fastapi` | API, маршруты, dependency injection, Swagger |
| `uvicorn` | ASGI-сервер, который запускает FastAPI |
| `python-multipart` | Приём файлов через `multipart/form-data` |
| `pypdf` | Извлечение текста из PDF |
| `python-docx` | Чтение DOCX |
| `python-pptx` | Чтение PPTX |
| `httpx` | Асинхронные запросы к Gemini API |
| `PyJWT` | Создание и проверка JWT |
| `pwdlib[argon2]` | Безопасное хеширование паролей Argon2 |

SQLite, `csv`, `zipfile`, `json`, `re`, `uuid` и другие базовые модули входят в Python.

## 4. Конфигурация и пути

В начале `main.py` определяются основные параметры:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "frontend"
MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_SIZE = 100 * 1024 * 1024
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 8 * 60
```

- `PROJECT_ROOT` указывает на корень `StudyCloudAI`.
- `STATIC_DIR` указывает на отдельную папку frontend.
- Максимальный размер входного файла — 25 МБ.
- ZIP-контейнеры DOCX, PPTX и EPUB после распаковки ограничены 100 МБ.
- JWT подписывается алгоритмом HS256 и действует 8 часов.

Поддерживаемые расширения находятся в `SUPPORTED_EXTENSIONS`:

```text
PDF, PPTX, DOCX, TXT, MD, HTML, HTM, EPUB, CSV, SRT, VTT
```

## 5. Папка данных

Функция `data_dir()` выбирает рабочую директорию:

1. Берёт `STUDYCLOUD_DATA_DIR`, если переменная задана.
2. Иначе использует корневую папку `data/`.
3. Создаёт `data/` и `data/uploads/`, если их нет.

Структура:

```text
data/
├── studycloud.db       # SQLite
├── jwt-secret.key      # локальный секрет подписи JWT
└── uploads/            # оригиналы загруженных файлов
```

База и JWT-ключ исключены из Git. JWT-ключ также исключён из Docker build-контекста.

## 6. Подключение к SQLite

Функция `connect()`:

```python
connection = sqlite3.connect(data_dir() / "studycloud.db")
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA foreign_keys = ON")
```

`sqlite3.Row` позволяет обращаться к полям как `row["username"]`, а не только по индексам. `foreign_keys = ON` включает каскадные связи и проверку внешних ключей.

Конструкция:

```python
with connect() as db:
    ...
```

фиксирует транзакцию при успешном завершении и откатывает её при исключении.

## 7. Схема базы данных

### `users`

| Поле | Значение |
|---|---|
| `id` | UUID пользователя |
| `username` | уникальный логин без учёта регистра |
| `email` | уникальная почта без учёта регистра |
| `full_name` | отображаемое имя |
| `password_hash` | Argon2-хеш, не исходный пароль |
| `is_active` | можно ли войти |
| `created_at` | время регистрации в UTC |

### `lectures`

| Поле | Значение |
|---|---|
| `id` | ID учебного материала |
| `owner_id` | владелец материала |
| `title`, `filename` | заголовок и исходное имя файла |
| `pages` | число страниц, слайдов, глав или секций |
| `word_count` | количество слов |
| `text_content` | извлечённый полный текст |
| `summary` | конспект |
| `key_ideas` | JSON-массив ключевых идей |
| `quiz` | JSON-массив вопросов |
| `flashcards` | JSON-массив карточек |
| `source_chunks` | JSON-фрагменты со ссылками на источник |
| `engine` | локальный движок или Gemini |
| `file_type` | тип файла |
| `created_at` | дата создания |

### `quiz_attempts`

Хранит пользователя, материал, результат, ответы, уверенность по каждому вопросу и время прохождения.

### `knowledge_gaps`

| Поле | Значение |
|---|---|
| `user_id`, `lecture_id` | чей это пробел и к какому материалу относится |
| `concept` | понятие, в котором была ошибка |
| `mistakes`, `successes` | ошибки и успешные повторения |
| `evidence`, `source_ref` | объяснение и место в источнике |
| `next_review` | следующая дата повторения |
| `false_confidence` | число уверенных ошибок |
| `last_confidence` | последняя указанная уверенность |

Ограничение `UNIQUE(user_id, lecture_id, concept)` означает, что один и тот же пробел обновляется, а не создаётся заново после каждой ошибки.

## 8. Инициализация и миграции

`lifespan()` вызывает `init_database()` при запуске FastAPI.

`init_database()`:

1. Создаёт отсутствующие таблицы.
2. Через `ensure_column()` добавляет новые поля в старую базу.
3. Перестраивает старую таблицу пробелов под персональные `user_id`.
4. Создаёт индексы по владельцу и пользователю.
5. Добавляет демонстрационный материал Raft в пустую базу.
6. Обновляет старые материалы, у которых ещё нет source chunks или карточек.

`migrate_knowledge_gaps_ownership()` переименовывает старую таблицу, создаёт новую схему, копирует данные и удаляет старую таблицу. Поэтому переход на аккаунты не уничтожает накопленный прогресс.

При регистрации самого первого пользователя все старые материалы без владельца закрепляются за ним. Встроенный `demo-raft` остаётся общим демонстрационным материалом.

## 9. Регистрация и вход

### Валидация регистрации

`RegistrationRequest` проверяет:

- username: 3–32 символа;
- только латинские буквы, цифры, `.`, `_`, `-`;
- email: 5–160 символов и простая проверка формата;
- полное имя: 2–100 символов;
- пароль: 8–128 символов.

### Хеширование пароля

```python
password_hash = PasswordHash.recommended()
password_hash.hash(request.password)
```

`pwdlib` выбирает рекомендуемую Argon2-конфигурацию. В таблицу `users` попадает только хеш. Восстановить исходный пароль из него нельзя; при входе выполняется проверка `verify()`.

### Защита времени ответа

Если логин не найден, `authenticate_user()` всё равно проверяет пароль против `DUMMY_PASSWORD_HASH`. Это уменьшает разницу времени ответа между «такого пользователя нет» и «пароль неправильный».

### JWT-секрет

`jwt_secret()`:

- использует `STUDYCLOUD_SECRET_KEY`, если он задан;
- требует минимум 32 символа;
- иначе создаёт случайный `data/jwt-secret.key`;
- повторно использует этот файл после перезапуска.

### Содержимое токена

`create_access_token()` записывает:

```json
{
  "sub": "user:<id>",
  "username": "login",
  "iat": "время выдачи",
  "exp": "время окончания"
}
```

### Проверка токена

`get_current_user()` является FastAPI dependency:

```python
current_user = Depends(get_current_user)
```

Она извлекает Bearer-токен, проверяет подпись и срок действия, достаёт `user_id`, затем проверяет, что пользователь существует и активен. При ошибке возвращается `401` и заголовок `WWW-Authenticate: Bearer`.

### Два endpoint входа

- `/api/auth/login` принимает JSON и используется frontend.
- `/api/auth/token` принимает OAuth2 form и используется кнопкой `Authorize` в Swagger.

## 10. Разделение данных пользователей

Ключевая функция — `owned_lecture()`.

Для чтения она разрешает:

```sql
owner_id = текущий пользователь OR id = 'demo-raft'
```

Для изменения и удаления:

```sql
owner_id = текущий пользователь
```

Если материал чужой, сервер отвечает `404`, а не `403`. Так он не подтверждает постороннему пользователю существование чужого ID.

Такая же фильтрация по `user_id` используется для результатов тестов и knowledge gaps. Нельзя получить чужой прогресс, просто подставив другой ID в URL.

## 11. Pydantic-модели

| Модель | Для чего |
|---|---|
| `RegistrationRequest` | регистрация |
| `LoginRequest` | JSON-вход |
| `UserResponse` | безопасные данные пользователя без хеша |
| `TokenResponse` | JWT + профиль |
| `QuizSubmission` | ответы и уверенность |
| `AskRequest` | вопрос к материалу |
| `DefenseRequest` | объяснение своими словами и уверенность |
| `GapReview` | результат повторения `remembered` |
| `StudyPackUpdate` | ручное редактирование конспекта |
| `FlashcardInput` | структура редактируемой карточки |

Pydantic выполняет проверку до входа в функцию endpoint. Невалидные данные получают статус `422`.

## 12. Безопасная загрузка файлов

`upload_lecture()` выполняет последовательность:

1. Берёт только имя файла через `Path(...).name`, отбрасывая путь клиента.
2. Проверяет расширение по белому списку.
3. Читает максимум `25 МБ + 1 байт`.
4. Отклоняет слишком большой или пустой файл.
5. Передаёт содержимое в `extract_document()`.
6. Всегда строит локальный fallback-пакет.
7. При наличии ключа пробует Gemini.
8. Нормализует результат.
9. Сохраняет оригинал под сгенерированным ID, а не пользовательским путём.
10. Записывает материал с `owner_id` текущего пользователя.

Для DOCX, PPTX и EPUB вызывается `validate_archive()`. Эти форматы являются ZIP-контейнерами. Проверка защищает от битых архивов и от ZIP bomb: суммарный распакованный размер не может превышать 100 МБ.

## 13. Извлечение разных форматов

`extract_document()` возвращает:

```python
(полный_текст, количество_единиц, source_chunks)
```

| Формат | Библиотека/способ | Source reference |
|---|---|---|
| PDF | `PdfReader` | `Page 1` |
| PPTX | `Presentation`, текст shape | `Slide 1` |
| DOCX | абзацы и таблицы | `Paragraph 1`, `Table 1` |
| EPUB | XHTML внутри ZIP | `Chapter 1` |
| HTML | собственный `ReadableHTMLParser` | `Section 1` |
| CSV | стандартный `csv.reader` | `Row 1` |
| SRT/VTT | очистка таймкодов и тегов | `Cue 1` |
| TXT/MD | разделение по пустым строкам | `Section 1` |

`ReadableHTMLParser` игнорирует `script`, `style`, `svg`, `noscript`, чтобы код страницы не попадал в учебный текст.

Если извлечено меньше 80 символов, возвращается `422`. Это типично для сканированного PDF без текстового слоя; текущая версия честно сообщает, что нужен OCR.

## 14. Локальный движок генерации

`local_study_material()` позволяет проекту работать без API-ключа.

### Разделение текста

`split_sentences()` делит текст на предложения и отбрасывает слишком короткие фрагменты.

### Ключевые слова

`keywords()`:

1. Находит слова длиной от четырёх символов.
2. Приводит их к нижнему регистру.
3. Удаляет русские и английские stop words.
4. Считает частоту.
5. Возвращает наиболее частые термины.

### Конспект

Частым ключевым словам назначается больший вес. Для предложения считается нормализованная сумма весов. Выбираются семь самых информативных предложений, после чего возвращается их исходный порядок.

### Ключевые идеи

Первые пять выбранных предложений становятся `key_ideas`.

### Вопросы

Движок ищет ключевой термин в предложении, заменяет его на `_____`, формирует четыре варианта ответа и сохраняет:

- правильный индекс;
- понятие;
- объяснение;
- ссылку на источник.

Если таких вопросов мало, добавляются вопросы вида «Какое утверждение подтверждается источником?». Итог — 5–7 вопросов.

### Карточки

Лицевая сторона — ключевой термин, обратная — ключевая идея, плюс `source_ref`.

## 15. Необязательный Gemini

`gemini_study_material()` работает только при наличии `GEMINI_API_KEY`.

В модель передаётся до 60 000 символов с метками источника. Промпт требует только JSON, 5 идей, 5–10 карточек и 5–7 вопросов. Температура `0.2` уменьшает случайность.

Если Gemini недоступен, вернул ошибку или невалидный JSON, исключение не ломает загрузку: функция возвращает `None`, и используется локальный пакет.

`normalize_material()` дополнительно проверяет:

- что у вопроса ровно четыре ответа;
- что `correct_index` находится в диапазоне 0–3;
- что вопросов не меньше пяти;
- что карточек не меньше трёх.

Плохие части ответа заменяются локальным fallback. Это делает внешнюю AI-интеграцию необязательной и отказоустойчивой.

## 16. Source-grounded Q&A

Endpoint: `POST /api/lectures/{id}/ask`.

`ranked_sources()` сравнивает ключевые слова вопроса с каждым source chunk и выбирает до трёх наиболее подходящих фрагментов.

Далее:

- при наличии Gemini вызывается `gemini_answer()` с требованием отвечать только по evidence;
- без Gemini выбираются предложения с максимальным пересечением терминов;
- клиент получает ответ и сами supporting sources.

Это не общий чат: ответ ограничен содержимым конкретного загруженного материала.

## 17. Проверка теста, ProofLoop и BlindSpot

Endpoint: `POST /api/lectures/{id}/quiz`.

Для каждого вопроса пользователь отправляет:

- номер выбранного ответа;
- уверенность от 0 до 100.

Backend:

1. Сравнивает ответ с `correct_index`.
2. Сохраняет всю попытку в `quiz_attempts`.
3. Находит или создаёт `knowledge_gap` по понятию.
4. Увеличивает `mistakes` или `successes`.
5. Если ответ неправильный и уверенность не меньше 75%, увеличивает `false_confidence`.
6. Назначает дату повторения.

Неправильный ответ возвращает понятие на повтор через один день. После первого успешного ответа интервал становится 2 дня, затем 4, 8 и 16 дней.

BlindSpot Detector — это не отдельная модель. Это логика калибровки: высокая уверенность + неправильный ответ означает более опасный пробел, чем неуверенная ошибка.

## 18. Feynman Defense

Endpoint: `POST /api/lectures/{id}/defend`.

Пользователь объясняет тему своими словами и указывает уверенность. Backend:

1. Берёт понятия из карточек и ключевых идей.
2. Токенизирует объяснение.
3. Проверяет прямое упоминание понятия или достаточное пересечение терминов.
4. Делит понятия на `covered` и `missing`.
5. Вычисляет процент покрытия.
6. Для пропущенных понятий создаёт knowledge gaps.
7. При уверенности от 75% помечает пропуски как blind spots.
8. Возвращает evidence и следующий вопрос для объяснения.

Идея функции: пользователь может выбрать правильный вариант случайно, но объяснение своими словами сложнее подделать. Поэтому тест и Feynman Defense дополняют друг друга.

## 19. Knowledge radar и интервальное повторение

`GET /api/radar` сортирует пробелы по формуле приоритета:

```text
priority = mistakes × 2 + false_confidence × 3 - successes
```

Уверенные ошибки имеют дополнительный вес.

`mastery_score()` вычисляет освоение и уменьшает его на 12 пунктов за каждую активную уверенную ошибку. Результат ограничен диапазоном 0–100.

`POST /api/radar/{gap_id}/review` принимает:

```json
{"remembered": true}
```

Если пользователь вспомнил материал, растёт `successes`, уменьшается `false_confidence` и увеличивается интервал. Если не вспомнил — растёт `mistakes`, повтор назначается на следующий день.

## 20. Редактирование, экспорт и удаление

### Редактирование

`PATCH /api/lectures/{id}` разрешает менять только:

- `title`;
- `summary`;
- `key_ideas`;
- `flashcards`.

Список допустимых полей задан явно, а материал должен принадлежать пользователю.

### Экспорт

`GET /api/lectures/{id}/export` собирает Markdown с конспектом, идеями, карточками, вопросами и ссылками на источник.

### Исходный файл

`GET /api/lectures/{id}/source` возвращает оригинал из `data/uploads/` после проверки владельца.

### Удаление

`DELETE /api/lectures/{id}` удаляет запись SQLite и оригинальный файл. Внешние ключи с `ON DELETE CASCADE` удаляют связанные попытки и пробелы. Встроенный demo удалить нельзя.

## 21. Полный список API

| Метод | Путь | Авторизация | Назначение |
|---|---|---:|---|
| POST | `/api/auth/register` | нет | регистрация |
| POST | `/api/auth/login` | нет | JSON-вход frontend |
| POST | `/api/auth/token` | нет | OAuth2-вход Swagger |
| GET | `/api/auth/me` | да | текущий профиль |
| GET | `/api/health` | нет | состояние и форматы |
| GET | `/api/stats` | да | статистика пользователя |
| GET | `/api/lectures` | да | список своих материалов + demo |
| GET | `/api/lectures/{id}` | да | полный учебный пакет |
| POST | `/api/lectures` | да | загрузить материал |
| PATCH | `/api/lectures/{id}` | да | редактировать свой пакет |
| POST | `/api/lectures/{id}/quiz` | да | проверить тест |
| POST | `/api/lectures/{id}/ask` | да | вопрос по источнику |
| POST | `/api/lectures/{id}/defend` | да | Feynman Defense |
| GET | `/api/radar` | да | персональные knowledge gaps |
| POST | `/api/radar/{id}/review` | да | результат повторения |
| GET | `/api/lectures/{id}/export` | да | Markdown-экспорт |
| GET | `/api/lectures/{id}/source` | да | оригинальный файл |
| DELETE | `/api/lectures/{id}` | да | удалить свой материал |

## 22. Коды ошибок

| Код | Когда используется |
|---:|---|
| 400 | пустой запрос изменений, битый архив, неверное содержимое PDF |
| 401 | отсутствующий, просроченный или неправильный JWT; неверный пароль |
| 404 | материал/пробел не найден или принадлежит другому пользователю |
| 409 | username или email уже зарегистрирован |
| 413 | файл или распакованный архив слишком большой |
| 415 | неподдерживаемое расширение |
| 422 | ошибка Pydantic или недостаточно извлекаемого текста |

## 23. Статические файлы

Backend обслуживает frontend двумя частями:

```python
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
```

`/sw.js` отдан отдельным endpoint, чтобы service worker имел scope `/`, а не только `/static/`.

## 24. Запуск

Рекомендуемый вариант:

```powershell
.\run.ps1
```

Ручной:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

В `main.py` также есть блок `if __name__ == "__main__"`, поэтому файл можно запустить напрямую. Но для разработки предпочтительнее Uvicorn с `--reload`.

## 25. Отладка в PyCharm

Конфигурация `Python`:

- Module name: `uvicorn`
- Parameters: `backend.app.main:app --reload --host 127.0.0.1 --port 8000`
- Working directory: корень `StudyCloudAI`
- Interpreter: `.venv\Scripts\python.exe`

Точки остановки можно ставить внутри endpoint, например в `upload_lecture()`, `submit_quiz()` или `get_current_user()`.

## 26. Тесты

Запуск:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Тесты используют отдельную временную базу через `STUDYCLOUD_DATA_DIR`; реальные материалы пользователя не затрагиваются.

Покрываются:

1. Регистрация, вход, JWT и Swagger OAuth2.
2. Запрет анонимного доступа.
3. Общий demo-материал.
4. Изоляция материалов двух пользователей.
5. TXT, HTML, CSV и EPUB.
6. Source-grounded Q&A.
7. Персональные ProofLoop gaps и review.
8. Markdown-экспорт, Feynman Defense и редактирование.
9. PWA и форма авторизации.
10. Неподдерживаемые и пустые файлы.

## 27. Что показать на защите

Порядок демонстрации на 5–7 минут:

1. Показать разделение `backend/`, `frontend/`, `data/`.
2. Открыть Swagger и `POST /api/auth/register` / `/api/auth/token`.
3. Объяснить Argon2: в базе нет исходных паролей.
4. Объяснить JWT dependency `get_current_user()`.
5. Показать `owner_id` и `owned_lecture()` как защиту личных материалов.
6. Загрузить TXT или PDF и показать source references.
7. Пройти тест неправильно с уверенностью 100%.
8. Открыть ProofLoop и показать появившийся blind spot.
9. Показать Feynman Defense.
10. Запустить тесты командой `pytest`.

Короткое описание проекта для защиты:

> StudyCloud — FastAPI-приложение, которое преобразует учебные документы в source-grounded конспекты, карточки и тесты. Пользователи изолированы через JWT и owner_id. Отличие проекта — ProofLoop: система не просто показывает балл, а связывает ошибку и уверенность пользователя с конкретным местом источника и назначает интервальное повторение.

## 28. Частые вопросы преподавателя

### Почему FastAPI?

Он даёт типизированные модели Pydantic, dependency injection для JWT, асинхронные endpoint и автоматическую OpenAPI/Swagger-документацию.

### Почему SQLite?

Для локального MVP она не требует отдельного сервера, поддерживает транзакции и внешние ключи. Для production следующим шагом будет PostgreSQL.

### Почему пароль нельзя расшифровать?

Используется не шифрование, а односторонний Argon2-хеш. При входе сравнивается новый хеш-кандидат с сохранённым.

### Как защищены чужие материалы?

ID пользователя берётся из подписанного JWT, а каждый SQL-запрос фильтруется по `owner_id` или `user_id`. Перед чтением, изменением и удалением выполняется серверная проверка.

### Что произойдёт без Gemini?

Загрузка продолжит работать. Локальный extractive engine создаст конспект, идеи, карточки и тест без сети.

### Почему ответы считаются source-grounded?

Текст при извлечении разбит на chunks с метками страниц/слайдов/секций. Конспекты, карточки, вопросы и ответы сохраняют `source_ref` и показывают evidence.

### В чём уникальная часть?

Комбинация трёх механизмов: ошибка становится knowledge debt, высокая уверенность превращает её в blind spot, а Feynman Defense находит понятия, которые пользователь не смог объяснить своими словами.

## 29. Честные ограничения и дальнейшее развитие

- Сканированные PDF требуют OCR.
- SQLite подходит для локального проекта, но не для большой конкурентной нагрузки.
- Access token хранится в `localStorage`; для production лучше перейти на короткий access token, refresh rotation и защищённые HttpOnly cookies.
- Нужны rate limiting, подтверждение email, восстановление пароля и журнал сессий.
- Большие файлы лучше обрабатывать в фоновой очереди.
- Файлы production-версии следует хранить в S3-совместимом object storage.
- Локальный extractive engine проще LLM и иногда создаёт слабые distractors.
- Качество генерации следует измерять отдельными eval-тестами.

## 30. Как безопасно расширять backend

При добавлении нового защищённого endpoint используйте шаблон:

```python
@app.get("/api/example")
def example(current_user: dict = Depends(get_current_user)):
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM some_table WHERE user_id = ?",
            (current_user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]
```

Правила:

1. Не принимайте `user_id` от frontend — берите его только из JWT.
2. Используйте SQL-параметры `?`, не вставляйте пользовательский текст в строку запроса.
3. Проверяйте владельца перед чтением и записью.
4. Ограничивайте размер строк, списков и файлов через Pydantic и серверные проверки.
5. Не возвращайте `password_hash`, секреты и полный `text_content` без необходимости.
6. Добавляйте тест, в котором второй пользователь пытается получить чужие данные.

## 31. Подробный разбор импортов

Импорты в `main.py` можно разделить на шесть групп.

### Работа с данными и файлами

```python
import io
import csv
import json
import sqlite3
import zipfile
from pathlib import Path
```

- `io.BytesIO` превращает загруженные байты в файловый объект для библиотек PDF, DOCX и PPTX.
- `csv` читает таблицы без дополнительной зависимости.
- `json` сериализует списки вопросов, карточек и source chunks в SQLite.
- `sqlite3` отвечает за локальную базу.
- `zipfile` проверяет EPUB/DOCX/PPTX и читает EPUB.
- `Path` безопасно работает с путями и расширениями.

### Текст и HTML

```python
import re
from html.parser import HTMLParser
```

Регулярные выражения используются для нормализации пробелов, предложений, слов, субтитров и имён экспортируемых файлов. `HTMLParser` извлекает видимый текст без JavaScript и CSS.

### Идентификаторы, время и безопасность

```python
import secrets
import uuid
from datetime import UTC, datetime, timedelta
```

- `uuid` создаёт ID пользователей и материалов.
- `secrets` создаёт криптографически случайный JWT-секрет.
- всё серверное время хранится в UTC, чтобы даты не зависели от часового пояса компьютера.

### FastAPI

```python
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
```

- `Depends` подключает проверку JWT к endpoint.
- `UploadFile` принимает multipart-файл.
- `HTTPException` превращает серверную проверку в понятный HTTP-ответ.
- `FileResponse` отдаёт оригиналы и HTML.
- `PlainTextResponse` отдаёт Markdown.
- OAuth2-классы связывают JWT со Swagger.

### Внешние библиотеки документов

```python
from pypdf import PdfReader
from docx import Document
from pptx import Presentation
```

У каждой библиотеки одна ответственность: прочитать структуру конкретного формата. Генерация учебного пакета не зависит от формата, потому что все extractors приводят документы к общей структуре `chunks`.

### Авторизация и валидация

```python
import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel, Field, field_validator
```

`PyJWT` работает с токенами, `pwdlib` — с Argon2, Pydantic — с телами HTTP-запросов.

## 32. Справочник всех функций

### Инфраструктура

| Функция | Принимает | Возвращает | Побочный эффект |
|---|---|---|---|
| `data_dir()` | ничего | абсолютный `Path` | создаёт `data/uploads` |
| `connect()` | ничего | SQLite connection | открывает БД, включает foreign keys |
| `ensure_column()` | connection, таблица, поле, DDL | ничего | добавляет отсутствующую колонку |
| `migrate_knowledge_gaps_ownership()` | connection | ничего | перестраивает старую таблицу gaps |
| `init_database()` | ничего | ничего | создаёт/обновляет схему и demo |
| `clean_text()` | строку | строку | нет; схлопывает пробелы |

### Авторизация

| Функция | Принимает | Возвращает | Возможная ошибка |
|---|---|---|---|
| `jwt_secret()` | ничего | секретную строку | `RuntimeError`, если env-секрет короче 32 символов |
| `public_user()` | строку SQLite или dict | безопасный профиль | — |
| `create_access_token()` | пользователя | JWT-строку | — |
| `authenticate_user()` | username, password | строку пользователя или `None` | — |
| `get_current_user()` | Bearer token через dependency | dict пользователя | `401` |
| `owned_lecture()` | DB, lecture ID, user ID, режим записи | строку материала | `404` |

### Разбор документов

| Функция/класс | Назначение |
|---|---|
| `ReadableHTMLParser` | собирает видимые текстовые HTML-блоки |
| `html_blocks()` | удобная оболочка над parser |
| `validate_archive()` | проверяет ZIP-контейнер и распакованный размер |
| `extract_document()` | приводит любой поддерживаемый файл к тексту и chunks |

### Генерация

| Функция | Назначение |
|---|---|
| `split_sentences()` | делит нормализованный текст на предложения |
| `keywords()` | считает информативные частые термины |
| `find_source()` | находит chunk с максимальным пересечением слов |
| `local_study_material()` | строит пакет без внешнего AI |
| `gemini_study_material()` | запрашивает JSON-пакет у Gemini |
| `normalize_material()` | исправляет/заменяет некорректный AI-ответ |
| `upgrade_legacy_lectures()` | добавляет старым материалам новые структуры |
| `seed_demo()` | записывает демонстрационную лекцию Raft |

### Представление данных

| Функция | Назначение |
|---|---|
| `row_to_lecture()` | SQLite row → JSON-ready dict, скрывает сырой текст и owner ID |
| `mastery_score()` | считает освоение 0–100 |
| `gap_to_dict()` | добавляет mastery, priority, blind-spot flag |
| `token_response()` | собирает единый ответ login/register |

### Учебная логика

| Функция | Назначение |
|---|---|
| `ranked_sources()` | ранжирует chunks относительно вопроса |
| `gemini_answer()` | отвечает только по выбранному evidence |

## 33. Что происходит при старте процесса

Хронология запуска:

1. Python импортирует `backend.app.main`.
2. Создаются `password_hash`, `oauth2_scheme` и dummy hash.
3. Создаётся объект `FastAPI` с `lifespan`.
4. Uvicorn вызывает startup-часть `lifespan()`.
5. `init_database()` проверяет схему и миграции.
6. FastAPI начинает принимать запросы.
7. `/` отдаёт `frontend/index.html`.
8. Браузер запрашивает JS/CSS через `/static/...`.
9. Frontend проверяет сохранённый токен через `/api/auth/me`.

Почему база инициализируется в lifespan, а не просто на уровне импорта: startup hook гарантирует выполнение именно при запуске приложения и корректно работает с `TestClient`.

## 34. Полная последовательность регистрации

Запрос:

```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "dias",
  "email": "dias@example.com",
  "full_name": "Dias Student",
  "password": "StrongPassword42"
}
```

Внутри сервера:

```text
Pydantic validation
  → генерируется user_id
  → открывается транзакция SQLite
  → проверяется, первый ли это пользователь
  → password_hash.hash(password)
  → INSERT INTO users
  → при первом аккаунте назначаются старые записи
  → SELECT созданного пользователя
  → commit транзакции
  → create_access_token
  → public_user удаляет закрытые поля
```

Ответ:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "e1f...",
    "username": "dias",
    "email": "dias@example.com",
    "full_name": "Dias Student",
    "created_at": "2026-11-16T12:00:00+00:00"
  }
}
```

`password_hash` не попадает ни в `UserResponse`, ни в JSON.

Если уникальный индекс SQLite отклоняет username/email, `IntegrityError` преобразуется в `409 Conflict`.

## 35. Полная последовательность защищённого запроса

Frontend отправляет:

```http
GET /api/lectures
Authorization: Bearer eyJ...
```

`OAuth2PasswordBearer` извлекает строку после `Bearer`. Затем `get_current_user()`:

```text
jwt.decode(token, secret, algorithms=["HS256"])
  → проверка подписи
  → проверка exp
  → проверка формата sub="user:..."
  → SELECT пользователя по ID и is_active=1
  → dict пользователя передаётся endpoint
```

Endpoint не доверяет username или user ID из браузера. Единственный источник ID — проверенный `sub` токена.

## 36. Связи базы данных

```text
users
  id ───────────────┐
                    │ owner_id
                    ▼
                 lectures
                    │ id
           ┌────────┴─────────┐
           │ lecture_id       │ lecture_id
           ▼                  ▼
    quiz_attempts       knowledge_gaps
           ▲                  ▲
           │ user_id          │ user_id
           └──────── users ───┘
```

Поведение удаления:

- удаление пользователя каскадно удаляет его материалы, попытки и gaps;
- удаление материала каскадно удаляет его попытки и gaps;
- физический файл удаляется отдельно, потому что SQLite не управляет файловой системой.

Фактического endpoint удаления пользователя сейчас нет, но схема готова к такому действию.

## 37. Почему JSON хранится внутри SQLite

`key_ideas`, `quiz`, `source_chunks`, `flashcards`, `answers`, `confidences` хранятся как JSON-текст.

Преимущества для MVP:

- не нужно создавать много вспомогательных таблиц;
- учебный пакет читается одной строкой;
- структура вопроса может развиваться без сложной миграции.

Недостатки:

- труднее делать SQL-аналитику по отдельным вопросам;
- нельзя навесить внешний ключ на каждую карточку;
- изменение одного элемента требует перезаписи JSON.

Для production можно нормализовать вопросы/карточки в отдельные таблицы или использовать PostgreSQL JSONB.

## 38. Upload pipeline с конкретными данными

Пусть пользователь загружает `network.pdf`, размер 2 МБ.

```text
filename = "network.pdf"
extension = ".pdf"
contents = 2 МБ bytes
```

После `extract_document()`:

```python
text = "Computer networks ... TCP ..."
units = 14
chunks = [
    {"ref": "Page 1", "text": "..."},
    {"ref": "Page 2", "text": "..."}
]
```

После генерации:

```python
material = {
    "summary": "...",
    "key_ideas": ["..."],
    "quiz": [{...}],
    "flashcards": [{...}],
    "engine": "Local extractive engine"
}
```

Файл сохраняется не как `network.pdf`, а примерно как:

```text
data/uploads/9fa31d2b8c11.pdf
```

Исходное имя остаётся в колонке `filename`. Это предотвращает перезапись файлов с одинаковыми именами.

## 39. Ошибочные сценарии загрузки

### Расширение `.pdf`, но содержимое не PDF

Проверяется сигнатура `%PDF`. Ответ: `400`.

### Пустой файл

Ответ: `400 The uploaded file is empty`.

### 26 МБ

Сервер читает 25 МБ + 1 байт, обнаруживает превышение и возвращает `413`, не загружая произвольный объём в память.

### Битый DOCX

`validate_archive()` видит, что байты не являются ZIP, и возвращает `400`.

### ZIP bomb

Сумма `file_size` элементов превышает 100 МБ: `413` до распаковки всего содержимого.

### PDF-скан

Страницы существуют, но `extract_text()` возвращает пустые строки. Итоговый текст короче 80 символов: `422` с предложением использовать OCR.

## 40. Пример работы локального summarizer

Исходный упрощённый текст:

```text
TCP establishes a reliable connection. TCP numbers segments.
Acknowledgements confirm delivery. Lost segments are retransmitted.
```

Частые содержательные термины могут получиться такими:

```text
TCP, segments, connection, acknowledgements, delivery
```

Самым ранним терминам в рейтинге назначается больший вес. Предложение с `TCP` и `segments` получает высокий score. Из семи лучших предложений формируется summary, а из пяти первых — key ideas.

Для вопроса слово `segments` заменяется:

```text
Which term best completes this statement?
TCP numbers _____.
```

`find_source()` сравнивает множество слов предложения со словами каждого chunk и прикрепляет страницу с максимальным пересечением.

Это extractive, а не generative подход: локальный движок в основном выбирает и преобразует существующие предложения, поэтому меньше рискует добавить внешний факт.

## 41. Разбор нормализации ответа Gemini

Даже если модель обещает JSON, backend не доверяет структуре без проверки.

Примеры проблем:

```json
{"options": ["A", "B"]}
```

Такой вопрос имеет не четыре варианта — options заменяются fallback-вариантами.

```json
{"correct_index": 8}
```

Индекс вне диапазона 0–3 — заменяется корректным локальным индексом.

Если после нормализации вопросов меньше пяти, весь quiz берётся из local engine. Если карточек меньше трёх, берутся локальные карточки.

Следовательно, внешний AI улучшает контент, но не определяет работоспособность структуры API.

## 42. Расчёт Quiz + BlindSpot на примере

Пусть вопрос относится к понятию `Leader election`.

Пользователь выбрал неправильный ответ и указал уверенность 90%.

До ответа:

```text
mistakes = 1
successes = 0
false_confidence = 0
```

После ответа:

```text
mistakes = 2
successes = 0
false_confidence = 1
last_confidence = 90
next_review = завтра
```

Почему `false_confidence` увеличился: ответ неправильный и `90 >= 75`.

Приоритет:

```text
priority = mistakes × 2 + false_confidence × 3 - successes
priority = 2 × 2 + 1 × 3 - 0 = 7
```

Обычная неуверенная ошибка дала бы приоритет 4. Значит, уверенная ошибка поднимается в radar выше.

## 43. Расчёт mastery на примере

Формула:

```text
base = round(100 × (successes + 0.25) / (mistakes + successes + 0.5))
mastery = clamp(base - false_confidence × 12, 0, 100)
```

Пусть:

```text
mistakes = 3
successes = 1
false_confidence = 1
```

Тогда:

```text
base = round(100 × 1.25 / 4.5) = 28
mastery = 28 - 12 = 16
```

Небольшие значения `0.25` и `0.5` являются сглаживанием, чтобы первые ответы не давали слишком резкие крайние оценки.

## 44. Интервальное повторение на примере

После успешного ответа `successes` увеличивается до расчёта даты.

```text
successes=1 → 2^1 = 2 дня
successes=2 → 2^2 = 4 дня
successes=3 → 2^3 = 8 дней
successes>=4 → 2^4 = 16 дней
```

После ответа «не вспомнил» интервал сбрасывается на один день, а `mistakes` увеличивается.

Это упрощённая spaced-repetition модель. Production-версия может использовать SM-2, FSRS или обучаемую модель памяти.

## 45. Feynman Defense на примере

Понятия материала:

```text
Leader election
Replicated log
Majority commitment
Randomized timeout
```

Объяснение пользователя:

```text
Raft выбирает лидера, который копирует команды на другие серверы.
```

Покрыты `Leader election` и частично `Replicated log`. Пропущены `Majority commitment` и `Randomized timeout`.

Если уверенность 100%, оба пропуска создают `false_confidence`. Ответ содержит:

```json
{
  "coverage": 50,
  "confidence": 100,
  "covered": ["Leader election", "Replicated log"],
  "missing": ["Majority commitment", "Randomized timeout"],
  "blind_spots": ["..."],
  "next_prompt": "Explain how Majority commitment connects to the main topic."
}
```

Алгоритм не оценивает литературный стиль; он проверяет покрытие набора source-derived concepts.

## 46. Примеры API-запросов через PowerShell

### Регистрация

```powershell
$body = @{
  username = "dias"
  email = "dias@example.com"
  full_name = "Dias Student"
  password = "StrongPassword42"
} | ConvertTo-Json

$session = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/auth/register" `
  -ContentType "application/json" `
  -Body $body
```

### Сохранение заголовка авторизации

```powershell
$headers = @{ Authorization = "Bearer $($session.access_token)" }
```

### Получение материалов

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/lectures" `
  -Headers $headers
```

### Загрузка файла

Для загрузки удобнее использовать Swagger или `curl.exe`:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/lectures" `
  -H "Authorization: Bearer $($session.access_token)" `
  -F "file=@C:\path\notes.txt"
```

### Вопрос к материалу

```powershell
$question = @{ question = "What is leader election?" } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/lectures/demo-raft/ask" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $question
```

## 47. Как пользоваться Swagger

1. Запустить сервер.
2. Зарегистрироваться через обычный интерфейс.
3. Открыть `http://127.0.0.1:8000/docs`.
4. Нажать `Authorize`.
5. Ввести username и password.
6. Swagger отправит форму на `/api/auth/token`.
7. Полученный Bearer token автоматически добавится к следующим запросам.
8. Открыть нужный endpoint, нажать `Try it out`, заполнить данные и выполнить запрос.

Swagger генерируется из декораторов FastAPI, type hints, Pydantic-моделей и `response_model`.

## 48. Транзакции и целостность

Регистрация выполняет создание пользователя и перенос старых данных в одной транзакции. Если INSERT пользователя завершился ошибкой, перенос не будет частично применён.

Quiz endpoint сохраняет попытку и обновляет все knowledge gaps внутри одного `with connect()`. Исключение откатывает транзакцию.

Параметризованный SQL:

```python
db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

отделяет SQL-код от пользовательского значения и защищает от SQL injection. Исключение — динамический список полей PATCH, но он собирается только из жёсткого allowlist `allowed`.

## 49. Security review текущей версии

### Уже реализовано

- Argon2 вместо хранения паролей.
- Случайный JWT-secret.
- Проверка срока JWT.
- Dummy password hash для уменьшения timing leak.
- Case-insensitive уникальность username/email.
- Pydantic-валидация.
- Параметризованный SQL.
- Проверка owner/user ID на сервере.
- 404 вместо раскрытия чужого объекта.
- Белый список расширений.
- Ограничение размера файла и архива.
- Нормализация пользовательского имени файла.
- Секреты и БД исключены из Git/Docker context.

### Что нужно для публичного production

- HTTPS; без него токен можно перехватить в сети.
- Rate limiting входа и загрузки.
- Refresh tokens с ротацией и отзывом.
- HttpOnly/SameSite cookie или усиленная CSP при localStorage.
- Email verification и password reset.
- Проверка MIME/magic bytes для всех форматов, не только PDF/ZIP.
- Антивирусная проверка загрузок.
- Audit log и мониторинг подозрительных входов.
- Ограничение количества материалов на пользователя.

## 50. Производительность и масштабирование

Текущий MVP читает весь файл в память и обрабатывает его в запросе. Для 25 МБ и локального использования это приемлемо, но при большом числе пользователей появятся ограничения.

Production-путь:

```text
FastAPI API
  → загрузка в object storage
  → задача в очереди
  → worker извлекает текст
  → worker вызывает AI
  → PostgreSQL хранит статус
  → frontend опрашивает job или получает WebSocket/SSE
```

SQLite имеет ограниченную конкурентную запись. PostgreSQL лучше подходит для нескольких API-инстансов.

Gemini-запрос имеет timeout 75 секунд для учебного пакета и 45 секунд для ответа. При ошибке приложение использует fallback, поэтому сетевой сбой не превращается в полный отказ.

## 51. Как читать traceback

### `ModuleNotFoundError`

Обычно выбран неправильный interpreter или не установлены `backend/requirements.txt`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### `can't open file app/main.py`

Старая PyCharm-конфигурация указывает на путь до разделения папок. Используйте модуль:

```text
uvicorn backend.app.main:app --reload
```

### `401 Not authenticated`

Нет заголовка `Authorization` или frontend потерял токен. Выполнить вход заново.

### `Could not validate credentials`

Токен испорчен, истёк или JWT-secret изменился.

### `422 Not enough readable text`

Документ пустой, слишком короткий или PDF является сканом.

### `409 This username is already registered`

Сработал уникальный индекс SQLite. Нужно выбрать другой username.

## 52. Как устроены backend-тесты

В начале `test_app.py` до импорта приложения устанавливается временная папка:

```python
os.environ["STUDYCLOUD_DATA_DIR"] = tempfile.mkdtemp(...)
```

Это важно: `main.py` читает переменную при обращении к `data_dir()`, и тесты не касаются настоящей `data/studycloud.db`.

Helper `register()` каждый раз создаёт уникальный username через UUID и возвращает готовый Bearer header.

Тест изоляции создаёт двух пользователей:

```text
User A загружает файл
User A видит ID
User B не видит ID в списке
User B получает 404 по прямому URL
```

Это сильнее обычной проверки списка: тест доказывает, что нельзя обойти защиту прямой подстановкой ID.

## 53. Как добавить новый формат файла

Допустим, нужно добавить `.json`.

1. Добавить `.json` в `SUPPORTED_EXTENSIONS`.
2. Добавить ветку в `extract_document()`.
3. Преобразовать структуру в список:

```python
chunks = [
    {"ref": "Object 1", "text": "нормализованный текст"}
]
```

4. Определить корректное значение `units`.
5. Добавить формат в frontend `supportedExtensions` и `accept` input.
6. Добавить тест с реальным минимальным файлом.
7. Проверить пустой, битый и слишком большой вариант.

Главный контракт extractor: каждый chunk обязан иметь строковые `ref` и `text`.

## 54. Как добавить новую таблицу

Пример: `study_sessions`.

1. Добавить `CREATE TABLE IF NOT EXISTS` в `init_database()`.
2. Связать `user_id` внешним ключом.
3. Создать индекс по часто используемому фильтру.
4. Для старой базы использовать `ensure_column()` или отдельную migration-функцию.
5. Все запросы фильтровать по ID из JWT.
6. Добавить тест двух пользователей.

Пример схемы:

```sql
CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

## 55. Как добавить endpoint правильно

Пример персональной статистики с параметром:

```python
class SessionCreate(BaseModel):
    duration_seconds: int = Field(ge=1, le=86400)


@app.post("/api/sessions", status_code=201)
def create_session(
    request: SessionCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO study_sessions (user_id, started_at, duration_seconds) VALUES (?, ?, ?)",
            (current_user["id"], datetime.now(UTC).isoformat(), request.duration_seconds),
        )
        row = db.execute(
            "SELECT * FROM study_sessions WHERE id = ? AND user_id = ?",
            (cursor.lastrowid, current_user["id"]),
        ).fetchone()
    return dict(row)
```

Здесь присутствуют все основные элементы проекта: Pydantic, JWT dependency, UTC, параметризованный SQL, `user_id` из токена и возврат своей записи.

## 56. Как отлаживать upload пошагово

Поставить breakpoints:

1. Первая строка `upload_lecture()` — проверить `file.filename`.
2. После `contents = await file.read(...)` — проверить размер.
3. После `extract_document()` — посмотреть `units` и первые chunks.
4. После `local_study_material()` — проверить quiz/flashcards.
5. После Gemini — сравнить `generated` и fallback.
6. Перед INSERT — проверить `current_user["id"]`.
7. После `row_to_lecture()` — убедиться, что сырой `text_content` и `owner_id` не уходят клиенту.

В PyCharm можно открыть Evaluate Expression и выполнить:

```python
chunks[:2]
material["quiz"][0]
current_user["id"]
```

## 57. Как доказать, что это backend-работа на неделю

Разложение по задачам:

### День 1 — архитектура и база

- схема четырёх таблиц;
- миграции;
- foreign keys и индексы;
- сохранение старых данных.

### День 2 — auth

- Pydantic-регистрация;
- Argon2;
- JWT;
- OAuth2 Swagger;
- dependency текущего пользователя.

### День 3 — персональные данные

- `owner_id`/`user_id`;
- фильтрация каждого запроса;
- безопасные 404;
- first-user migration.

### День 4 — ingestion

- поддержка разных библиотек;
- единый формат chunks;
- source references;
- ограничения файлов и архивов.

### День 5 — learning engine

- локальный summarizer;
- quiz/flashcards;
- Gemini fallback и нормализация.

### День 6 — ProofLoop

- попытки;
- уверенность;
- blind spots;
- mastery/priority;
- spaced review;
- Feynman Defense.

### День 7 — качество

- Swagger;
- тесты изоляции;
- Docker;
- CI;
- документация и обработка ошибок.

## 58. Расширенные вопросы на защите

### Почему `owner_id` нельзя брать из request body?

Пользователь мог бы отправить ID другого аккаунта. Поэтому owner определяется сервером из подписанного JWT.

### Почему `owned_lecture()` возвращает 404, а не 403?

`403` подтвердил бы существование объекта. `404` не раскрывает, есть ли такой чужой материал.

### Зачем одновременно local engine и Gemini?

Local engine гарантирует доступность без ключа и сети. Gemini повышает качество. Нормализатор сохраняет контракт ответа при проблемах модели.

### Почему не хранить JWT в базе?

Access JWT самодостаточен и проверяется подписью. Для отзыва сессий production-версия добавит refresh-token table или denylist.

### Что произойдёт при смене JWT-secret?

Все старые токены перестанут проходить проверку. Пользователи должны войти снова; данные аккаунтов не удалятся.

### Есть ли SQL injection в динамическом PATCH?

Имена колонок берутся не из request напрямую, а после фильтрации жёстким множеством `allowed`. Значения всё равно передаются параметрами `?`.

### Почему source chunks важнее просто полного текста?

Полный текст позволяет искать, но не объясняет происхождение утверждения. Chunks сохраняют страницы, слайды и секции, поэтому ответ можно проверить.

### Почему `false_confidence` не просто boolean?

Счётчик сохраняет повторяемость уверенных ошибок. Несколько таких ошибок повышают priority сильнее одной.

### Почему demo доступен всем, но не редактируется?

Он позволяет проверить продукт сразу после регистрации, при этом общая запись защищена от изменений конкретным пользователем.

## 59. Ментальная модель всего backend

Backend удобно запомнить как четыре слоя:

```text
HTTP слой
  FastAPI routes + Pydantic + Swagger

Security слой
  Argon2 + JWT + get_current_user + ownership

Domain слой
  extraction + study pack + quiz + ProofLoop + Feynman

Persistence слой
  SQLite + JSON fields + uploads directory
```

Когда нужно понять любую функцию, задайте четыре вопроса:

1. Какие данные она получает от HTTP-слоя?
2. Как проверяется пользователь и входные значения?
3. Какое учебное правило она реализует?
4. Что она читает или изменяет в SQLite/файлах?

Если на эти четыре вопроса есть ответы, логика конкретного участка backend полностью понятна.

