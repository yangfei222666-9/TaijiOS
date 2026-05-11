$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$secretDir = Join-Path $repoRoot "data\secrets"
$secretPath = Join-Path $secretDir "deepseek_api_key.dpapi"

New-Item -ItemType Directory -Force -Path $secretDir | Out-Null

$secureKey = Read-Host "DeepSeek API Key" -AsSecureString
if ($secureKey.Length -eq 0) {
    throw "DeepSeek API Key is empty"
}

$encrypted = ConvertFrom-SecureString -SecureString $secureKey
Set-Content -Path $secretPath -Value $encrypted -Encoding ASCII -NoNewline

Write-Host "Saved DeepSeek API key with Windows DPAPI:"
Write-Host $secretPath
Write-Host "Only the same Windows user on this machine can decrypt it."
