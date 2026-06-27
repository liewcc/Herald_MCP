@echo off
cd /d "%~dp0"
for /f "delims=" %%p in ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do start "" "%%p" "%~dp0shell_agent.py"
