@echo off
title Padronizador de Clientes
cd /d "%~dp0"

echo ============================================
echo   Padronizador de Clientes - iniciando...
echo ============================================
echo.

rem Procura o Python primeiro em locais conhecidos (caminho absoluto), sem
rem depender do PATH do Windows: quando o PATH do sistema nao inclui a pasta
rem do Python, um processo aberto por duplo clique nao acha "python" so pelo
rem nome, mesmo estando tudo instalado. Se o seu Python estiver em outro
rem lugar, acrescente o caminho na lista abaixo.
set "PY_CMD="
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY_CMD if exist "C:\Python313\python.exe" set "PY_CMD=C:\Python313\python.exe"
if not defined PY_CMD (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY_CMD=%%D\python.exe"
)
if not defined PY_CMD where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD where py >nul 2>nul && set "PY_CMD=py"
if not defined PY_CMD (
    echo [ERRO] Python nao foi encontrado neste computador.
    echo Instale o Python em https://www.python.org/downloads/ e tente de novo.
    pause
    exit /b 1
)

set "PS_CMD=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS_CMD%" set "PS_CMD=powershell"

rem A interface (tela do navegador) agora e feita em Vue e precisa ser
rem compilada com o Node.js antes de abrir - mesma logica de deteccao usada
rem acima pro Python, pra nao depender do PATH do Windows.
set "NPM_CMD="
if exist "%ProgramFiles%\nodejs\npm.cmd" set "NPM_CMD=%ProgramFiles%\nodejs\npm.cmd"
if not defined NPM_CMD if exist "%ProgramFiles(x86)%\nodejs\npm.cmd" set "NPM_CMD=%ProgramFiles(x86)%\nodejs\npm.cmd"
if not defined NPM_CMD (
    where npm >nul 2>nul && set "NPM_CMD=npm"
)

if not defined NPM_CMD (
    echo [AVISO] Node.js/npm nao foi encontrado neste computador.
    echo A interface nova precisa do Node.js pra ser compilada.
    echo Instale a versao LTS em https://nodejs.org/ e rode este atalho de novo.
    if not exist "%~dp0static\dist\app.js" (
        echo Nao ha uma interface ja compilada pra usar enquanto isso.
        pause
        exit /b 1
    )
    echo Abrindo com a ultima versao da interface ja compilada neste computador...
) else (
    if not exist "%~dp0frontend\node_modules" (
        echo Instalando a interface pela primeira vez, aguarde um instante...
        pushd "%~dp0frontend"
        call "%NPM_CMD%" install --no-fund --no-audit --loglevel=error
        popd
    )
    echo Compilando a interface...
    pushd "%~dp0frontend"
    call "%NPM_CMD%" run build --silent
    popd
)

if not defined PADRONIZADOR_PORT set "PADRONIZADOR_PORT=5057"
echo Liberando a porta %PADRONIZADOR_PORT%, se estiver em uso...
"%PS_CMD%" -NoProfile -Command "Get-NetTCPConnection -LocalPort %PADRONIZADOR_PORT% -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" >nul 2>nul

echo Verificando dependencias...
%PY_CMD% -c "import flask, openpyxl, rapidfuzz" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias pela primeira vez, aguarde um instante...
    %PY_CMD% -m pip install -r requirements.txt --quiet
)

echo.
echo Tudo pronto! Abrindo o Padronizador de Clientes no navegador...
echo (Para fechar o programa, feche esta janela ou aperte Ctrl+C)
echo.
%PY_CMD% app.py

echo.
echo O servidor foi encerrado.
pause
