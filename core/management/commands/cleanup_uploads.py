from django.core.management.base import BaseCommand
from core.storage import cleanup_expired


class Command(BaseCommand):
    help = "Expire abandoned transfers and remove completed/cancelled/expired temporary parts; never delete archived files."

    def handle(self, *args, **options):
        self.stdout.write(f"Removed {cleanup_expired()} temporary parts")
