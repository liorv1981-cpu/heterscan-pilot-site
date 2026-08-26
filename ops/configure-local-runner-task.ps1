param(
  [Parameter(Mandatory = $true)]
  [string]$RunnerDirectory,

  [string]$TaskName = 'HETERSCAN Jerusalem Runner'
)

$ErrorActionPreference = 'Stop'
$resolvedRunnerDirectory = (Resolve-Path -LiteralPath $RunnerDirectory).Path
$startScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'start-local-runner.ps1')).Path
$account = "$env:USERDOMAIN\$env:USERNAME"

$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -RunnerDirectory "{1}"' -f $startScript, $resolvedRunnerDirectory
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $resolvedRunnerDirectory
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$recoveryTrigger = New-ScheduledTaskTrigger `
  -Once `
  -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -MultipleInstances IgnoreNew `
  -Hidden

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
  Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logonTrigger, $recoveryTrigger) -Settings $settings | Out-Null
} else {
  Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $recoveryTrigger) `
    -Settings $settings `
    -User $account | Out-Null
}

Start-ScheduledTask -TaskName $TaskName
$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
[pscustomobject]@{
  TaskName = $TaskName
  State = $task.State
  LastRunTime = $info.LastRunTime
  NextRunTime = $info.NextRunTime
  ExecutionTimeLimit = $task.Settings.ExecutionTimeLimit
}
