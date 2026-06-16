from django.core.management.base import BaseCommand

import silk.models
from silk.config import SilkyConfig


class Command(BaseCommand):
    help = "Triggers silk's request garbage collect."

    def add_arguments(self, parser):
        parser.add_argument(
            "-m",
            "--max-requests",
            default=SilkyConfig().SILKY_MAX_RECORDED_REQUESTS,
            type=int,
            help="Maximum number of requests to keep after garbage collection.",
        )
        parser.add_argument(
            "--mode",
            choices=["count", "time", "both"],
            default=SilkyConfig().SILKY_GARBAGE_COLLECT_MODE,
            help="Garbage collection strategy.",
        )
        parser.add_argument(
            "--max-time",
            default=SilkyConfig().SILKY_MAX_RECORDED_TIME,
            type=int,
            help="Maximum age in minutes to keep ('time'/'both' modes).",
        )

    def handle(self, *args, **options):
        if "max_requests" in options:
            max_requests = options["max_requests"]
            SilkyConfig().SILKY_MAX_RECORDED_REQUESTS = max_requests
        if options.get("mode") is not None:
            SilkyConfig().SILKY_GARBAGE_COLLECT_MODE = options["mode"]
        if options.get("max_time") is not None:
            SilkyConfig().SILKY_MAX_RECORDED_TIME = options["max_time"]
        if options["verbosity"] >= 2:
            max_requests = SilkyConfig().SILKY_MAX_RECORDED_REQUESTS
            request_count = silk.models.Request.objects.count()
            self.stdout.write(
                f"Keeping up to {max_requests} of {request_count} requests."
            )
        silk.models.Request.garbage_collect(force=True)
