@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "%SCRIPT_DIR%settings.json" (
    echo Missing settings.json. Create it with:
    echo   copy settings.example.json settings.json
    echo Then fill in the Plex and Discord credentials.
    exit /b 1
)

set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python.exe"
"%PYTHON_EXE%" -c "import discord, plexapi, watchdog" >nul 2>&1
if errorlevel 1 (
    echo Required Python packages are missing for: %PYTHON_EXE%
    echo Install them with:
    echo   "%PYTHON_EXE%" -m pip install -r requirements.txt
    exit /b 1
)

:: Always stop any existing bot and supervisor before starting one instance.
call "%SCRIPT_DIR%stop_plex_playlist_discord_bot.bat" >nul 2>&1
powershell -NoProfile -Command "Start-Sleep -Seconds 2" >nul 2>&1
if exist "%SCRIPT_DIR%plex_playlist_discord_bot.stop" del /q "%SCRIPT_DIR%plex_playlist_discord_bot.stop" >nul 2>&1
if exist "%SCRIPT_DIR%plex_playlist_discord_bot.pid" del /q "%SCRIPT_DIR%plex_playlist_discord_bot.pid" >nul 2>&1
if exist "%SCRIPT_DIR%plex_playlist_discord_bot.supervisor.pid" del /q "%SCRIPT_DIR%plex_playlist_discord_bot.supervisor.pid" >nul 2>&1

powershell -NoProfile -Command "$supervisor = Join-Path '%SCRIPT_DIR%' 'supervise_plex_playlist_discord_bot.ps1'; Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$supervisor) -WorkingDirectory '%SCRIPT_DIR%' -WindowStyle Hidden" >nul 2>&1
echo Plex playlist Discord bot supervisor started.
exit /b 0
