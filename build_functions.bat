@echo off
setlocal

echo === Packing functions (no deps) ===

set F1=function1_weather_context.py
set F2=function2_weather_forecast.py

if not exist "%F1%" (
  echo [ERROR] Missing %F1%
  exit /b 1
)
if not exist "%F2%" (
  echo [ERROR] Missing %F2%"
  exit /b 1
)

del /f /q weather_context.zip 2>nul
del /f /q weather_forecast.zip 2>nul

echo [INFO] Using PowerShell .NET Zip fallback
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; " ^
  "$tmp=New-Item -ItemType Directory -Path ([IO.Path]::GetTempPath()) -Name ([IO.Path]::GetRandomFileName()); " ^
  "Copy-Item '%F1%' -Destination $tmp; " ^
  "$out=Join-Path (Get-Location) 'weather_context.zip'; if (Test-Path $out){Remove-Item $out -Force}; " ^
  "[IO.Compression.ZipFile]::CreateFromDirectory($tmp.FullName, $out); " ^
  "Remove-Item $tmp -Recurse -Force;"
if errorlevel 1 goto :zip_ps1_fail

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; " ^
  "$tmp=New-Item -ItemType Directory -Path ([IO.Path]::GetTempPath()) -Name ([IO.Path]::GetRandomFileName()); " ^
  "Copy-Item '%F2%' -Destination $tmp; " ^
  "$out=Join-Path (Get-Location) 'weather_forecast.zip'; if (Test-Path $out){Remove-Item $out -Force}; " ^
  "[IO.Compression.ZipFile]::CreateFromDirectory($tmp.FullName, $out); " ^
  "Remove-Item $tmp -Recurse -Force;"
if errorlevel 1 goto :zip_ps1_fail

goto :done

:zip_fail
echo [ERROR] tar failed to create zip
exit /b 1

:zip_ps1_fail
echo [ERROR] PowerShell .NET zip fallback failed.
echo Try manual:
echo   tar -a -c -f weather_context.zip %F1%
echo   tar -a -c -f weather_forecast.zip %F2%
exit /b 1

:done
echo Done. Created: weather_context.zip, weather_forecast.zip
endlocal
