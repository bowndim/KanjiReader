@echo off
python -m venv venv
call C:\Users\apowe\Desktop\kanji_readers\venv\Scripts\activate.bat
pip install -r requirements.txt
python -m playwright install chromium
echo Setup complete.
