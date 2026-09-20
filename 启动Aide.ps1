$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\python.exe'
$node = 'C:\Users\HONOR\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$vite = Join-Path $root 'ui\node_modules\vite\bin\vite.js'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

if (-not (Test-Path $python)) { throw "Backend Python not found: $python" }
if (-not (Test-Path $node)) { throw "Node runtime not found: $node" }

function Start-Hidden($file, $argList, $cwd, $name) {
  $logDir = Join-Path $root 'logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $cwd -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir ($name + '.out.log')) `
    -RedirectStandardError (Join-Path $logDir ($name + '.err.log'))
}

function Port-IsOpen($port) {
  try { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue) } catch { return $false }
}

# Start each service without opening a console window. Existing services keep
# their ports; this avoids killing unrelated Node/Python processes.
if (-not (Port-IsOpen 8000)) { Start-Hidden $python @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000','--no-access-log','--log-level','info') $backend 'backend' }
if (-not (Port-IsOpen 8002)) { Start-Hidden $python @((Join-Path $backend 'mcp-serve\mcp_server.py')) $backend 'mcp' }
if (-not (Port-IsOpen 3000)) { Start-Hidden $node @($vite,'--host','127.0.0.1','--port','3000') (Join-Path $root 'ui') 'frontend' }
Write-Output 'Aide services started in hidden windows.'
