"""Check and migrate an isolated SQLite snapshot before replacing the service."""

from django.core.management import BaseCommand, CommandError, call_command
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.loader import MigrationLoader


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        loader = MigrationLoader(connections[DEFAULT_DB_ALIAS], replace_migrations=False)
        known = set(loader.disk_migrations)
        for migration in loader.disk_migrations.values():
            known.update(migration.replaces)
        missing = sorted(key for key in loader.applied_migrations if key[0] == "management" and key not in known)
        if missing:
            names = ", ".join(migration for _, migration in missing)
            raise CommandError(f"This release cannot preserve applied migrations: {names}")
        call_command("migrate", interactive=False)
