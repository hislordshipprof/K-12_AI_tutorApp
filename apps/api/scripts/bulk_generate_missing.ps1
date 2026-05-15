$ErrorActionPreference = "Continue"
$missing = @(
    "ap-physics-1.unit-6.energy-momentum-rotating-systems",
    "ap-calc-bc.unit-2.differentiation-definition-properties",
    "ap-calc-bc.unit-3.differentiation-composite-implicit-inverse",
    "ap-calc-bc.unit-4.contextual-applications-differentiation",
    "ap-calc-bc.unit-5.analytical-applications-differentiation",
    "ap-calc-bc.unit-6.integration-accumulation-change",
    "ap-calc-bc.unit-7.differential-equations",
    "ap-calc-bc.unit-8.applications-integration",
    "ap-calc-bc.unit-9.parametric-polar-vector-functions",
    "ap-calc-bc.unit-10.infinite-sequences-series",
    "ap-biology.unit-1.chemistry-of-life",
    "ap-biology.unit-2.cell-structure-function",
    "ap-biology.unit-3.cellular-energetics",
    "ap-biology.unit-4.cell-communication-cycle",
    "ap-biology.unit-5.heredity",
    "ap-biology.unit-6.gene-expression-regulation",
    "ap-biology.unit-7.natural-selection",
    "ap-biology.unit-8.ecology"
)

$total = $missing.Count
$ok = 0
$fail = 0
$start = Get-Date
$logPath = Join-Path (Get-Location) "..\..\bulk_generate.log"

"[bulk] starting $total topics at $start" | Tee-Object -FilePath $logPath

for ($i = 0; $i -lt $total; $i++) {
    $slug = $missing[$i]
    $n = $i + 1
    $tstart = Get-Date
    "[bulk] ($n/$total) $slug ..." | Tee-Object -Append -FilePath $logPath
    & .venv\Scripts\python.exe -m app.content.cli generate --topic-slug $slug 2>&1 | Tee-Object -Append -FilePath $logPath
    $rc = $LASTEXITCODE
    $dur = [int]((Get-Date) - $tstart).TotalSeconds
    if ($rc -eq 0) {
        $ok++
        "[bulk] ($n/$total) OK in ${dur}s :: $slug" | Tee-Object -Append -FilePath $logPath
    } else {
        $fail++
        "[bulk] ($n/$total) FAIL rc=$rc in ${dur}s :: $slug" | Tee-Object -Append -FilePath $logPath
    }
}

$total_dur = [int]((Get-Date) - $start).TotalMinutes
"[bulk] DONE :: $ok ok / $fail fail in ${total_dur}min" | Tee-Object -Append -FilePath $logPath
