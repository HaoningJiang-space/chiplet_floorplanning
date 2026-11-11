# Dot-source from PowerShell: . ./tools/windows_env.ps1
# Only changes this shell; does not change system/user environment variables.
$chipletRepo = Split-Path -Parent $PSScriptRoot
$chipletToolchain = Join-Path $chipletRepo 'local/toolchain/Library'
$chipletPython = Join-Path $chipletRepo '.venv/Scripts'
foreach ($chipletRequired in @($chipletToolchain, $chipletPython)) {
    if (-not (Test-Path -LiteralPath $chipletRequired)) {
        throw "Missing local environment: $chipletRequired. See docs/windows-local.md."
    }
}
$env:PATH = "$chipletPython;$chipletToolchain/bin;$env:PATH"
$env:TCL_LIBRARY = Join-Path $chipletToolchain 'lib/tcl8.6'
$env:OPENBLAS_NUM_THREADS = '1'
