param([switch]$Journey, [switch]$Renderer)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw 'Verification failed; inspect the preceding output' } }
if ($Journey) {
    if (-not $env:CONVERZA_JOURNEY_TEST_DSN) { throw 'Set CONVERZA_JOURNEY_TEST_DSN to its disposable loopback test_converza_journey database' }
    $env:CONVERZA_RUN_JOURNEY = '1'
}
python scripts/verify_core.py
Check-Exit
Set-Location "$root/core"
python -m services.workflow.evals.run
Check-Exit
python evals/memory/run.py
Check-Exit
python -m services.memory.evals.run
Check-Exit
python evals/memory_sleyz_safety.py
Check-Exit
python -m services.sleyz.evals.run
Check-Exit
python -m services.milo.evals.run
Check-Exit
python -m services.vea.evals.run
Check-Exit
python -m services.feed.evals
Check-Exit
Set-Location "$root/web"
npm test
Check-Exit
npm run typecheck
Check-Exit
npm audit --audit-level=moderate
Check-Exit
npm run build
Check-Exit
Set-Location $root
if ($Renderer) {
    & "$PSScriptRoot/verify_renderer.ps1"
}
