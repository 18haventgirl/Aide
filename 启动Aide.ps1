param(
  [switch]$AllowOffline,
  [switch]$Status,
  [ValidateRange(1024,65525)][int]$FrontendPort=3000,
  [ValidateRange(1024,65535)][int]$BackendPort=8000,
  [ValidateRange(1024,65535)][int]$McpPort=8002,
  [switch]$RestartFrontend,
  [string]$NodePath
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'scripts\aide-runtime.ps1')
$backend = Join-Path $root 'backend'
$python = Join-Path $backend '.venv\python.exe'
$vite = Join-Path $root 'ui\node_modules\vite\bin\vite.js'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

function Start-AideHidden($file, $argList, $cwd, $name) {
  $logDir = Join-Path $root 'logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
  # Start-Process joins ArgumentList; explicitly quote paths containing spaces.
  $quoted = @($argList | ForEach-Object {
    if ($_ -match '"') { throw 'Unexpected quote in process argument.' }
    '"' + $_ + '"'
  })
  Start-Process -FilePath $file -ArgumentList $quoted -WorkingDirectory $cwd -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logDir "$name-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logDir "$name-$stamp.err.log")
}

function Test-AideModelPort {
  $line = Get-Content (Join-Path $backend '.env') -ErrorAction SilentlyContinue |
    Where-Object { $_ -match '^OPENAI_API_BASE_URL=' } | Select-Object -Last 1
  $baseUrl = if ($line) { ($line -split '=',2)[1].Trim().Trim('"',"'") } else { 'https://api.openai.com/v1' }
  $uri = $null
  if (-not [Uri]::TryCreate($baseUrl,[UriKind]::Absolute,[ref]$uri) -or $uri.Scheme -notin 'http','https') {
    throw 'Invalid OPENAI_API_BASE_URL in backend/.env'
  }
  Test-AideTcp $uri.Host $uri.Port
}

