# Pure ownership/port decisions are separate from startup side effects.
function Get-AideProcessKind($Process, [string]$Root) {
    $pythonPath = Join-Path $Root 'backend\.venv\python.exe'
    $mcpPath = Join-Path $Root 'backend\mcp-serve\mcp_server.py'
    $vitePath = Join-Path $Root 'ui\node_modules\vite\bin\vite.js'
    $command = [string]$Process.CommandLine
    if ($Process.ExecutablePath -ieq $pythonPath) {
        if ($command -match ('(?:^|[\s"])'+[regex]::Escape($mcpPath)+'(?=[\s"]|$)')) { return 'MCP' }
        if ($command -match '(?:^|\s)"?-m"?\s+"?uvicorn"?\s+"?main:app"?(?:\s|$)') { return 'API' }
    }
    if ([IO.Path]::GetFileName([string]$Process.ExecutablePath) -ieq 'node.exe' -and
        $command -match ('(?:^|[\s"])'+[regex]::Escape($vitePath)+'(?=[\s"]|$)')) { return 'UI' }
    return 'Other'
}

function Get-AideListeners([string]$Root) {
    $processes = @{}
    # Permission/query failure must not be interpreted as an empty port list.
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
    foreach ($connection in $listeners) {
        $ownerId = [int]$connection.OwningProcess
        if (-not $processes.ContainsKey($ownerId)) {
            $processes[$ownerId] = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction Stop
        }
        $owner = $processes[$ownerId]
        [pscustomobject]@{ Port=[int]$connection.LocalPort; ProcessId=$ownerId
            Kind=(Get-AideProcessKind $owner $Root); Name=$owner.Name }
    }
}

function Assert-AideFixedPort($Listeners, [int]$Port, [string]$Kind) {
    $foreign = @($Listeners | Where-Object { $_.Port -eq $Port -and $_.Kind -ne $Kind })
    if ($foreign.Count) {
        throw "Port $Port is occupied by another process (PID $($foreign[0].ProcessId), $($foreign[0].Name)). No process was stopped."
    }
}

function Select-AideFrontendPort($Listeners, [int]$PreferredPort=3000) {
    $existing = @($Listeners | Where-Object Kind -eq 'UI' | Select-Object -ExpandProperty Port -Unique)
    if ($existing.Count -gt 1) { throw 'Multiple Aide UI listeners exist; inspect them before starting another.' }
    if ($existing.Count -eq 1) { return [int]$existing[0] }
    foreach ($candidate in $PreferredPort..($PreferredPort+10)) {
        if (-not @($Listeners | Where-Object Port -eq $candidate).Count) { return $candidate }
    }
    throw 'No free frontend port in the requested range.'
}

function Test-AideTcp([string]$HostName, [int]$Port, [int]$TimeoutMs=3000) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $pending = $client.ConnectAsync($HostName, $Port)
        return ($pending.Wait($TimeoutMs) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}

function Wait-AideListener([string]$Root, [int]$Port, [string]$Kind, $StartedProcess, [int]$Seconds=90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if ($StartedProcess) {
            $StartedProcess.Refresh()
            if ($StartedProcess.HasExited) { throw "$Kind exited before listening; inspect logs. Exit code: $($StartedProcess.ExitCode)" }
        }
        if (Test-AideTcp '127.0.0.1' $Port 300) {
            $all = @(Get-AideListeners $Root)
            Assert-AideFixedPort $all $Port $Kind
            $match = @($all | Where-Object { $_.Port -eq $Port -and $_.Kind -eq $Kind })
            if ($match.Count) { return $match[0] }
        }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    throw "$Kind did not listen on port $Port within $Seconds seconds; inspect logs. Existing processes were preserved."
}
