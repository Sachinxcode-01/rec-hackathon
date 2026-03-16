import os

# Binding to the port Railway provides, defaulting to 8080 which is common for Nixpacks
bind = "0.0.0.0:" + os.environ.get("PORT", "8080")

# Using eventlet worker class for Socket.IO support
worker_class = "eventlet"
workers = 1
timeout = 300
preload_app = False

# Detailed logging to terminal for Railway dashboard
accesslog = "-"
errorlog = "-"
loglevel = "info"
capture_output = True
enable_stdio_inheritance = True
