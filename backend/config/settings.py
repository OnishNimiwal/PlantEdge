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
# Models are defined in chat/model_registry.py (OLLAMA_MODEL is no longer used).
# There is no external/cloud AI support at all (ALLOW_EXTERNAL_AI was removed);
# chat/checks.py warns if either legacy variable is still set.
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
# Private-LAN hosts/IPs/CIDRs Ollama may run on, e.g. "192.168.1.50" or "10.20.0.0/16".
# Loopback is always allowed; public and link-local addresses are always refused.
OLLAMA_ALLOWED_HOSTS = [h.strip() for h in os.getenv('OLLAMA_ALLOWED_HOSTS', '').split(',') if h.strip()]

# Multi-model layer (registered local models live in chat/model_registry.py)
DEFAULT_CHAT_MODEL = os.getenv('DEFAULT_CHAT_MODEL', 'qwen3')
# Seconds. Generous because switching models on an 8 GB GPU means a reload,
# and Qwen3 spends time "thinking" before it answers.
OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', '300'))
# Context window per request. Ollama's default (4096) silently halves longer prompts.
# 8192 keeps each model fully on an 8 GB GPU; 16384 spills qwen3 to CPU.
OLLAMA_NUM_CTX = int(os.getenv('OLLAMA_NUM_CTX', '8192'))
# Qwen3 "thinking": empty = model default (on), "false" = answer directly (faster,
# less step-by-step reasoning), "true" = force on. Only affects thinking-capable models.
_think = os.getenv('OLLAMA_THINK', '').strip().lower()
OLLAMA_THINK = {'true': True, '1': True, 'yes': True, 'false': False, '0': False, 'no': False}.get(_think)

# Images sent to the vision model (backend-enforced; protects the 8 GB GPU)
VISION_MAX_SIDE = int(os.getenv('VISION_MAX_SIDE', '1024'))            # longest side after resize
VISION_MAX_INPUT_PIXELS = int(os.getenv('VISION_MAX_INPUT_PIXELS', str(50_000_000)))  # reject above
MAX_IMAGES_PER_MESSAGE = int(os.getenv('MAX_IMAGES_PER_MESSAGE', '3'))

# Document limits (resource protection; reported to the user when hit)
DOCUMENT_MAX_CHARS = int(os.getenv('DOCUMENT_MAX_CHARS', '50000'))
DOCUMENT_MAX_PDF_PAGES = int(os.getenv('DOCUMENT_MAX_PDF_PAGES', '300'))

# Local OCR (PaddleOCR on CPU; see documents/ocr.py)
OCR_LANG = os.getenv('OCR_LANG', 'en')
OCR_PDF_DPI = int(os.getenv('OCR_PDF_DPI', '200'))
OCR_MAX_PDF_PAGES = int(os.getenv('OCR_MAX_PDF_PAGES', '20'))
OCR_CPU_THREADS = int(os.getenv('OCR_CPU_THREADS', '8'))
# Optional explicit PaddleOCR model names, e.g. PP-OCRv5_mobile_det / en_PP-OCRv5_mobile_rec
# (about 4x faster on CPU, slightly less accurate). Empty = PaddleOCR default for OCR_LANG.
OCR_DET_MODEL = os.getenv('OCR_DET_MODEL', '')
OCR_REC_MODEL = os.getenv('OCR_REC_MODEL', '')

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
        'documents': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
