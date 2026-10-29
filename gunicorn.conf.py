"""Production server settings; Railway supplies PORT at runtime."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
