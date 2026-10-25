[CmdletBinding()]
param(
    [switch]$WithNeural,
    [switch]$WithModels
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param([string]$FilePath, [string[]]$ArgumentList)
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar $FilePath (codigo $LASTEXITCODE)."
    }
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
            throw 'Instale o Python 3.11 de python.org com o Python Launcher (py) e execute novamente.'
        }
        Invoke-Checked -FilePath 'py' -ArgumentList @('-3.11', '-m', 'venv', '.venv')
    }
    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'pip', 'install', '-e', '.')

    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
    }

    if ($WithNeural) {
        Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'pip', 'install', '-e', '.[voice]')
        $PreviousCMakeArgs = $env:CMAKE_ARGS
        $PreviousBuildParallelism = $env:CMAKE_BUILD_PARALLEL_LEVEL
        try {
            # Compilacao conservadora para o AMD A4: sem AVX/AVX2, BMI2, FMA ou F16C.
            # Requer Visual Studio Build Tools com C++ e CMake. Nenhum driver CUDA.
            $env:CMAKE_ARGS = '-DGGML_NATIVE=OFF -DGGML_CUDA=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_AVX512=OFF -DGGML_BMI2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF'
            $env:CMAKE_BUILD_PARALLEL_LEVEL = '2'
            # Recompila somente o mecanismo, sem wheel em cache ou reinstalar suas dependencias.
            # O segundo comando resolve as dependencias declaradas pelo extra usando o mecanismo ja instalado.
            Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'pip', 'install', '--no-cache-dir', '--force-reinstall', '--no-deps', '--no-binary=llama-cpp-python', 'llama-cpp-python==0.3.36')
            Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'pip', 'install', '-e', '.[llm]')
        }
        finally {
            if ($null -eq $PreviousCMakeArgs) {
                Remove-Item Env:CMAKE_ARGS -ErrorAction SilentlyContinue
            }
            else {
                $env:CMAKE_ARGS = $PreviousCMakeArgs
            }
            if ($null -eq $PreviousBuildParallelism) {
                Remove-Item Env:CMAKE_BUILD_PARALLEL_LEVEL -ErrorAction SilentlyContinue
            }
            else {
                $env:CMAKE_BUILD_PARALLEL_LEVEL = $PreviousBuildParallelism
            }
        }
    }

    if ($WithModels) {
        Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'pip', 'install', '-e', '.[models]')
        Invoke-Checked -FilePath $Python -ArgumentList @('-m', 'ivi.download_models')
    }

    Write-Host ''
    Write-Host 'Preparacao concluida. Inicie, na raiz do projeto:'
    Write-Host '  .\.venv\Scripts\python.exe -m ivi'
    Write-Host 'Abra http://127.0.0.1:8765 no computador que executa a I.V.I.'
    if (-not $WithNeural) {
        Write-Host 'Os mecanismos neurais nao foram instalados. Use -WithNeural para instala-los.'
    }
    if (-not $WithModels) {
        Write-Host 'Nenhum modelo foi baixado por este comando. Consulte o README ou use -WithModels.'
    }
}
finally {
    Pop-Location
}
