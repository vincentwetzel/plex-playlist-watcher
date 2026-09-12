@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Tell the supervisor not to restart the bot after it exits.
> "%SCRIPT_DIR%plex_playlist_discord_bot.stop" echo stop

:: Stop the exact bot and supervisor PIDs recorded by the supervisor.
powershell -NoProfile -Command "$pidFiles = @('%SCRIPT_DIR%plex_playlist_discord_bot.pid','%SCRIPT_DIR%plex_playlist_discord_bot.supervisor.pid'); foreach ($pidFile in $pidFiles) { if (Test-Path -LiteralPath $pidFile) { $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim(); $targetPid = 0; if ([int]::TryParse($rawPid, [ref]$targetPid) -and $targetPid -gt 0) { Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue }; Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue } }" >nul 2>&1

:: Fallback for instances started before PID tracking was added.
powershell -NoProfile -Command "try { $bots = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { ($_.Name -in @('python.exe','pythonw.exe')) -and $_.CommandLine -like '*plex_playlist_watcher.py*' }); $bots | Invoke-CimMethod -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null } catch {}" >nul 2>&1

:: Stop the hidden supervisor too.
powershell -NoProfile -Command "try { $supervisors = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.CommandLine -like '*supervise_plex_playlist_discord_bot.ps1*' }); $supervisors | Invoke-CimMethod -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null } catch {}" >nul 2>&1
exit /b 0
