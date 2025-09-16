# Simple Weather Forecast Serverless Service

Простое serverless приложение для прогноза погоды с автоматическим определением геолокации пользователя в браузере.

## 🏗️ Архитектура

```
Пользователь заходит на сайт
         ↓
Браузер автоматически определяет геолокацию
         ↓
API Gateway получает запрос с координатами
         ↓
Function 1 (Weather Context) → сохраняет статистику в PostgreSQL
         ↓
Function 2 (Weather Forecast) → получает данные о погоде из OpenWeatherMap API
         ↓
Результат отображается пользователю
```

### Компоненты:

1. **API Gateway** - принимает запросы, отдает HTML страницу и API endpoints
2. **Object Storage** - хранит HTML страницу  
3. **Function 1 (Weather Context)** - обрабатывает координаты, сохраняет статистику в БД
4. **Function 2 (Weather Forecast)** - получает прогноз погоды по координатам
5. **Managed PostgreSQL** - хранит статистику запросов
6. **HTML страница** - автоматически определяет геолокацию и показывает погоду

## 🚀 Быстрый старт

### 1. Настройка

Отредактируйте `terraform.tfvars`:
```hcl
cloud_id  = "your-cloud-id"
folder_id = "your-folder-id"
sa_key_file = "/path/to/service-account-key.json"

# Опционально - API ключ для реальных данных о погоде
weather_api_key = "your-openweathermap-api-key"
```

### 2. Сборка и развертывание

```bash
# Создание архивов функций
chmod +x build_functions.sh
./build_functions.sh

# Развертывание
terraform init
terraform plan
terraform apply
```

### 3. Использование

После развертывания откройте URL из outputs:
```
weather_app_url = "https://d5dxxxxx.apigw.yandexcloud.net"
```

Просто откройте эту ссылку в браузере - все остальное произойдет автоматически!

## 📱 Как это работает

1. **Пользователь заходит на сайт** - браузер загружает простую HTML страницу
2. **Автоматическое определение геолокации** - JavaScript запрашивает координаты у браузера
3. **Запрос к API** - отправляются координаты на `/weather?lat=55.7558&lon=37.6176`
4. **Function 1** сохраняет статистику в PostgreSQL и вызывает Function 2
5. **Function 2** получает данные о погоде из OpenWeatherMap API (или mock данные)
6. **Отображение результата** - прогноз погоды показывается на странице

## 🔧 API Endpoints

### `GET /`
Главная страница с автоопределением геолокации

### `GET /weather?lat=55.7558&lon=37.6176&days=5&user_id=web_user`
API для получения прогноза погоды по координатам

**Параметры:**
- `lat` (обязательный) - широта
- `lon` (обязательный) - долгота  
- `days` (опционально) - количество дней прогноза (1-7, по умолчанию 5)
- `user_id` (опционально) - идентификатор пользователя для статистики

**Пример ответа:**
```json
{
  "location": "Moscow",
  "country": "RU",
  "coordinates": "55.7558, 37.6176",
  "forecast_days": 5,
  "forecast": [
    {
      "date": "2025-09-16",
      "temperature": {
        "day": 15,
        "min": 12,
        "max": 18,
        "feels_like": 14
      },
      "weather": {
        "main": "Clear",
        "description": "ясно"
      },
      "humidity": 65,
      "wind_speed": 3.2
    }
  ]
}
```

### `GET /health`
Проверка состояния сервиса

## 🎯 Особенности

### ✅ Что работает
- **Автоматическое определение геолокации** в браузере
- **Простой и понятный UI** без лишних элементов
- **Serverless архитектура** - масштабируется автоматически
- **Сохранение статистики** всех запросов в PostgreSQL
- **Mock данные** если нет API ключа OpenWeatherMap
- **Отзывчивый дизайн** для мобильных устройств

### 🔧 Настройка Yandex Weather API

Для получения реальных данных о погоде:

1. Перейдите на https://yandex.ru/dev/weather/
2. Зарегистрируйтесь и получите API ключ (есть бесплатный тариф)
3. Добавьте в `terraform.tfvars`:
```hcl
weather_api_key = "your-yandex-weather-api-key"
```
4. Выполните `terraform apply`

**Преимущества Yandex Weather API:**
- ✅ **Более точные данные** для территории России и СНГ
- ✅ **Русскоязычные описания** погодных условий
- ✅ **Интеграция с экосистемой** Yandex Cloud
- ✅ **До 7 дней прогноза** в бесплатном тарифе
- ✅ **Подробная информация** о ветре, давлении, влажности

Без API ключа приложение работает с демонстрационными данными.

## 📊 Мониторинг

### Логи функций
В Yandex Cloud Console: Cloud Functions → Ваша функция → Логи

### Статистика в БД
```sql
SELECT user_id, coordinates, forecast_days, request_time 
FROM weather_requests 
ORDER BY request_time DESC;
```

### Тестирование API
```bash
# Проверка здоровья
curl "https://YOUR-API-GATEWAY.apigw.yandexcloud.net/health"

# Тест API с координатами Москвы
curl "https://YOUR-API-GATEWAY.apigw.yandexcloud.net/weather?lat=55.7558&lon=37.6176&days=3"
```

## 🗂️ Структура проекта

```
├── hw07.tf              # Основная Terraform конфигурация
├── providers.tf         # Настройки провайдеров
├── variables.tf         # Переменные
├── versions.tf          # Версии Terraform и провайдеров
├── terraform.tfvars     # Значения переменных
├── build_functions.sh   # Скрипт сборки функций
├── static/
│   └── index.html      # HTML страница (создается скриптом)
├── weather_context.zip  # Function 1 (создается скриптом)
├── weather_forecast.zip # Function 2 (создается скриптом)
└── README.md           # Эта инструкция
```

## 🧹 Очистка ресурсов

```bash
terraform destroy
```

## 💡 Возможные улучшения

- Добавить кэширование результатов
- Интегрировать с другими погодными API
- Добавить уведомления о погодных предупреждениях
- Создать мобильное приложение
- Добавить исторические данные о погоде

## 🔍 Troubleshooting

### Ошибка геолокации
Пользователь должен разрешить доступ к геолокации в браузере

### Нет данных о погоде
- Проверьте API ключ OpenWeatherMap
- Посмотрите логи функций в консоли Yandex Cloud

### Ошибки БД
- Убедитесь, что PostgreSQL кластер запущен
- Проверьте настройки сети и security groups

---

**Создано для демонстрации serverless архитектуры Yandex Cloud**