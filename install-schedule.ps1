# Регистрация задачи в планировщике Windows: обновление доменов раз в 2 дня.
# Запускать из папки со скриптом. Права администратора не нужны.

$ErrorActionPreference = "Stop"
$dir    = $PSScriptRoot
$python = (Get-Command python).Source
$script = Join-Path $dir "update-all.py"

if (-not (Test-Path $script)) { throw "не найден $script" }

$action  = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval 2 -At 05:00
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RandomDelay (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "RU routing domains update" `
    -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Задача зарегистрирована. Проверить:  Get-ScheduledTask 'RU routing domains update'"
Write-Host "Запустить сейчас:  Start-ScheduledTask 'RU routing domains update'"
