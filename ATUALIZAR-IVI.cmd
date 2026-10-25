@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo Nao encontrei o Python Launcher. Instale o Python 3.11 conforme o README.md.
    pause
    exit /b 1
)
py -3.11 "%~dp0scripts\atualizar_ivi.py"
set "IVI_EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %IVI_EXIT_CODE%
