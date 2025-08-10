@echo off
setlocal
cd /d "%~dp0"

rem 1) Preferir el launcher gráfico (sin consola)
where pyw >nul 2>nul
if %errorlevel%==0 (
  pyw -3 "clipboard_buddy.py"
  goto :eof
)

rem 2) Si no hay pyw, probar py (consola breve) 
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "clipboard_buddy.py"
  goto :eof
)

rem 3) Fallback directo a pythonw/python en PATH
where pythonw >nul 2>nul && (pythonw "clipboard_buddy.py" & goto :eof)
where python  >nul 2>nul && (python  "clipboard_buddy.py" & goto :eof)

echo No se encontro Python. Instalalo desde https://www.python.org (tildando "Add Python to PATH").
pause
