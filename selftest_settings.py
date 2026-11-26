from gostibot.settings import *  # noqa: F401,F403

# Отдельная копия базы для самопроверки бота — рабочую базу тест не трогает.
DATABASES["default"]["NAME"] = "/tmp/selftest.sqlite3"
