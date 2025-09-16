@echo off
echo Building Cloud Functions for Weather Forecast Service...
echo.

REM Create directory structure
if not exist "static" mkdir static
if not exist "temp" mkdir temp
if not exist "temp\weather_context" mkdir temp\weather_context
if not exist "temp\weather_forecast" mkdir temp\weather_forecast

echo Creating static files...

REM ============================================================================
REM Create HTML page (if file doesn't exist)
REM ============================================================================
if not exist "static\index.html" (
    echo Creating static\index.html...
    echo. > static\index.html
) else (
    echo static\index.html already exists, skipping creation...
)

echo Static files ready

REM ============================================================================
REM Function 1: Weather Context
REM ============================================================================
echo Building weather-context function...

REM Copy Function 1 source code
copy function1_weather_context.py temp\weather_context\index.py > nul
if errorlevel 1 (
    echo Error: function1_weather_context.py not found!
    echo Please make sure the file exists in the current directory.
    pause
    exit /b 1
)

REM Create requirements.txt for Function 1
echo psycopg2-binary==2.9.7 > temp\weather_context\requirements.txt
echo requests==2.31.0 >> temp\weather_context\requirements.txt

REM Create ZIP archive for Function 1
cd temp\weather_context
if exist "..\..\weather_context.zip" del "..\..\weather_context.zip"

REM Try PowerShell first (newer Windows versions)
powershell -command "& {try {Compress-Archive -Path '.\*' -DestinationPath '..\..\weather_context.zip' -Force; exit 0} catch {exit 1}}" 2>nul
if errorlevel 1 (
    echo PowerShell Compress-Archive not working, using alternative method...
    REM Use tar (built into Windows 10/11)
    tar -a -c -f ..\..\weather_context.zip index.py requirements.txt 2>nul
    if errorlevel 1 (
        echo Error: Could not create ZIP archive. Install 7-Zip or use another archiver.
        echo Create weather_context.zip manually from temp\weather_context\ folder
        pause
        cd ..\..
        exit /b 1
    )
)

cd ..\..
echo weather_context.zip created

REM ============================================================================
REM Function 2: Weather Forecast
REM ============================================================================
echo Building weather-forecast function...

REM Copy Function 2 source code
copy function2_weather_forecast.py temp\weather_forecast\index.py > nul
if errorlevel 1 (
    echo Error: function2_weather_forecast.py not found!
    echo Please make sure the file exists in the current directory.
    pause
    exit /b 1
)

REM Create requirements.txt for Function 2
echo requests==2.31.0 > temp\weather_forecast\requirements.txt

REM Create ZIP archive for Function 2
cd temp\weather_forecast
if exist "..\..\weather_forecast.zip" del "..\..\weather_forecast.zip"

REM Try PowerShell first
powershell -command "& {try {Compress-Archive -Path '.\*' -DestinationPath '..\..\weather_forecast.zip' -Force; exit 0} catch {exit 1}}" 2>nul
if errorlevel 1 (
    echo PowerShell Compress-Archive not working, using alternative method...
    REM Use tar (built into Windows 10/11)
    tar -a -c -f ..\..\weather_forecast.zip index.py requirements.txt 2>nul
    if errorlevel 1 (
        echo Error: Could not create ZIP archive. Install 7-Zip or use another archiver.
        echo Create weather_forecast.zip manually from temp\weather_forecast\ folder
        pause
        cd ..\..
        exit /b 1
    )
)

cd ..\..
echo weather_forecast.zip created

REM ============================================================================
REM Clean up temporary files
REM ============================================================================
echo Cleaning up temporary files...
if exist create_zip.vbs del create_zip.vbs
rmdir /s /q temp

echo.
echo All components built successfully!
echo.
echo Files created:
echo   - static\index.html - Simple HTML page with auto geolocation
echo   - weather_context.zip - Function 1 (Context and DB)
echo   - weather_forecast.zip - Function 2 (Weather API)
echo.
echo Next steps:
echo   1. terraform init
echo   2. terraform plan
echo   3. terraform apply
echo.
echo After deployment, access your app at:
echo   https://YOUR-API-GATEWAY-ID.apigw.yandexcloud.net
echo.
echo Required files:
echo   - function1_weather_context.py
echo   - function2_weather_forecast.py
echo   - static\index.html (will be created if missing)
echo.
echo If ZIP files were not created, use 7-Zip or WinRAR:
echo   - Archive contents of temp\weather_context\ to weather_context.zip
echo   - Archive contents of temp\weather_forecast\ to weather_forecast.zip
echo.
pause