@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM ============================================================
REM  coding agent launcher (this file is UTF-8; chcp above fixes display)
REM
REM  用法：双击本文件。
REM  不要在 Git Bash 里执行，结尾的 pause 会把终端挂住。
REM
REM  前置条件：
REM    · conda 环境 codingagent 已创建（见 scripts\activate.bat）
REM    · 前端依赖已安装（web\node_modules 存在）
REM
REM  假定项目路径与 conda 路径不含空格。若含空格，相关路径需要补引号。
REM ============================================================

REM ---------- 可修改的配置 ----------
set "CONDA_ROOT=D:\huanjing\miniconda3"
set "ENV_NAME=codingagent"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "OPEN_BROWSER=1"
REM ----------------------------------

set "ENV_PATH=%CONDA_ROOT%\envs\%ENV_NAME%"
set "PYTHON=%ENV_PATH%\python.exe"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "WEB=%ROOT%\web"

echo.
echo ============================================================
echo   coding agent 一键启动
echo ------------------------------------------------------------
echo   项目目录   %ROOT%
echo   后端       http://127.0.0.1:%BACKEND_PORT%   [conda %ENV_NAME%]
echo   前端       http://127.0.0.1:%FRONTEND_PORT%
echo ============================================================
echo.

REM ---------- 前置检查 ----------
if not exist "%PYTHON%" (
    echo [错误] 找不到项目环境：%PYTHON%
    echo        创建环境：conda create -n %ENV_NAME% python=3.12 -y
    echo        安装依赖：pip install -e ".[dev]"
    goto :fail
)

if not exist "%WEB%\package.json" (
    echo [错误] 找不到前端工程：%WEB%
    goto :fail
)

if not exist "%WEB%\node_modules" (
    echo [错误] 前端依赖尚未安装
    echo        请先执行：cd /d "%WEB%"
    echo                    npm install
    goto :fail
)

REM ---------- 端口占用提示：只警告，不阻断 ----------
netstat -ano | findstr /r /c:":%BACKEND_PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 echo [警告] 端口 %BACKEND_PORT% 已被占用，后端可能启动失败

netstat -ano | findstr /r /c:":%FRONTEND_PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 echo [警告] 端口 %FRONTEND_PORT% 已被占用，前端可能改用其它端口

echo 正在启动两个服务...
echo.

REM ---------- 启动后端，独立窗口 ----------
REM 直接用环境里的 python.exe，不走 conda activate。
REM 因为 bash 工具会自动把解释器所在环境加入子进程 PATH
REM （见 agent/util.py 的 interpreter_path_dirs），这样起就够了，
REM 还能避开在 cmd /k 里嵌套引号的麻烦。
start "coding agent 后端 %BACKEND_PORT%" /D "%ROOT%" cmd /k %PYTHON% -m agent.server --port %BACKEND_PORT%

REM ---------- 启动前端，独立窗口 ----------
start "coding agent 前端 %FRONTEND_PORT%" /D "%WEB%" cmd /k npm run dev

REM ---------- 等就绪后打开浏览器 ----------
if not "%OPEN_BROWSER%"=="1" goto :done

echo 等待前端就绪...
where curl >nul 2>&1
if errorlevel 1 goto :fixed_wait

for /l %%i in (1,1,40) do (
    timeout /t 1 /nobreak >nul
    curl -s -o nul --max-time 2 http://127.0.0.1:%FRONTEND_PORT%
    if not errorlevel 1 (
        start "" "http://127.0.0.1:%FRONTEND_PORT%"
        goto :done
    )
)
echo [提示] 等待超时，请手动打开 http://127.0.0.1:%FRONTEND_PORT%
goto :done

:fixed_wait
timeout /t 8 /nobreak >nul
start "" "http://127.0.0.1:%FRONTEND_PORT%"

:done
echo.
echo ------------------------------------------------------------
echo  已启动。两个服务各占一个窗口：
echo    · 关闭「后端」窗口 = 停止后端
echo    · 关闭「前端」窗口 = 停止前端
echo.
echo  浏览器访问：http://127.0.0.1:%FRONTEND_PORT%
echo ------------------------------------------------------------
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
