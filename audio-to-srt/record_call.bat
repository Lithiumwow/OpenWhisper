@echo off
setlocal
cd /d "%~dp0"
set "PATH=%~dp0;%~dp0.venv\Lib\site-packages\nvidia\cublas\bin;%~dp0.venv\Lib\site-packages\nvidia\cuda_nvrtc\bin;%~dp0.venv\Lib\site-packages\nvidia\cuda_runtime\bin;%PATH%"

echo Recording speaker output (Teams / system audio).
echo Press Ctrl+C when the call ends — then transcription starts.
echo.
".venv\Scripts\python.exe" record_call.py %* --txt

echo.
pause
