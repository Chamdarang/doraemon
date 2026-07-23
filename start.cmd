@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".pocket-runtime" mkdir ".pocket-runtime"
if exist ".pocket-runtime\ports.cmd" call "%~dp0stop.cmd" >nul

if not exist "back\.venv\Scripts\python.exe" (
  echo [Doraemon] Backend runtime not found: back\.venv\Scripts\python.exe
  echo Install the backend dependencies first.
  exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [Doraemon] npm.cmd was not found. Install Node.js first.
  exit /b 1
)

set API_PORT=8000
:find_api_port
netstat -ano | findstr /R /C:":!API_PORT! .*LISTENING" >nul
if !errorlevel! equ 0 (
  set /a API_PORT+=1
  goto find_api_port
)

set WEB_PORT=3000
:find_web_port
netstat -ano | findstr /R /C:":!WEB_PORT! .*LISTENING" >nul
if !errorlevel! equ 0 (
  set /a WEB_PORT+=1
  goto find_web_port
)

> "front\.env.local" echo NEXT_PUBLIC_POCKET_API_URL=http://localhost:!API_PORT!/api
del ".pocket-runtime\api.log" ".pocket-runtime\web.log" >nul 2>&1

start "Doraemon API" /min cmd.exe /d /c "cd /d ""%~dp0back"" ^&^& .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port !API_PORT! 1^>^> ""%~dp0.pocket-runtime\api.log"" 2^>^&1"
start "Doraemon Web" /min cmd.exe /d /c "cd /d ""%~dp0front"" ^&^& npm.cmd run dev -- --port !WEB_PORT! 1^>^> ""%~dp0.pocket-runtime\web.log"" 2^>^&1"

call :wait_listener !API_PORT! API_PID
if not defined API_PID goto api_failed
call :wait_listener !WEB_PORT! WEB_PID
if not defined WEB_PID goto web_failed

> ".pocket-runtime\ports.tmp" echo set API_PORT=!API_PORT!
>> ".pocket-runtime\ports.tmp" echo set WEB_PORT=!WEB_PORT!
>> ".pocket-runtime\ports.tmp" echo set API_PID=!API_PID!
>> ".pocket-runtime\ports.tmp" echo set WEB_PID=!WEB_PID!
move /y ".pocket-runtime\ports.tmp" ".pocket-runtime\ports.cmd" >nul

echo Doraemon started: http://localhost:!WEB_PORT!
echo API docs: http://localhost:!API_PORT!/docs
echo Run stop.cmd to stop both servers.
exit /b 0

:api_failed
echo [Doraemon] Backend failed to start on port !API_PORT!.
echo Check .pocket-runtime\api.log for details.
call :stop_owned "!WEB_PORT!" "!WEB_PID!"
del ".pocket-runtime\ports.tmp" >nul 2>&1
exit /b 1

:web_failed
echo [Doraemon] Frontend failed to start on port !WEB_PORT!.
echo Check .pocket-runtime\web.log for details.
call :stop_owned "!API_PORT!" "!API_PID!"
del ".pocket-runtime\ports.tmp" >nul 2>&1
exit /b 1

:wait_listener
set FOUND_PID=
for /l %%N in (1,1,20) do (
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do set FOUND_PID=%%P
  if defined FOUND_PID (
    set "%~2=!FOUND_PID!"
    exit /b 0
  )
  rem timeout.exe fails when the script is launched with redirected stdin.
  ping 127.0.0.1 -n 2 >nul
)
set "%~2="
exit /b 1

:stop_owned
if "%~1"=="" exit /b 0
if "%~2"=="" exit /b 0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
  if "%%P"=="%~2" taskkill /PID %%P /T /F >nul 2>&1
)
exit /b 0
