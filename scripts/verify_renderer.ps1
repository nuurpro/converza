param([string]$Image = 'converza/approved-renderer:1.3.9-converza')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$vendor = Join-Path $root 'Vea/services/MoneyPrinterTurbo'
$output = Join-Path $root 'reports/local'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$modules = @(Get-Content (Join-Path $vendor 'SOURCE_MANIFEST.milo.txt') |
    Where-Object { $_ -match '/test/services/(test_[A-Za-z0-9_]+)\.py$' } |
    ForEach-Object { 'test.services.' + [IO.Path]::GetFileNameWithoutExtension($_) })
if (-not $modules.Count) { throw 'The approved source manifest contains no renderer tests' }
$names = ConvertTo-Json -InputObject $modules -Compress
$code = @"
import io,json,unittest
from pathlib import Path
names=json.loads(r'''$names''')
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
log=io.StringIO()
result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
report={'discovered':result.testsRun,'passed':result.testsRun-len(result.skipped)-len(result.errors)-len(result.failures),'errors':len(result.errors),'failures':len(result.failures),'skipped':[{'test':t.id(),'reason':r} for t,r in result.skipped],'network_disabled':True,'successful':result.wasSuccessful()}
Path('/verification-output/renderer-tests.log').write_text(log.getvalue())
Path('/verification-output/renderer-tests.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
raise SystemExit(not result.wasSuccessful() or bool(result.skipped))
"@
docker run --rm --network none -e MPT_APPROVED_ONLY=1 -e MPT_RUN_API_TESTS=1 -e MPT_RUN_MEDIA_TESTS=1 `
    -v "${vendor}/test:/MoneyPrinterTurbo/test:ro" `
    -v "${vendor}/scripts:/MoneyPrinterTurbo/scripts:ro" `
    -v "${output}:/verification-output" $Image python -c $code
if ($LASTEXITCODE -ne 0) { throw 'Renderer verification failed; inspect reports/local/renderer-tests.log' }
