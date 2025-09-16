#!/bin/bash

echo "🏗️ Building Cloud Functions for Weather Forecast Service..."
echo

# Создаем структуру папок
mkdir -p static
mkdir -p temp/weather_context
mkdir -p temp/weather_forecast

echo "📄 Creating static files..."

# ============================================================================
# Создание HTML страницы (если файл не существует)
# ============================================================================
if [ ! -f "static/index.html" ]; then
    echo "Creating static/index.html..."
    touch static/index.html
else
    echo "static/index.html already exists, skipping creation..."
fi

echo "✓ Static files ready"

# ============================================================================
# Function 1: Weather Context
# ============================================================================
echo "🔧 Building weather-context function..."

# Проверяем наличие исходного кода Function 1
if [ ! -f "function1_weather_context.py" ]; then
    echo "❌ Error: function1_weather_context.py not found!"
    echo "Please make sure the file exists in the current directory."
    exit 1
fi

# Копируем исходный код Function 1
cp function1_weather_context.py temp/weather_context/index.py

# Создаем requirements.txt для Function 1
cat > temp/weather_context/requirements.txt << EOF
psycopg2-binary==2.9.7
requests==2.31.0
EOF

# Создаем ZIP архив для Function 1
cd temp/weather_context
rm -f ../../weather_context.zip
zip -r ../../weather_context.zip .
if [ $? -ne 0 ]; then
    echo "❌ Error creating weather_context.zip"
    cd ../..
    exit 1
fi

cd ../..
echo "✓ weather_context.zip created"

# ============================================================================
# Function 2: Weather Forecast
# ============================================================================
echo "🌤️ Building weather-forecast function..."

# Проверяем наличие исходного кода Function 2
if [ ! -f "function2_weather_forecast.py" ]; then
    echo "❌ Error: function2_weather_forecast.py not found!"
    echo "Please make sure the file exists in the current directory."
    exit 1
fi

# Копируем исходный код Function 2
cp function2_weather_forecast.py temp/weather_forecast/index.py

# Создаем requirements.txt для Function 2
cat > temp/weather_forecast/requirements.txt << EOF
requests==2.31.0
EOF

# Создаем ZIP архив для Function 2
cd temp/weather_forecast
rm -f ../../weather_forecast.zip
zip -r ../../weather_forecast.zip .
if [ $? -ne 0 ]; then
    echo "❌ Error creating weather_forecast.zip"
    cd ../..
    exit 1
fi

cd ../..
echo "✓ weather_forecast.zip created"

# ============================================================================
# Очистка временных файлов
# ============================================================================
echo "🧹 Cleaning up temporary files..."
rm -rf temp/

echo
echo "🎉 All components built successfully!"
echo
echo "📦 Files created:"
echo "  - static/index.html - Simple HTML page with auto geolocation"
echo "  - weather_context.zip - Function 1 (Context & DB)"
echo "  - weather_forecast.zip - Function 2 (Weather API)"
echo
echo "🚀 Next steps:"
echo "  1. terraform init"
echo "  2. terraform plan"
echo "  3. terraform apply"
echo
echo "🌐 After deployment, access your app at:"
echo "  https://YOUR-API-GATEWAY-ID.apigw.yandexcloud.net"
echo
echo "⚠️ Required files:"
echo "  - function1_weather_context.py"
echo "  - function2_weather_forecast.py"
echo "  - static/index.html (will be created if missing)"
echo