@echo off
REM install_gpu.bat — 安装 GPU 版 PaddlePaddle + open-guji-cv（Windows）
REM
REM 用法：
REM   install_gpu.bat           （默认 CUDA 12.3）
REM   install_gpu.bat cu118     （CUDA 11.8）
REM   install_gpu.bat cpu       （仅 CPU）
REM
REM 支持的 CUDA 版本：cu118 / cu120 / cu121 / cu122 / cu123 / cu124
REM 查询 CUDA 版本：nvidia-smi

setlocal

SET CUDA_TAG=%~1
IF "%CUDA_TAG%"=="" SET CUDA_TAG=cu123

SET PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/%CUDA_TAG%/

echo =========================================
echo  open-guji-cv GPU 安装脚本 (Windows)
echo  CUDA 标签: %CUDA_TAG%
echo =========================================

REM 1. 卸载 CPU 版
echo.
echo [1/4] 卸载 CPU 版 paddlepaddle（如有）...
pip uninstall paddlepaddle -y 2>nul

REM 2. 安装 GPU 版 paddlepaddle
echo.
echo [2/4] 安装 paddlepaddle-gpu (%CUDA_TAG%)...
IF "%CUDA_TAG%"=="cpu" (
    pip install paddlepaddle
) ELSE (
    pip install paddlepaddle-gpu -i %PADDLE_INDEX%
)
IF ERRORLEVEL 1 goto :error

REM 3. 安装 paddleocr
echo.
echo [3/4] 安装 paddleocr...
pip install "paddleocr>=2.8.0"
IF ERRORLEVEL 1 goto :error

REM 4. 安装 open-guji-cv
echo.
echo [4/4] 安装 open-guji-cv[gpu]...
IF EXIST pyproject.toml (
    pip install -e ".[gpu]"
) ELSE (
    pip install "open-guji-cv[gpu]"
)
IF ERRORLEVEL 1 goto :error

echo.
echo =========================================
echo  安装完成！验证：
echo    python -c "import paddle; paddle.utils.run_check()"
echo =========================================
goto :eof

:error
echo.
echo [错误] 安装失败，请检查上方输出。
exit /b 1
