@echo off
setlocal
cd /d "%~dp0"
set API_PORT=
set WEB_PORT=
set API_PID=
set WEB_PID=

if not exist ".pocket-runtime\ports.cmd" goto done
call ".pocket-runtime\ports.cmd"
call :stop_owned "%API_PORT%" "%API_PID%"
call :stop_owned "%WEB_PORT%" "%WEB_PID%"
del ".pocket-runtime\ports.cmd" >nul 2>&1

:done
echo Doraemon stopped.
exit /b 0

:stop_owned
if "%~1"=="" exit /b 0
if "%~2"=="" exit /b 0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
  if "%%P"=="%~2" taskkill /PID %%P /T /F >nul 2>&1
)
exit /b 0
