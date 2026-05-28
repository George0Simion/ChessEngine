import os

ALLOWED_TIME_CONTROLS = {3, 5, 10}
DEFAULT_TIME_CONTROL = 3
INCREMENT_SEC = 2
CLOCK_TICK_SEC = 1.0
DISCONNECT_GRACE_SEC = int(os.environ.get("MP_DISCONNECT_GRACE", "45"))
# Must resolve to the same value the Flask app uses to sign JWTs, otherwise
# tokens issued by the web service won't validate here. Mirror that logic:
# prefer JWT_SECRET_KEY, fall back to SECRET_KEY.
SECRET_KEY = (
    os.environ.get("JWT_SECRET_KEY")
    or os.environ.get("SECRET_KEY")
    or "dev-secret-change-in-production"
)
