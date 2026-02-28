#!/bin/bash
cd "$(dirname "$0")"
if [ "$1" = "laptop" ]; then
    source venv_laptop/bin/activate
else
    source venv/bin/activate
fi
exec gunicorn -w 2 -b 127.0.0.1:8080 "app:create_app()"
