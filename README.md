# OCR Case Tool (Flask + SQLite)

Features
- Users (register/login), roles (**admin**, **user**)
- Create **cases**, upload screenshots (JPG/PNG)
- **Auto OCR** text extraction on upload (Tesseract), re-run button
- **Notes** per case
- **Admin dashboard**: audit who uploaded what + extracted text
- Activity log table

## Setup (macOS / zsh)
```bash
# 1) Tesseract
brew install tesseract

# 2) Python env
cd ocr_case_tool
python3 -m venv .venv
source .venv/bin/activate

# 3) Deps
pip install -r requirements.txt

# 4) Config
cp .env.example .env
# Option A (recommended): leave DATABASE_URL commented (app uses absolute default)
# Option B: set ABSOLUTE SQLite URL:
# DATABASE_URL=sqlite:////Users/you/Downloads/ocr_case_tool/instance/ocr_case_tool.sqlite
# If Tesseract not found:
# TESSERACT_CMD=/opt/homebrew/bin/tesseract

# 5) Init DB + create admin
python app.py init-db
python app.py create-admin --email admin@example.com --name "Admin" --password "ChangeMe123!"

# 6) Run
python app.py run
```

## Setup (Windows / VS Code PowerShell)
```powershell
# 1) Install Tesseract (UB Mannheim build). Ensure tesseract.exe is in PATH.
cd ocr_case_tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Optional absolute DB:
# DATABASE_URL=sqlite:////C:/Users/you/Downloads/ocr_case_tool/instance/ocr_case_tool.sqlite
python app.py init-db
python app.py create-admin --email admin@example.com --name "Admin" --password "ChangeMe123!"
python app.py run
```

## Notes
- App normalizes a relative SQLite URL into an absolute one to avoid "unable to open database file".
- Creates `instance/` and `instance/uploads/` automatically.
- Allowed files: .jpg, .jpeg, .png
