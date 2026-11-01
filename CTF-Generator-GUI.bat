@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "ASC CTF Generator" pythonw "%~dp0ctf_gui.py"
) else (
    python "%~dp0ctf_gui.py"
)
