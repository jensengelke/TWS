# weekly-earnings-script.ps1
# Initialize Python virtual environment located at .venv relative to this script.

git stash save
git pull 
Set-StrictMode -Version Latest

# Resolve script directory (works when script is dot-sourced or executed)
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }

$activatePath = Join-Path $ScriptDir ".venv\Scripts\Activate.ps1"

if (-not (Test-Path $activatePath)) {
    Write-Error "Virtual environment activation script not found: $activatePath"
    exit 1
}

# If already active, report and skip
if ($env:VIRTUAL_ENV) {
    Write-Output "Virtual environment already active: $env:VIRTUAL_ENV"
} else {
    Write-Output "Activating virtual environment: $activatePath"
    # Dot-source to ensure the activation affects the current session scope
    . $activatePath

    if (-not $env:VIRTUAL_ENV) {
        Write-Error "Activation failed or did not set VIRTUAL_ENV."
        exit 1
    }
}

# (Optional) show python version to confirm
python --version 2>$null
python .\evaluate-options-trade.py --earnings-week current
git add docs
git commit -m "new earnings option prices"
git push
git stash pop