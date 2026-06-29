#!/bin/bash
cd /opt/babybuddy

export DJANGO_SETTINGS_MODULE=babybuddy.settings.development

# Build assets (optional but safe)
gulp build

# Start server
pipenv run python manage.py runserver 0.0.0.0:8000
