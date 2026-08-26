param(
  [Parameter(Mandatory = $true)]
  [string]$RunnerDirectory
)

$ErrorActionPreference = 'Stop'
$resolvedRunnerDirectory = (Resolve-Path -LiteralPath $RunnerDirectory).Path
$runnerCommand = Join-Path $resolvedRunnerDirectory 'run.cmd'
if (-not (Test-Path -LiteralPath $runnerCommand -PathType Leaf)) {
  throw "GitHub Actions runner was not found at $resolvedRunnerDirectory"
}

$pythonRegistryPath = 'Registry::HKEY_LOCAL_MACHINE\Software\Python\PythonCore\3.12\InstallPath'
if (Test-Path -LiteralPath $pythonRegistryPath) {
  $pythonExecutable = (Get-ItemProperty -LiteralPath $pythonRegistryPath).ExecutablePath
  $pythonDirectory = Split-Path -Parent $pythonExecutable
  $env:Path = "$pythonDirectory;$pythonDirectory\Scripts;$env:Path"
}

Set-Location -LiteralPath $resolvedRunnerDirectory
& $runnerCommand
exit $LASTEXITCODE
