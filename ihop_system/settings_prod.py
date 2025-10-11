# settings_prod.py
import os
GOOGLE_TIMEZONE_API_KEY = os.environ.get("GOOGLE_TZ_BACKEND_KEY", "")
TIMEZONE_HTTP_TIMEOUT = int(os.environ.get("TIMEZONE_HTTP_TIMEOUT", "4"))
