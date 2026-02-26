# Create a Windows Startup shortcut for InterYubi.
# Run this script once to enable auto-start on login.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbsPath = Join-Path $scriptDir "interyubi_silent.vbs"

if (-not (Test-Path $vbsPath)) {
    Write-Error "interyubi_silent.vbs not found in $scriptDir"
    exit 1
}

$ws = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath('Startup')
$shortcut = $ws.CreateShortcut("$startup\InterYubi.lnk")
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = """$vbsPath"""
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = "InterYubi — auto-type TOTP codes from YubiKey"
$shortcut.Save()

Write-Host "Startup shortcut created at: $startup\InterYubi.lnk"
Write-Host "InterYubi will now start automatically when you log in."
