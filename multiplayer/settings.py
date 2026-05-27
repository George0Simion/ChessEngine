import os

ALLOWED_TIME_CONTROLS = {3, 5, 10}
DEFAULT_TIME_CONTROL = 3
INCREMENT_SEC = 2
CLOCK_TICK_SEC = 1.0
DISCONNECT_GRACE_SEC = int(os.environ.get("MP_DISCONNECT_GRACE", "45"))
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
