from django.core.management.base import BaseCommand,CommandError
from api.worker import run_worker


class Command(BaseCommand):
    help='Execute queued REST API jobs serially using the existing management commands.'
    requires_system_checks=[]

    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true',help='Process at most one queued job and exit')
        parser.add_argument('--poll-interval',type=float,default=1)

    def handle(self,*args,**options):
        try:
            run_worker(once=options['once'],poll_interval=options['poll_interval'],output=self.stdout.write)
        except Exception as exc:
            raise CommandError(f'API worker stopped: {exc}') from exc
