import json
from pathlib import Path
from django.core.management.base import BaseCommand
from analytics.services import report

class Command(BaseCommand):
    help = 'Compute a repeatable productivity report from local records.'
    def add_arguments(self, parser):
        parser.add_argument('--output', help='Optional JSON output path; overwritten on repeated runs.')
    def handle(self, *args, **options):
        content = json.dumps(report(), indent=2)
        if options['output']:
            path = Path(options['output'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.stdout.write(content)
