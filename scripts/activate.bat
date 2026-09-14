@echo off
chcp 65001 >nul
REM 一键激活本项目的 conda 环境（codingagent）
REM 用法：双击本文件；本机 activate_torchgpu.bat 同样的用法。
REM 注意：不要在 Git Bash 里直接执行，结尾的 cmd /k 会把终端挂住。
set "CONDA_ROOT=D:\huanjing\miniconda3"
set "ENV_PATH=D:\huanjing\miniconda3\envs\codingagent"

if not exist "%CONDA_ROOT%\condabin\conda.bat" (
    echo [错误] 未找到 conda: %CONDA_ROOT%
    pause
    exit /b 1
)
if not exist "%ENV_PATH%\python.exe" (
    echo [错误] 未找到环境: %ENV_PATH%
    echo        创建: conda create -n codingagent python=3.12 -y
    echo        装依赖: pip install -e ".[dev]"
    pause
    exit /b 1
)

call "%CONDA_ROOT%\condabin\conda.bat" activate "%ENV_PATH%"

REM 切到项目根目录（本文件所在目录的上一级）
cd /d "%~dp0.."

echo.
echo 已激活环境: %ENV_PATH%
echo 项目目录:   %CD%
echo.
echo 运行: python -m agent.repl -t "任务描述"
echo 测试: python -m pytest
echo 配置: python -m agent.repl --show-config
echo.
cmd /k
