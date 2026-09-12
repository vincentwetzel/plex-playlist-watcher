$ErrorActionPreference = 'Continue'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $scriptDir 'plex_playlist_watcher.py'
$stopPath = Join-Path $scriptDir 'plex_playlist_discord_bot.stop'
$supervisorPidPath = Join-Path $scriptDir 'plex_playlist_discord_bot.supervisor.pid'
$botPidPath = Join-Path $scriptDir 'plex_playlist_discord_bot.pid'

$python = Join-Path $scriptDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python.exe'
}

Set-Content -LiteralPath $supervisorPidPath -Value $PID -Encoding ASCII

try {
    while (-not (Test-Path -LiteralPath $stopPath)) {
        $bot = Start-Process -FilePath $python `
            -ArgumentList @('-u', $scriptPath) `
            -WorkingDirectory $scriptDir `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -LiteralPath $botPidPath -Value $bot.Id -Encoding ASCII
        $bot.WaitForExit()
        Remove-Item -LiteralPath $botPidPath -Force -ErrorAction SilentlyContinue

        if (Test-Path -LiteralPath $stopPath) {
            break
        }

        # Restart after an unexpected crash or lost connection.
        Start-Sleep -Seconds 5
    }
}
finally {
    Remove-Item -LiteralPath $botPidPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $supervisorPidPath -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $stopPath) {
    Remove-Item -LiteralPath $stopPath -Force -ErrorAction SilentlyContinue
}
