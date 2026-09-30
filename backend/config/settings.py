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
    'monitoring',
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
        # Wait for a lock instead of failing when the document worker and a request write at once.
        'OPTIONS': {'timeout': 20},
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
# Default is OFF for speed (39 s -> 3 s on a simple question); users can turn it on per
# message with "Think deeper" (request field `think: true`).
_think = os.getenv('OLLAMA_THINK', 'false').strip().lower()
OLLAMA_THINK = {'true': True, '1': True, 'yes': True, 'false': False, '0': False, 'no': False}.get(_think)
# How long Ollama keeps the last-used model in GPU memory (Ollama's default is 5m).
OLLAMA_KEEP_ALIVE = os.getenv('OLLAMA_KEEP_ALIVE', '30m')
# Load a model ahead of the request (page open, image attached, model picked) when idle.
OLLAMA_WARMUP = os.getenv('OLLAMA_WARMUP', 'True').lower() in ('true', '1', 'yes')

# Reliability instructions (chat/reliability.py) added to every model's system message.
# Reduces unsupported claims; it cannot eliminate hallucinations.
RELIABILITY_INSTRUCTIONS = os.getenv('RELIABILITY_INSTRUCTIONS', 'True').lower() in ('true', '1', 'yes')

# Formatting guidance sent as the system message in General Chat (empty = none).
# Models usually follow it, but formatting cannot be guaranteed.
CHAT_SYSTEM_PROMPT = os.getenv('CHAT_SYSTEM_PROMPT', (
    "You are MRPL Local AI, an on-premise assistant for an industrial company. "
    "Format answers in GitHub-flavored Markdown: short paragraphs, headings and lists where "
    "they help, real Markdown tables for tabular data (never inside code blocks), and fenced "
    "code blocks with a language tag only for actual code."
))

# Conversation context (chat/context.py): earlier messages sent with each request, and how
# many recent messages an earlier image stays available for follow-up questions.
CONTEXT_MAX_MESSAGES = int(os.getenv('CONTEXT_MAX_MESSAGES', '12'))
CONTEXT_IMAGE_TURNS = int(os.getenv('CONTEXT_IMAGE_TURNS', '8'))

# Images sent to the vision model (backend-enforced; protects the 8 GB GPU)
VISION_MAX_SIDE = int(os.getenv('VISION_MAX_SIDE', '1024'))            # longest side after resize
VISION_MAX_INPUT_PIXELS = int(os.getenv('VISION_MAX_INPUT_PIXELS', str(50_000_000)))  # reject above
MAX_IMAGES_PER_MESSAGE = int(os.getenv('MAX_IMAGES_PER_MESSAGE', '3'))
# PDF pages the vision model may see per question ("pages 2-3"); pages are never all sent at once.
VISION_MAX_PDF_PAGES = int(os.getenv('VISION_MAX_PDF_PAGES', '2'))
# Image + coding request: vision model describes the image, then Coder writes the code (two models).
VISION_CODING_CHAIN = os.getenv('VISION_CODING_CHAIN', 'True').lower() in ('true', '1', 'yes')
# One model request at a time on the GPU (8 GB): further requests wait up to OLLAMA_QUEUE_TIMEOUT s.
OLLAMA_MAX_CONCURRENT = int(os.getenv('OLLAMA_MAX_CONCURRENT', '1'))
OLLAMA_QUEUE_TIMEOUT = int(os.getenv('OLLAMA_QUEUE_TIMEOUT', '180'))
# "Describe all pages": pages analysed one batch after another, up to this many.
VISION_OVERVIEW_MAX_PAGES = int(os.getenv('VISION_OVERVIEW_MAX_PAGES', '6'))

# Document limits (resource protection; reported to the user when hit)
DOCUMENT_MAX_CHARS = int(os.getenv('DOCUMENT_MAX_CHARS', '50000'))
DOCUMENT_MAX_PDF_PAGES = int(os.getenv('DOCUMENT_MAX_PDF_PAGES', '300'))
# Extract text / run OCR in a background worker so uploads return immediately.
DOCUMENT_ASYNC_PROCESSING = os.getenv('DOCUMENT_ASYNC_PROCESSING', 'True').lower() in ('true', '1', 'yes')

# Local OCR (PaddleOCR on CPU; see documents/ocr.py and samples/ocr_benchmark.py)
def _env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('true', '1', 'yes')

OCR_LANG = os.getenv('OCR_LANG', 'en')
# Languages users may choose per upload (PaddleOCR codes: en, hi, mr, ka, ta, te, ml, ch, latin).
# Each extra language downloads its own recognition model once, then runs offline.
OCR_ALLOWED_LANGS = [l.strip() for l in os.getenv('OCR_ALLOWED_LANGS', OCR_LANG).split(',') if l.strip()]
# mobile = default (~6 s/page on CPU, same accuracy as server on the benchmark scans);
# server = PaddleOCR's larger models (~20 s/page). Non-English languages always use their own models.
OCR_MODEL_PROFILE = os.getenv('OCR_MODEL_PROFILE', 'mobile')
# Optional preprocessing models (see samples/ocr_benchmark.py). Page-orientation correction
# is on: it fixed 90/180-degree rotated scans (accuracy 0.15 -> 1.00) at ~no speed cost.
# Text-line orientation did not help; unwarping targets photographed curved pages.
OCR_USE_DOC_ORIENTATION = _env_bool('OCR_USE_DOC_ORIENTATION', True)
OCR_USE_TEXTLINE_ORIENTATION = _env_bool('OCR_USE_TEXTLINE_ORIENTATION')
OCR_USE_UNWARPING = _env_bool('OCR_USE_UNWARPING')
OCR_PDF_DPI = int(os.getenv('OCR_PDF_DPI', '200'))
OCR_MAX_PDF_PAGES = int(os.getenv('OCR_MAX_PDF_PAGES', '20'))
OCR_CPU_THREADS = int(os.getenv('OCR_CPU_THREADS', '8'))
# Low-confidence OCR pages (handwriting, poor scans) are re-read by the local vision model.
OCR_VISION_FALLBACK = _env_bool('OCR_VISION_FALLBACK', True)
OCR_VISION_FALLBACK_BELOW = float(os.getenv('OCR_VISION_FALLBACK_BELOW', '0.80'))
# Free the OCR engine (~0.5-1 GB RAM) after this many idle seconds (0 = keep loaded).
OCR_IDLE_UNLOAD_SECONDS = int(os.getenv('OCR_IDLE_UNLOAD_SECONDS', '600'))
# Optional explicit PaddleOCR model names (override OCR_MODEL_PROFILE). Empty = profile default.
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
        'monitoring': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
