@echo off
echo 🏗️ Building Cloud Functions for Weather Forecast Service...
echo.

REM Создаем структуру папок
if not exist "static" mkdir static
if not exist "temp" mkdir temp
if not exist "temp\weather_context" mkdir temp\weather_context
if not exist "temp\weather_forecast" mkdir temp\weather_forecast

echo 📄 Creating static files...

REM ============================================================================
REM Создание HTML страницы (если файл не существует)
REM ============================================================================
if not exist "static\index.html" (
    echo Creating static\index.html...
    echo. > static\index.html
) else (
    echo static\index.html already exists, skipping creation...
)

echo ✓ Static files ready

REM ============================================================================
REM Function 1: Weather Context
REM ============================================================================
echo 🔧 Building weather-context function...

REM Копируем исходный код Function 1
copy function1_weather_context.py temp\weather_context\index.py > nul
if errorlevel 1 (
    echo ❌ Error: function1_weather_context.py not found!
    echo Please make sure the file exists in the current directory.
    pause
    exit /b 1
)

REM Создаем requirements.txt для Function 1
echo psycopg2-binary==2.9.7 > temp\weather_context\requirements.txt
echo requests==2.31.0 >> temp\weather_context\requirements.txt

REM Создаем ZIP архив для Function 1
cd temp\weather_context
if exist "..\..\weather_context.zip" del "..\..\weather_context.zip"

REM Используем PowerShell для создания ZIP архива
powershell -command "Compress-Archive -Path '.\*' -DestinationPath '..\..\weather_context.zip' -Force"
if errorlevel 1 (
    echo ❌ Error creating weather_context.zip
    cd ..\..
    pause
    exit /b 1
)

cd ..\..
echo ✓ weather_context.zip created

REM ============================================================================
REM Function 2: Weather Forecast
REM ============================================================================
echo 🌤️ Building weather-forecast function...

REM Копируем исходный код Function 2
copy function2_weather_forecast.py temp\weather_forecast\index.py > nul
if errorlevel 1 (
    echo ❌ Error: function2_weather_forecast.py not found!
    echo Please make sure the file exists in the current directory.
    pause
    exit /b 1
)

REM Создаем requirements.txt для Function 2
echo requests==2.31.0 > temp\weather_forecast\requirements.txt

REM Создаем ZIP архив для Function 2
cd temp\weather_forecast
if exist "..\..\weather_forecast.zip" del "..\..\weather_forecast.zip"

REM Используем PowerShell для создания ZIP архива
powershell -command "Compress-Archive -Path '.\*' -DestinationPath '..\..\weather_forecast.zip' -Force"
if errorlevel 1 (
    echo ❌ Error creating weather_forecast.zip
    cd ..\..
    pause
    exit /b 1
)

cd ..\..
echo ✓ weather_forecast.zip created

REM ============================================================================
REM Очистка временных файлов
REM ============================================================================
echo 🧹 Cleaning up temporary files...
rmdir /s /q temp

echo.
echo 🎉 All components built successfully!
echo.
echo 📦 Files created:
echo   - static\index.html - Simple HTML page with auto geolocation
echo   - weather_context.zip - Function 1 (Context ^& DB)
echo   - weather_forecast.zip - Function 2 (Weather API)
echo.
echo 🚀 Next steps:
echo   1. terraform init
echo   2. terraform plan
echo   3. terraform apply
echo.
echo 🌐 After deployment, access your app at:
echo   https://YOUR-API-GATEWAY-ID.apigw.yandexcloud.net
echo.
echo ⚠️ Required files:
echo   - function1_weather_context.py
echo   - function2_weather_forecast.py
echo   - static\index.html (will be created if missing)
echo.
pause