@echo off
setlocal

echo ====================== Build Web3 node client ======================
cd /d "%~dp0.."
if errorlevel 1 goto fail

if not exist build mkdir build
if not exist dist mkdir dist
set "BUILD_LOG=build\client-build.log"
set "BUILD_RESULT=dist\BUILD_RESULT.txt"
set "BUILD_STATUS=FAILED"
set "BUILD_MESSAGE=Build did not finish."
(
    echo Web3 node client build log
    echo Started: %DATE% %TIME%
    echo Working directory: %CD%
) > "%BUILD_LOG%"

echo [1/4] Check Python
call :run python --version
if errorlevel 1 goto fail

echo [2/4] Install runtime dependencies
(
    echo requests
    echo pywebview
) > build\client-runtime-requirements.txt
call :run python -m pip install -r build\client-runtime-requirements.txt
if errorlevel 1 goto fail

echo [2.5/4] Check PyInstaller
call :run python -m PyInstaller --version
if errorlevel 1 (
    echo PyInstaller is required for building the exe.
    echo Installing PyInstaller from default pip index...
    call :run python -m pip install PyInstaller
    if errorlevel 1 (
        echo Retry installing PyInstaller from Tsinghua mirror...
        call :run python -m pip install PyInstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    )
)
call :run python -m PyInstaller --version
if errorlevel 1 goto pyinstaller_fail

echo [3/4] Build exe with PyInstaller
if exist node.ico (
    call :run python -m PyInstaller --clean -F -w -i node.ico --name web3-node client\main.py
) else (
    call :run python -m PyInstaller --clean -F -w --name web3-node client\main.py
)
if errorlevel 1 goto fail

echo [4/4] Copy sidecar config files
if not exist dist\node_config.json call :run copy client\node_config.example.json dist\node_config.json
if exist .env if not exist dist\.env call :run copy .env dist\.env
if errorlevel 1 goto fail

set "BUILD_STATUS=SUCCESS"
set "BUILD_MESSAGE=Build complete."
goto finish

:fail
set "BUILD_STATUS=FAILED"
set "BUILD_MESSAGE=Build failed. Check build\client-build.log."
goto finish

:pyinstaller_fail
set "BUILD_STATUS=FAILED"
set "BUILD_MESSAGE=PyInstaller is not installed for the current Python interpreter. If you are using a very new Python version, install Python 3.12 or 3.13 and run this script again."
goto finish

:finish
(
    echo status=%BUILD_STATUS%
    echo message=%BUILD_MESSAGE%
    echo exe=dist\web3-node.exe
    echo config=dist\node_config.json
    echo log=%BUILD_LOG%
    echo finished=%DATE% %TIME%
) > "%BUILD_RESULT%"
echo.
if "%BUILD_STATUS%"=="SUCCESS" (
    echo ====================== Build complete ======================
) else (
    echo ====================== Build failed ======================
)
type dist\BUILD_RESULT.txt
echo.
echo Build result saved to dist\BUILD_RESULT.txt
echo Build log saved to %BUILD_LOG%
pause
if "%BUILD_STATUS%"=="SUCCESS" exit /b 0
exit /b 1

:run
echo $ %*
>> "%BUILD_LOG%" echo $ %*
%* >> "%BUILD_LOG%" 2>&1
if not errorlevel 1 exit /b 0
echo Command failed. See %BUILD_LOG%
>> "%BUILD_LOG%" echo Command failed.
exit /b 1
