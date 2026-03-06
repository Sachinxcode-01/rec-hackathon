import os

# Binding to the port Railway provides, defaulting to 8080 which is common for Nixpacks
bind = "0.0.0.0:" + os.environ.get("PORT", "8080")

# Stick with 1 worker during debugging to see all logs clearly
workers = 1
threads = 4
timeout = 300
preload_app = False

# Detailed logging to terminal for Railway dashboard
accesslog = "-"
errorlog = "-"
loglevel = "debug"
capture_output = True
enable_stdio_inheritance = True
