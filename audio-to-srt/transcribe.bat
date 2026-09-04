@echo off
setlocal
cd /d "%~dp0"
set "PATH=%~dp0;%~dp0.venv\Lib\site-packages\nvidia\cublas\bin;%~dp0.venv\Lib\site-packages\nvidia\cuda_nvrtc\bin;%~dp0.venv\Lib\site-packages\nvidia\cuda_runtime\bin;%PATH%"

REM Add --speakers to detect voices and interactively name them in the SRT.
REM First-time speaker setup: see README.md (pip + Hugging Face token).
if "%~1"=="" (
  ".venv\Scripts\python.exe" transcribe_to_srt.py --txt
) else (
  ".venv\Scripts\python.exe" transcribe_to_srt.py %* --txt
)

echo.
pause
