$ErrorActionPreference = "Continue"

$subtopics = @(
    "ap-physics-1.unit-1.position-velocity-acceleration",
    "ap-physics-1.unit-1.projectile-motion",
    "ap-physics-1.unit-2.newtons-laws-free-body-diagrams",
    "ap-physics-1.unit-2.friction-circular-motion",
    "ap-physics-1.unit-3.work-kinetic-energy",
    "ap-physics-1.unit-3.potential-energy-conservation",
    "ap-physics-1.unit-4.impulse-momentum",
    "ap-physics-1.unit-4.collisions-conservation",
    "ap-physics-1.unit-5.rotational-kinematics-torque",
    "ap-physics-1.unit-5.rotational-newtons-2nd-law",
    "ap-physics-1.unit-6.rotational-kinetic-energy",
    "ap-physics-1.unit-6.angular-momentum-conservation",
    "ap-physics-1.unit-7.simple-harmonic-motion",
    "ap-physics-1.unit-7.period-energy-shm",
    "ap-physics-1.unit-8.density-pressure",
    "ap-physics-1.unit-8.buoyancy-bernoulli"
)

$logPath = Join-Path (Get-Location) "..\..\bulk_subtopics_phys1.log"
$start = Get-Date
$total = $subtopics.Count
"[subbulk] starting $total sub-topics at $start" | Tee-Object -FilePath $logPath

$failures = @()

function RunPhase {
    param([string]$phaseName, [string[]]$extraArgs)
    for ($i = 0; $i -lt $script:total; $i++) {
        $slug = $script:subtopics[$i]
        $n = $i + 1
        $tstart = Get-Date
        "[subbulk] $phaseName ($n/$($script:total)) $slug ..." | Tee-Object -Append -FilePath $script:logPath
        $cliArgs = @("-m", "app.content.cli", $phaseName, "--topic-slug", $slug) + $extraArgs
        & .venv\Scripts\python.exe @cliArgs 2>&1 | Tee-Object -Append -FilePath $script:logPath
        $rc = $LASTEXITCODE
        $dur = [int]((Get-Date) - $tstart).TotalSeconds
        if ($rc -eq 0) {
            "[subbulk] $phaseName ($n/$($script:total)) OK in ${dur}s :: $slug" | Tee-Object -Append -FilePath $script:logPath
        } else {
            $script:failures += "$phaseName rc=$rc :: $slug"
            "[subbulk] $phaseName ($n/$($script:total)) FAIL rc=$rc in ${dur}s :: $slug" | Tee-Object -Append -FilePath $script:logPath
        }
    }
}

RunPhase -phaseName "ingest"   -extraArgs @()
RunPhase -phaseName "generate" -extraArgs @("--force")
RunPhase -phaseName "quiz"     -extraArgs @()

$mins = [int]((Get-Date) - $start).TotalMinutes
$nfail = $failures.Count
"[subbulk] DONE in ${mins} min. failures=$nfail" | Tee-Object -Append -FilePath $logPath
foreach ($fail in $failures) {
    "[subbulk]   FAIL $fail" | Tee-Object -Append -FilePath $logPath
}
