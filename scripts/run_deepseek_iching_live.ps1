param(
    [switch]$Fresh,
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$secretPath = Join-Path $repoRoot "data\secrets\deepseek_api_key.dpapi"
$latestPointer = Join-Path $repoRoot "runs\iching\latest_output_dir.txt"

$running = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
    Where-Object {
        $_.CommandLine -like "*examples\deepseek_iching_64.py*" -and
        $_.CommandLine -like "*--live*"
    }
if ($running) {
    $ids = ($running | Select-Object -ExpandProperty ProcessId) -join ", "
    throw "DeepSeek I Ching live run is already active. Existing python PID(s): $ids"
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function Get-RunSummary {
    param([Parameter(Mandatory = $true)][string]$RunDir)
    $summaryPath = Join-Path $RunDir "summary.json"
    if (-not (Test-Path $summaryPath)) {
        return $null
    }
    try {
        return Get-Content -Path $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Find-LatestLiveRun {
    $runsRoot = Join-Path $repoRoot "runs\iching"
    if (-not (Test-Path $runsRoot)) {
        return $null
    }
    foreach ($dir in Get-ChildItem -Path $runsRoot -Directory | Sort-Object LastWriteTime -Descending) {
        $summary = Get-RunSummary -RunDir $dir.FullName
        if (
            $summary -ne $null -and
            $summary.live -eq $true -and
            $summary.completed_count -eq 64 -and
            $summary.error_count -eq 0
        ) {
            return $dir.FullName
        }
    }
    return $null
}

function Find-ResumeRun {
    if ($OutputDir) {
        return $OutputDir
    }
    if (Test-Path $latestPointer) {
        $latest = (Get-Content -Path $latestPointer -Raw -Encoding UTF8).Trim()
        $summary = Get-RunSummary -RunDir $latest
        if ($summary -ne $null -and $summary.live -eq $true -and $summary.completed_count -lt 64) {
            return $latest
        }
    }
    return ""
}

if (-not $Fresh -and -not $OutputDir) {
    $existingLive = Find-LatestLiveRun
    if ($existingLive) {
        Write-Host "Found completed live DeepSeek I Ching run:"
        Write-Host $existingLive
        Invoke-NativeChecked -FilePath "python" -Arguments @("examples\validate_deepseek_iching_64.py", $existingLive)
        exit 0
    }
}

if (Test-Path $secretPath) {
    $encryptedBytes = [IO.File]::ReadAllBytes($secretPath)
    $encryptedKey = [Text.Encoding]::UTF8.GetString($encryptedBytes)
    $encryptedKey = $encryptedKey.Trim().Trim([char]0xFEFF)
    if ([string]::IsNullOrWhiteSpace($encryptedKey)) {
        throw "Stored DeepSeek API key is empty"
    }
    $secureKey = ConvertTo-SecureString -String $encryptedKey
    Write-Host "Loaded DeepSeek API key from Windows DPAPI store."
}
else {
    $secureKey = Read-Host "DeepSeek API Key" -AsSecureString
}

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "DEEPSEEK_API_KEY is empty"
    }
    $env:DEEPSEEK_API_KEY = $plainKey
    $runnerArgs = @("examples\deepseek_iching_64.py", "--live")
    $resumeRun = Find-ResumeRun
    if ($resumeRun) {
        $runnerArgs += @("--output-dir", $resumeRun)
    }
    if ($Fresh) {
        $runnerArgs += "--fresh"
    }
    Invoke-NativeChecked -FilePath "python" -Arguments $runnerArgs
    Invoke-NativeChecked -FilePath "python" -Arguments @("examples\validate_deepseek_iching_64.py")
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Item Env:\DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
}
