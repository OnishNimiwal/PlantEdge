"""
Django settings for mrpl-ai-workbench project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from workspace root or backend root
load_dotenv(BASE_DIR.parent / '.env')
load_dotenv(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/stable/howto/deployment/checklist/

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-mrpl-ai-workbench-pc5-local-secret-key-2026')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

# LAN & Allowed Hosts Configuration
allowed_hosts_env = os.getenv('ALLOWED_HOSTS', '*')
if allowed_hosts_env == '*':
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(',') if host.strip()]
    if 'localhost' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('localhost')
    if '127.0.0.1' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('127.0.0.1')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party apps
    'rest_framework',
    'corsheaders',
    # Local apps
    'chat',
    'documents',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be as high as possible
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# Media files (Uploaded documents stored locally on PC5)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Max upload limit (15MB)
FILE_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

# CORS Configuration for LAN and local dev
CORS_ALLOW_ALL_ORIGINS = True  # Allows access from any LAN client in on-premise deployment
cors_origins_env = os.getenv('CORS_ALLOWED_ORIGINS', '')
if cors_origins_env:
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in cors_origins_env.split(',') if origin.strip()]

# Ollama and AI Configuration (Strict On-Premise Privacy)
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3:4b')
ALLOW_EXTERNAL_AI = os.getenv('ALLOW_EXTERNAL_AI', 'False').lower() in ('true', '1', 'yes')

# Multi-model layer (registered local models live in chat/model_registry.py)
DEFAULT_CHAT_MODEL = os.getenv('DEFAULT_CHAT_MODEL', 'qwen3')
# Seconds. Generous because switching models on an 8 GB GPU means a reload,
# and Qwen3 spends time "thinking" before it answers.
OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', '300'))

# Server-side logging for the chat/model layer (metadata only, no prompts)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[{asctime}] {levelname} {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'loggers': {
        'chat': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
