@echo off
setlocal
cd /d "%~dp0"

set "IVI_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%IVI_PYTHON%" (
    echo Nao encontrei o Python da I.V.I. em .venv\Scripts\python.exe.
    echo Primeiro conclua a instalacao descrita no README.md desta pasta.
    echo Este atalho nao instala pacotes nem altera sua configuracao.
    pause
    exit /b 1
)

"%IVI_PYTHON%" -m ivi.desktop
set "IVI_EXIT_CODE=%ERRORLEVEL%"
if not "%IVI_EXIT_CODE%"=="0" (
    echo.
    echo Nao foi possivel abrir a I.V.I. Codigo: %IVI_EXIT_CODE%
    echo Leia a mensagem acima e as instrucoes no README.md.
    pause
)
exit /b %IVI_EXIT_CODE%
