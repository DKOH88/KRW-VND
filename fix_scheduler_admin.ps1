param(
    [string]$TaskName = "",
    [string]$UserId = "$env:USERDOMAIN\$env:USERNAME",
    [string]$PythonPath = "C:\Users\odk29\AppData\Local\Programs\Python\Python311\python.exe",
    [string]$ScriptPath = "C:\Vibe Coding\KRW-VND\exchange_rate_collector.py",
    [switch]$InteractiveOnly
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonPath)) {
    throw "Python not found: $PythonPath"
}
if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

if ([string]::IsNullOrWhiteSpace($TaskName)) {
    $taskMatch = @(foreach ($t in Get-ScheduledTask) {
        foreach ($a in $t.Actions) {
            $exec = ([string]$a.Execute).Trim('"')
            $args = ([string]$a.Arguments).Trim('"')
            if ($exec -ieq $ScriptPath) {
                $t
                break
            }
            if ($exec -match "python" -and $args -match [regex]::Escape($ScriptPath)) {
                $t
                break
            }
        }
    }) | Select-Object -First 1

    if (-not $taskMatch) {
        throw "TaskName not provided and no task pointing to $ScriptPath was found."
    }
    $TaskName = $taskMatch.TaskName
}

$workDir = Split-Path $ScriptPath -Parent
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 72) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 1)

if ($InteractiveOnly) {
    $principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
} else {
    $principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType S4U -RunLevel Limited
}

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
}
catch {
    if (-not $InteractiveOnly) {
        Write-Warning "S4U registration failed. Falling back to Interactive logon type."
        $principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    }
    else {
        throw
    }
}

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName

[pscustomobject]@{
    TaskName                     = $TaskName
    NextRunTime                  = $info.NextRunTime
    LastRunTime                  = $info.LastRunTime
    LastTaskResult               = $info.LastTaskResult
    Execute                      = $task.Actions.Execute
    Arguments                    = $task.Actions.Arguments
    WorkingDirectory             = $task.Actions.WorkingDirectory
    StartBoundary                = $task.Triggers.StartBoundary
    RandomDelay                  = $task.Triggers.RandomDelay
    LogonType                    = $task.Principal.LogonType
    DisallowStartIfOnBatteries   = $task.Settings.DisallowStartIfOnBatteries
    StopIfGoingOnBatteries       = $task.Settings.StopIfGoingOnBatteries
    StartWhenAvailable           = $task.Settings.StartWhenAvailable
} | Format-List
