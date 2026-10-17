@echo off
echo Building pigeon.exe...
python -m PyInstaller --noconsole --onefile --clean --icon "%~dp0icon.ico" --add-data "%~dp0pigeon.png;." --name "pigeon" --distpath "%~dp0." "%~dp0ask_admin_twice.py"
echo Done!