function Resolve-AideNode([string]$RequestedPath) {
  $resolved = $RequestedPath
  if (-not $resolved) { $resolved = $env:AIDE_NODE_EXE }
  if (-not $resolved) {
    $command = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($command) { $resolved = $command.Source }
  }
  if (-not $resolved) { $resolved = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' }
  if (-not (Test-Path -LiteralPath $resolved)) { throw 'Node not found; install Node or pass -NodePath.' }
  return $resolved
}

# Serialize launchers for this checkout; never stop another application.
$hasher = [Security.Cryptography.SHA256]::Create()
try { $identity = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))).Replace('-','') }
finally { $hasher.Dispose() }
$mutex = New-Object Threading.Mutex($false, "Local\AideLauncher-$identity")
$locked = $false
$previousExternalMcp = $env:AIDE_EXTERNAL_MCP
$previousMcpUrl = $env:AIDE_MCP_SERVER_URL
$previousMcpPort = $env:AIDE_MCP_PORT
$previousApiBase = $env:AIDE_API_BASE_URL
try {
  try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
  if (-not $locked) { throw 'Another launcher for this Aide checkout is running.' }
  $listeners = @(Get-AideListeners $root)
  if ($Status) {
    $listeners | Where-Object Kind -ne 'Other' | Sort-Object Kind,Port -Unique | Format-Table Kind,Port,ProcessId
    return
  }
  $BackendPort = Select-AideServicePort $listeners 'API' $BackendPort ($PSBoundParameters.ContainsKey('BackendPort'))
  $McpPort = Select-AideServicePort $listeners 'MCP' $McpPort ($PSBoundParameters.ContainsKey('McpPort'))
  Assert-AidePortConfiguration $BackendPort $McpPort
  Assert-AideFixedPort $listeners $McpPort 'MCP'
  Assert-AideFixedPort $listeners $BackendPort 'API'
  foreach ($kind in @('API','MCP')) {
    $expectedPort = if ($kind -eq 'API') { $BackendPort } else { $McpPort }
    if (@($listeners | Where-Object { $_.Kind -eq $kind -and $_.Port -ne $expectedPort }).Count) {
      throw "This checkout already has $kind on another port. Inspect its ownership before changing configuration."
    }
  }
  $existingUi = @($listeners | Where-Object Kind -eq 'UI')
  # Preflight before stopping a working frontend or starting any new process.
  if (-not (Test-Path -LiteralPath $python)) { throw "Backend Python not found: $python" }
  if (-not (Test-Path -LiteralPath $vite)) { throw 'Frontend dependencies missing; run npm ci in ui.' }
  if (-not $existingUi.Count -or $RestartFrontend) { $NodePath = Resolve-AideNode $NodePath }
  $existingApi = @($listeners | Where-Object { $_.Port -eq $BackendPort -and $_.Kind -eq 'API' })
  if (-not $existingApi.Count -and -not $AllowOffline -and -not (Test-AideModelPort)) {
    throw 'Model TCP endpoint unreachable. No service started. Check network/proxy or use -AllowOffline for local functions. This does not test API credentials.'
  }
  if ($RestartFrontend) {
    foreach ($uiPid in @($existingUi | Select-Object -ExpandProperty ProcessId -Unique)) {
      $uiOwner = Get-CimInstance Win32_Process -Filter "ProcessId=$uiPid" -ErrorAction Stop
      if ((Get-AideProcessKind $uiOwner $root) -ne 'UI') { throw 'Frontend ownership changed.' }
      Stop-Process -Id $uiPid -ErrorAction Stop
    }
    $listeners = @(Get-AideListeners $root)
    $existingUi = @($listeners | Where-Object Kind -eq 'UI')
  }
  if ($existingUi.Count) {
    $savedRuntime = $null
    $runtimePath = Join-Path $root 'logs\aide-runtime.json'
    if (Test-Path -LiteralPath $runtimePath) { $savedRuntime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json }
    $savedApiPort = if ($savedRuntime -and $savedRuntime.api_port) { [int]$savedRuntime.api_port } else { 8000 }
    if ($savedApiPort -ne $BackendPort) { throw 'Frontend proxy target changed; run with -RestartFrontend to apply it.' }
  }
  $uiPort = Select-AideFrontendPort $listeners $FrontendPort @($BackendPort,$McpPort)
  $startedMcp = $null
  $env:AIDE_MCP_PORT = "$McpPort"
  $env:AIDE_MCP_SERVER_URL = "http://127.0.0.1:$McpPort/mcp"
  $env:AIDE_API_BASE_URL = "http://127.0.0.1:$BackendPort"
  if (-not @($listeners | Where-Object { $_.Port -eq $McpPort -and $_.Kind -eq 'MCP' }).Count) {
    $startedMcp = Start-AideHidden $python @((Join-Path $backend 'mcp-serve\mcp_server.py')) $backend 'mcp'
  }
  $mcp = Wait-AideListener $root $McpPort 'MCP' $startedMcp
  $startedApi = $null
  $env:AIDE_EXTERNAL_MCP = 'true'
  if (-not $existingApi.Count) {
    $startedApi = Start-AideHidden $python @('-m','uvicorn','main:app','--host','127.0.0.1','--port',"$BackendPort",'--no-access-log','--log-level','info') $backend 'backend'
  }
  $api = Wait-AideListener $root $BackendPort 'API' $startedApi
  $health = Invoke-RestMethod "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 10
  if ($health.status -ne 'healthy') { throw 'API is listening but its database health is not ready; inspect backend logs.' }
  $startedUi = $null
  if (-not $existingUi.Count) {
    $startedUi = Start-AideHidden $NodePath @($vite,'--host','127.0.0.1','--port',"$uiPort",'--strictPort') (Join-Path $root 'ui') 'frontend'
  }
  $ui = Wait-AideListener $root $uiPort 'UI' $startedUi 30
  $runtime = [pscustomobject]@{checked_at=(Get-Date).ToString('o');frontend_url="http://127.0.0.1:$uiPort/";api_port=$BackendPort;mcp_port=$McpPort;services=@($mcp,$api,$ui);api_health=$health.status}
  New-Item -ItemType Directory -Force -Path (Join-Path $root 'logs') | Out-Null
  $runtime | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $root 'logs\aide-runtime.json') -Encoding UTF8
  Write-Output "Aide UI: http://127.0.0.1:$uiPort/"
  @($mcp,$api,$ui) | Format-Table Kind,Port,ProcessId
  Write-Output 'Services verified/reused. API database health passed; model authentication/generation was not tested.'
} finally {
  $env:AIDE_EXTERNAL_MCP = $previousExternalMcp
  $env:AIDE_MCP_SERVER_URL = $previousMcpUrl
  $env:AIDE_MCP_PORT = $previousMcpPort
  $env:AIDE_API_BASE_URL = $previousApiBase
  if ($locked) { $mutex.ReleaseMutex() }
  $mutex.Dispose()
}
