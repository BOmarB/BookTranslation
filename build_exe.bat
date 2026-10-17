@echo off
REM Build BookTranslator.exe. Preserves dist\.env across rebuilds.
cd /d "%~dp0"

echo Backing up dist\.env (if present)...
if exist "dist\.env" copy /y "dist\.env" "%TEMP%\booktrans_env_backup" >nul

echo Cleaning previous build...
if exist build rmdir /s /q build
if exist "BookTranslator.spec" del /q "BookTranslator.spec"
if exist dist rmdir /s /q dist

echo Building...
pyinstaller --onefile --windowed --name "BookTranslator" ^
  --icon "book_trans.ico" ^
  --add-data "book_trans.ico;." ^
  --add-data "fonts;fonts" ^
  --collect-all tkinterdnd2 ^
  --collect-all google.genai ^
  --collect-submodules google.auth ^
  --collect-submodules google.api ^
  --collect-all translators ^
  --collect-all cloudscraper ^
  --collect-submodules PIL ^
  --exclude-module google.cloud ^
  --exclude-module google.genai.tests ^
  --exclude-module torch ^
  --exclude-module torchvision ^
  --exclude-module torchaudio ^
  --exclude-module tensorflow ^
  --exclude-module keras ^
  --exclude-module scipy ^
  --exclude-module matplotlib ^
  --exclude-module sklearn ^
  --exclude-module pandas ^
  --exclude-module nltk ^
  --exclude-module sqlalchemy ^
  --exclude-module transformers ^
  --exclude-module onnxruntime ^
  --exclude-module cv2 ^
  --exclude-module av ^
  --exclude-module librosa ^
  --exclude-module soundfile ^
  --exclude-module yt_dlp ^
  --exclude-module yt_dlp_ejs ^
  --exclude-module lightning ^
  --exclude-module rich ^
  --exclude-module numba ^
  --exclude-module pygments ^
  --exclude-module jinja2 ^
  --exclude-module mako ^
  --exclude-module grpc ^
  app.py

if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo Restoring dist\.env...
if exist "%TEMP%\booktrans_env_backup" (
    copy /y "%TEMP%\booktrans_env_backup" "dist\.env" >nul
    del /q "%TEMP%\booktrans_env_backup"
)

echo.
echo Done: dist\BookTranslator.exe
echo Put your keys in dist\.env next to the EXE - rebuilds now keep it safe.
pause
