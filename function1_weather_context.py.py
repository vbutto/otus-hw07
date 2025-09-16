import json
import os
import logging
import psycopg2
import requests
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handler(event, context):
    """
    Function 1: Weather Context
    - Парсит координаты из запроса
    - Сохраняет статистику запросов в PostgreSQL
    - Вызывает Function 2 для получения прогноза погоды
    - Возвращает результат в API Gateway
    """
    try:
        # Парсим параметры запроса (координаты)
        query_params = event.get('queryStringParameters', {})
        if not query_params:
            query_params = {}
        
        lat = query_params.get('lat')
        lon = query_params.get('lon')
        days = int(query_params.get('days', 5))
        user_id = query_params.get('user_id', 'anonymous')
        
        if not lat or not lon:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({
                    'error': 'Latitude and longitude parameters are required'
                })
            }
        
        try:
            lat_float = float(lat)
            lon_float = float(lon)
        except ValueError:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({
                    'error': 'Invalid latitude or longitude format'
                })
            }
        
        # Валидация дней прогноза
        if days < 1 or days > 7:
            days = 5
        
        logger.info(f"Processing weather request for coordinates: {lat_float}, {lon_float}, days: {days}, user: {user_id}")
        
        # Сохраняем статистику в базу данных
        save_request_stats(user_id, f"{lat_float},{lon_float}", days)
        
        # Вызываем Function 2 для получения прогноза погоды
        forecast_result = call_weather_forecast_function(lat_float, lon_float, days)
        
        # Возвращаем результат
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(forecast_result, ensure_ascii=False)
        }
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }

def save_request_stats(user_id, coordinates, days):
    """Сохраняет статистику запросов в PostgreSQL"""
    try:
        # Подключение к базе данных
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'),
            port=os.environ.get('DB_PORT', '6432'),
            database=os.environ.get('DB_NAME'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD'),
            sslmode='require'
        )
        
        cursor = conn.cursor()
        
        # Создаем таблицу если её нет
        create_table_query = """
        CREATE TABLE IF NOT EXISTS weather_requests (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255),
            coordinates VARCHAR(255),
            location VARCHAR(255),
            forecast_days INTEGER,
            request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address VARCHAR(45)
        );
        """
        cursor.execute(create_table_query)
        
        # Вставляем запись о запросе
        insert_query = """
        INSERT INTO weather_requests (user_id, coordinates, forecast_days)
        VALUES (%s, %s, %s);
        """
        cursor.execute(insert_query, (user_id, coordinates, days))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Successfully saved request stats for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error saving request stats: {str(e)}")
        # Не прерываем выполнение если не удалось сохранить статистику

def call_weather_forecast_function(lat, lon, days):
    """Вызывает Function 2 для получения прогноза погоды"""
    try:
        function_id = os.environ.get('FORECAST_FUNCTION_ID')
        
        # URL для вызова Cloud Function
        function_url = f"https://functions.yandexcloud.net/{function_id}"
        
        # Параметры для Function 2
        payload = {
            'lat': lat,
            'lon': lon,
            'days': days
        }
        
        # Вызываем Function 2
        response = requests.post(
            function_url,
            json=payload,
            timeout=25,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"Successfully got weather forecast for coordinates {lat}, {lon}")
            return result
        else:
            logger.error(f"Error calling forecast function: {response.status_code}")
            return {
                'error': 'Failed to get weather forecast',
                'status_code': response.status_code
            }
            
    except Exception as e:
        logger.error(f"Error calling weather forecast function: {str(e)}")
        return {
            'error': 'Failed to call weather forecast service',
            'details': str(e)
        }