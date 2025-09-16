import json
import os
import logging
import requests
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handler(event, context):
    """
    Function 2: Weather Forecast
    - Получает координаты и диапазон дат
    - Обращается к Yandex Weather API для получения погодных данных
    - Возвращает JSON с прогнозом погоды
    """
    try:
        # Парсим входные данные
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
        
        lat = body.get('lat')
        lon = body.get('lon')
        days = int(body.get('days', 5))
        
        if lat is None or lon is None:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Latitude and longitude parameters are required'
                })
            }
        
        logger.info(f"Getting weather forecast for coordinates: {lat}, {lon}, days: {days}")
        
        # Получаем прогноз погоды
        forecast_data = get_weather_forecast(lat, lon, days)
        
        return {
            'statusCode': 200,
            'body': json.dumps(forecast_data, ensure_ascii=False)
        }
        
    except Exception as e:
        logger.error(f"Error in weather forecast function: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }

def get_weather_forecast(lat, lon, days):
    """Получает прогноз погоды из Yandex Weather API по координатам"""
    try:
        # Используем Yandex Weather API
        api_key = os.environ.get('WEATHER_API_KEY')
        
        if not api_key:
            # Если нет API ключа, возвращаем mock данные
            logger.warning("No Yandex Weather API key provided, returning mock data")
            return generate_mock_forecast_by_coords(lat, lon, days)
        
        # URL Yandex Weather API
        weather_url = "https://api.weather.yandex.ru/v2/forecast"
        
        # Параметры запроса
        headers = {
            'X-Yandex-API-Key': api_key
        }
        
        params = {
            'lat': lat,
            'lon': lon,
            'lang': 'ru_RU',
            'limit': min(days, 7),  # Yandex API поддерживает до 7 дней
            'hours': False,  # Получаем только дневные прогнозы
            'extra': False   # Без дополнительных данных
        }
        
        response = requests.get(weather_url, headers=headers, params=params, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Yandex Weather API error: {response.status_code}")
            if response.status_code == 403:
                logger.error("API key invalid or rate limit exceeded")
            return generate_mock_forecast_by_coords(lat, lon, days)
        
        weather_data = response.json()
        
        # Обрабатываем данные от Yandex Weather API
        forecast = process_yandex_weather_data(weather_data, days)
        
        return forecast
        
    except requests.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return generate_mock_forecast_by_coords(lat, lon, days)
    except Exception as e:
        logger.error(f"Error getting weather forecast: {str(e)}")
        return generate_mock_forecast_by_coords(lat, lon, days)

def process_yandex_weather_data(data, requested_days):
    """Обрабатывает данные от Yandex Weather API"""
    try:
        # Получаем информацию о местоположении
        location_info = data.get('info', {})
        location_name = f"{location_info.get('lat', 0):.3f}, {location_info.get('lon', 0):.3f}"
        
        # Пытаемся получить более читаемое название места
        if 'tzinfo' in location_info:
            tz_name = location_info['tzinfo'].get('name', '')
            if '/' in tz_name:
                location_name = tz_name.split('/')[-1].replace('_', ' ')
        
        # Текущая погода
        fact = data.get('fact', {})
        
        # Прогнозы по дням
        forecasts = data.get('forecasts', [])
        forecast_list = []
        
        for i, day_forecast in enumerate(forecasts[:requested_days]):
            date_str = day_forecast.get('date', '')
            
            # Информация о дне
            day_info = day_forecast.get('parts', {}).get('day', {})
            
            # Температура
            temp_avg = day_info.get('temp_avg')
            temp_min = day_info.get('temp_min') 
            temp_max = day_forecast.get('parts', {}).get('day_short', {}).get('temp_max')
            feels_like = day_info.get('feels_like', temp_avg)
            
            # Используем данные из fact для первого дня, если доступны
            if i == 0 and fact:
                temp_avg = fact.get('temp', temp_avg)
                feels_like = fact.get('feels_like', feels_like)
            
            # Погодные условия
            condition = day_info.get('condition', 'clear')
            condition_description = get_condition_description(condition)
            
            forecast_item = {
                'date': date_str,
                'temperature': {
                    'day': int(temp_avg) if temp_avg is not None else 0,
                    'min': int(temp_min) if temp_min is not None else int(temp_avg or 0) - 3,
                    'max': int(temp_max) if temp_max is not None else int(temp_avg or 0) + 3,
                    'feels_like': int(feels_like) if feels_like is not None else int(temp_avg or 0)
                },
                'weather': {
                    'main': condition.title(),
                    'description': condition_description,
                    'icon': get_weather_icon_from_condition(condition)
                },
                'humidity': day_info.get('humidity', 50),
                'pressure': day_info.get('pressure_mm', 760),
                'wind_speed': day_info.get('wind_speed', 0),
                'clouds': get_cloudiness_from_condition(condition),
                'wind_direction': day_info.get('wind_dir', 'n')
            }
            
            forecast_list.append(forecast_item)
        
        return {
            'location': location_name,
            'country': 'RU',
            'coordinates': f"{location_info.get('lat', 0)}, {location_info.get('lon', 0)}",
            'forecast_days': len(forecast_list),
            'forecast': forecast_list,
            'generated_at': datetime.now().isoformat(),
            'data_source': 'Yandex Weather API'
        }
        
    except Exception as e:
        logger.error(f"Error processing Yandex Weather data: {str(e)}")
        return generate_mock_forecast_by_coords(
            data.get('info', {}).get('lat', 0),
            data.get('info', {}).get('lon', 0),
            requested_days
        )

def get_condition_description(condition):
    """Переводит коды погодных условий Yandex API в описания"""
    conditions = {
        'clear': 'ясно',
        'partly-cloudy': 'малооблачно', 
        'cloudy': 'облачно',
        'overcast': 'пасмурно',
        'light-rain': 'небольшой дождь',
        'rain': 'дождь',
        'heavy-rain': 'сильный дождь',
        'showers': 'ливень',
        'wet-snow': 'дождь со снегом',
        'light-snow': 'небольшой снег',
        'snow': 'снег',
        'snow-showers': 'снегопад',
        'hail': 'град',
        'thunderstorm': 'гроза',
        'thunderstorm-with-rain': 'дождь с грозой',
        'thunderstorm-with-hail': 'гроза с градом'
    }
    return conditions.get(condition, condition)

def get_weather_icon_from_condition(condition):
    """Возвращает emoji иконку для погодного условия"""
    icons = {
        'clear': '☀️',
        'partly-cloudy': '⛅',
        'cloudy': '☁️', 
        'overcast': '☁️',
        'light-rain': '🌦️',
        'rain': '🌧️',
        'heavy-rain': '🌧️',
        'showers': '🌧️',
        'wet-snow': '🌨️',
        'light-snow': '❄️',
        'snow': '❄️',
        'snow-showers': '🌨️',
        'hail': '🌨️',
        'thunderstorm': '⛈️',
        'thunderstorm-with-rain': '⛈️',
        'thunderstorm-with-hail': '⛈️'
    }
    return icons.get(condition, '🌤️')

def get_cloudiness_from_condition(condition):
    """Возвращает примерную облачность в процентах на основе условий"""
    cloudiness = {
        'clear': 10,
        'partly-cloudy': 30,
        'cloudy': 70,
        'overcast': 100,
        'light-rain': 80,
        'rain': 90,
        'heavy-rain': 100,
        'showers': 90,
        'wet-snow': 90,
        'light-snow': 80,
        'snow': 90,
        'snow-showers': 100,
        'hail': 100,
        'thunderstorm': 90,
        'thunderstorm-with-rain': 95,
        'thunderstorm-with-hail': 100
    }
    return cloudiness.get(condition, 50)

def generate_mock_forecast_by_coords(lat, lon, days):
    """Генерирует mock данные о погоде для координат"""
    logger.info(f"Generating mock forecast for coordinates {lat}, {lon}")
    
    import random
    
    # Определяем примерное название места по координатам (очень упрощенно)
    location_name = f"Location ({lat:.2f}, {lon:.2f})"
    
    # Примерная температура в зависимости от широты и времени года
    import datetime
    month = datetime.datetime.now().month
    
    if abs(lat) > 60:
        base_temp = random.randint(-15, 5) if month in [11,12,1,2,3] else random.randint(-5, 15)
    elif abs(lat) > 40:
        base_temp = random.randint(-5, 15) if month in [11,12,1,2,3] else random.randint(5, 25)
    else:
        base_temp = random.randint(10, 25) if month in [11,12,1,2,3] else random.randint(20, 35)
    
    forecast_list = []
    
    weather_conditions = [
        {'condition': 'clear', 'description': 'ясно', 'icon': '☀️'},
        {'condition': 'partly-cloudy', 'description': 'малооблачно', 'icon': '⛅'},
        {'condition': 'cloudy', 'description': 'облачно', 'icon': '☁️'},
        {'condition': 'rain', 'description': 'дождь', 'icon': '🌧️'},
        {'condition': 'snow', 'description': 'снег', 'icon': '❄️'} if base_temp < 5 else {'condition': 'clear', 'description': 'ясно', 'icon': '☀️'}
    ]
    
    for i in range(days):
        date = datetime.datetime.now() + timedelta(days=i)
        temp_variation = random.randint(-5, 5)
        temp = base_temp + temp_variation
        
        weather = random.choice(weather_conditions)
        
        forecast_list.append({
            'date': date.strftime('%Y-%m-%d'),
            'temperature': {
                'day': temp,
                'min': temp - random.randint(2, 5),
                'max': temp + random.randint(2, 5),
                'feels_like': temp + random.randint(-2, 2)
            },
            'weather': {
                'main': weather['condition'].title(),
                'description': weather['description'],
                'icon': weather['icon']
            },
            'humidity': random.randint(40, 80),
            'pressure': random.randint(745, 770),
            'wind_speed': round(random.uniform(1.0, 8.0), 1),
            'clouds': get_cloudiness_from_condition(weather['condition']),
            'wind_direction': random.choice(['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'])
        })
    
    return {
        'location': location_name,
        'country': 'RU',
        'coordinates': f"{lat}, {lon}",
        'forecast_days': days,
        'forecast': forecast_list,
        'generated_at': datetime.now().isoformat(),
        'data_source': 'Mock data для демонстрации',
        'note': 'Демонстрационные данные - получите API ключ Yandex Weather для реальных данных'
    }