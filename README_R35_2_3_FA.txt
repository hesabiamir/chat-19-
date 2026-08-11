BARSAN AI Chatbot — R35.2.3 Railway Final Audited

این نسخه از ZIP اصلی و در یک پوشهٔ تازه بازسازی شده است.
مسیر استقرار فقط یک قرارداد دارد:
railway.json -> Dockerfile -> python /app/railway_start.py -> uvicorn main:app

نکتهٔ حیاتی:
فایل‌های داخل ZIP نهایی مستقیم در ریشهٔ archive هستند و هیچ زیرپوشه‌ای ندارند.
همان فایل‌ها را مستقیم با GitHub Add files -> Upload files در ریشهٔ repository
قرار دهید. Dockerfile، نه فایل builtin_sources.bundle.part01 تا part09،
railway.json، requirements.lock.txt، pyproject.toml و main.py باید کنار هم باشند.

Dockerfile نهایی هیچ دستور COPY برای pyproject.toml ندارد. اگر Railway دوباره
خطای checksum برای /pyproject.toml نشان داد، سرویس هنوز Dockerfile یا Root
Directory قدیمی را مصرف می‌کند و Build مربوط به این artifact نیست.

منابع PDF در نه قطعهٔ حداکثر 6MB قرار دارند تا محدودیت GitHub Web Upload، Git Data API و واسط شبکه رعایت
شود. Docker در Build قطعات را با SHA-256 بررسی، ترکیب و استخراج می‌کند.

Start:
python /app/railway_start.py

فرمان واقعی برنامه:
python -m uvicorn main:app --host 0.0.0.0 --port $PORT

Health: /healthz
Readiness: /readyz
Volume: /data
Replica برای SQLite: 1
