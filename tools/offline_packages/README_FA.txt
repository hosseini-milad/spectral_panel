بسته آفلاین فایل‌های محلی Swagger

این فایل رسمی و بدون تغییر از PyPI دریافت شده است. مجوزهای خود بسته، Swagger UI و Redoc داخل فایل wheel حفظ شده‌اند.
نسخه: drf-spectacular-sidecar 2026.10.1
SHA256: fe1d005d8ac9b5d0472f2fe5deeb2e7d6dcffaa24118044f22578b4b8c4b31f2
منبع: https://files.pythonhosted.org/packages/55/09/13509939a12e953759fa2f281b28dc14813c8c331addf3838fccdc71b364/drf_spectacular_sidecar-2026.10.1-py3-none-any.whl

پس از git pull، از ریشه پروژه نصب کنید (Django باید از قبل نصب باشد):
python -m pip install --no-index "tools/offline_packages/drf_spectacular_sidecar-2026.10.1-py3-none-any.whl"

بررسی نصب:
python -c "import drf_spectacular_sidecar; print(drf_spectacular_sidecar.__file__)"

بررسی پروژه پس از تکمیل همه نیازمندی‌ها:
python manage.py check

این پوشه فقط بسته sidecar را دارد؛ سایر وابستگی‌های پروژه جداگانه نصب می‌شوند. این روش به دانلود فایل از داخل چت یا دسترسی pip به PyPI وابسته نیست.
