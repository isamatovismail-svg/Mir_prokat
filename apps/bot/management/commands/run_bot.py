import sys
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.bot.telegram_bot import setup_telegram_application

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Запуск Telegram-бота Mir Prokat в режиме Polling'

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
        if not token:
            self.stdout.write(self.style.ERROR('ОШИБКА: TELEGRAM_BOT_TOKEN не указан в settings.py или .env файле!'))
            self.stdout.write('Укажите токен бота в файле .env:')
            self.stdout.write('TELEGRAM_BOT_TOKEN=123456789:ABCdef...')
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS('Запуск Telegram-бота Mir Prokat...'))
        app = setup_telegram_application()
        if app:
            app.run_polling()
