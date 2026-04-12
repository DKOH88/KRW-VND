# 환율 알림이 스케줄러 경로 업데이트 (2026-04-12 폴더 이동 후)
# 관리자 PowerShell에서 실행: 마우스 오른쪽 클릭 > PowerShell로 실행
# 또는 관리자 PowerShell 열고: cd "C:\Vibe Coding\services\KRW-VND"; .\update_scheduler_path.ps1

$ErrorActionPreference = "Stop"

# 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Write-Host "[ERROR] 관리자 권한 필요. PowerShell을 '관리자 권한으로 실행' 하세요." -ForegroundColor Red
    Write-Host "계속하려면 Enter를 누르세요..."
    Read-Host
    exit 1
}

Write-Host "=== 변경 전 Action 상태 ===" -ForegroundColor Cyan
(Get-ScheduledTask -TaskName "환율 알림이").Actions | Format-List Execute, Arguments, WorkingDirectory

Write-Host ""
Write-Host "=== Action 업데이트 중 ===" -ForegroundColor Cyan
$action = New-ScheduledTaskAction `
    -Execute 'C:\Users\odk29\AppData\Local\Programs\Python\Python311\python.exe' `
    -Argument '"C:\Vibe Coding\services\KRW-VND\exchange_rate_collector.py"' `
    -WorkingDirectory 'C:\Vibe Coding\services\KRW-VND'

Set-ScheduledTask -TaskName "환율 알림이" -Action $action | Out-Null

Write-Host ""
Write-Host "=== 변경 후 Action 상태 ===" -ForegroundColor Green
(Get-ScheduledTask -TaskName "환율 알림이").Actions | Format-List Execute, Arguments, WorkingDirectory

Write-Host ""
Write-Host "=== 태스크 정보 ===" -ForegroundColor Cyan
Get-ScheduledTaskInfo -TaskName "환율 알림이" | Format-List TaskName, LastRunTime, LastTaskResult, NextRunTime

Write-Host ""
Write-Host "[OK] 완료. 수동 테스트 실행하려면:" -ForegroundColor Green
Write-Host "    Start-ScheduledTask -TaskName '환율 알림이'" -ForegroundColor Yellow
Write-Host ""
Write-Host "아무 키나 누르면 창 닫힘..."
Read-Host
