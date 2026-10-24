from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Create a default superuser for local development. Credentials are read "
        "from .env (ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD)."
    )

    def handle(self, *args, **options):
        username = config("ADMIN_USERNAME", default="admin")
        email = config("ADMIN_EMAIL", default="admin@example.com")
        password = config("ADMIN_PASSWORD", default="admin")

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"Superuser '{username}' already exists."))
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created."))
