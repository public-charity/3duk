# Generate Intermediate/PythonStub/unreal.py headlessly.
# The PythonScriptPlugin only writes the stub outside commandlets (PythonScriptPlugin.cpp:1604,
# "IsDeveloperModeEnabled() && GIsEditor && !IsRunningCommandlet()"), so bDeveloperMode=True alone does nothing for
# -run=pythonscript. The PythonOnlineDocs commandlet calls the same writer (PythonOnlineDocsCommandlet.cpp:57 ->
# PyWrapperTypeRegistry.cpp:3307) and, with no -Include* switch, includes every type. It also tries to write Sphinx
# sources next to the plugin; failures there are warnings and do not affect the stub.
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/ue/gen_python_stub.ps1
param([string]$Log = "python_stub.log")
$ErrorActionPreference = "Continue"
$UE = "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$Proj = (Resolve-Path "$PSScriptRoot\..\..\Thanet.uproject").Path
$Stub = Join-Path (Split-Path $Proj) "Intermediate\PythonStub\unreal.py"
$flags = @("-run=PythonOnlineDocs", "-unattended", "-nopause", "-nosplash", "-stdout", "-FullStdOutLogOutput", "-NoLiveCoding", "-log=$Log")
& $UE "$Proj" @flags
$code = $LASTEXITCODE
if (Test-Path $Stub) {
	$lines = (Get-Content $Stub | Measure-Object -Line).Lines
	Write-Host "THANET_OK gen_python_stub {""stub"": ""$($Stub -replace '\\','/')"", ""lines"": $lines, ""engine_exit"": $code}"
	exit 0
}
Write-Host "THANET_FAIL gen_python_stub stub not written (engine exit $code); see Saved/Logs/$Log"
exit 1
