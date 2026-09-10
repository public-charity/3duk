# The known working pipeline Python and native DLL search path, including for resumed jobs.
# Example: & projects/one/Tools/python.ps1 projects/one/Tools/phase1_qc.py --max-jobs 2
$ErrorActionPreference = "Stop"
$pipelinePython = "C:/Users/Shadow/code/3duk-env/env/python.exe"
$previousPath = $env:PATH
try {
    $env:PATH = "C:/Users/Shadow/code/3duk-env/env/Library/bin;" + $previousPath
    & $pipelinePython @args
    $pythonCode = $LASTEXITCODE
} finally {
    $env:PATH = $previousPath
}
exit $pythonCode
