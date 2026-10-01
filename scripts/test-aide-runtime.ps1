$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'aide-runtime.ps1')
$testRoot = 'D:\Example Workspace\Aide'
function Assert-Equal($actual,$expected) { if ($actual -ne $expected) { throw "Expected $expected, got $actual" } }
function Assert-Throws([scriptblock]$action) { $failed=$false; try { & $action } catch { $failed=$true }; if (-not $failed) { throw 'Expected failure' } }
$other = [pscustomobject]@{Port=3000;Kind='Other';ProcessId=1;Name='other.exe'}
$other2 = [pscustomobject]@{Port=3001;Kind='Other';ProcessId=2;Name='other.exe'}
$own = [pscustomobject]@{Port=3002;Kind='UI';ProcessId=3;Name='node.exe'}
Assert-Equal (Select-AideFrontendPort @($other,$other2)) 3002
Assert-Equal (Select-AideFrontendPort @($own)) 3002
Assert-Equal (Select-AideFrontendPort @()) 3000
$conflict = [pscustomobject]@{Port=8000;Kind='Other';ProcessId=4;Name='other.exe'}
Assert-Throws { Assert-AideFixedPort @($conflict) 8000 'API' }
Assert-Throws { Select-AideFrontendPort @($own,([pscustomobject]@{Port=3004;Kind='UI'})) }
$proc = [pscustomobject]@{ExecutablePath="$testRoot\backend\.venv\python.exe";CommandLine='python -m uvicorn main:app --port 8000'}
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'API'
$proc.CommandLine='python "-m" "uvicorn" "main:app" "--port" "8000"'
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'API'
$proc.ExecutablePath='D:\Other\python.exe'
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'Other'
$proc.ExecutablePath="$testRoot\backend\.venv\python.exe"
$proc.CommandLine='python "'+$testRoot+'\backend\mcp-serve\mcp_server.py"'
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'MCP'
$proc.CommandLine='python "'+$testRoot+'\backend\mcp-serve\mcp_server.py.backup"'
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'Other'
$proc.ExecutablePath='C:\Tools\node.exe'
$proc.CommandLine='node "'+$testRoot+'\ui\node_modules\vite\bin\vite.js" --port 3002'
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'UI'
$proc.CommandLine='node D:\Other\ui\node_modules\vite\bin\vite.js'
Assert-Equal (Get-AideProcessKind $proc $testRoot) 'Other'
Write-Output '12 runtime ownership/port checks passed.'
