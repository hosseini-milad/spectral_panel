"""Run the canonical layer-1 chunk workflow for every chunk of a day."""
import re
import time
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from mongoengine import get_db

DAY_SOURCE_RE = re.compile(r"^clustered-day-(\d{4}-\d{2}-\d{2})$")


class Command(BaseCommand):
    help = 'Automatically run/resume all day chunks through the complete general-action workflow.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--source-file', required=True, help='clustered-day-YYYY-MM-DD (without a chunk suffix)')
        parser.add_argument('--sample-per-day', type=int, default=20000)
        parser.add_argument('--batch-size', type=int, default=2000)
        parser.add_argument('--neighbors', type=int, default=12)
        parser.add_argument('--threshold', type=float, default=0.995)
        parser.add_argument('--degree-cap', type=int, default=20)
        parser.add_argument('--ratio', type=float, default=0.10)
        parser.add_argument('--start-chunk', type=int, default=0, help='Optional first chunk; normally all chunks run automatically.')
        parser.add_argument('--max-chunks', type=int, default=None, help='Optional chunk count; normally all remaining chunks run.')
        parser.add_argument('--limit', type=int, default=None, help='Maximum chunks to process, starting at --start-chunk (default 0); equivalent to --max-chunks.')
        parser.add_argument('--skip-eigen', action='store_true')

    def handle(self, *args, **options):
        match = DAY_SOURCE_RE.fullmatch(options['source_file'].strip())
        if not match:
            raise CommandError('--source-file must be clustered-day-YYYY-MM-DD, without -chunk-N.')
        day = match.group(1)
        try:
            datetime.strptime(day, '%Y-%m-%d')
        except ValueError as exc:
            raise CommandError('Invalid calendar date in --source-file.') from exc
        chunk_size = options['sample_per_day']
        start = options['start_chunk']
        if options['limit'] is not None and options['max_chunks'] is not None and options['limit'] != options['max_chunks']:
            raise CommandError('--limit and --max-chunks must agree when both are provided.')
        limit = options['limit'] if options['limit'] is not None else options['max_chunks']
        if min(chunk_size, options['batch_size'], options['neighbors'], options['degree_cap']) < 1:
            raise CommandError('Chunk size, batch size, neighbors and degree cap must be positive.')
        if start < 0 or limit is not None and limit < 1:
            raise CommandError('--start-chunk must be >= 0 and --limit/--max-chunks must be positive.')
        if not 0 < options['ratio'] < 1 or not -1 <= options['threshold'] <= 1:
            raise CommandError('Require 0 < ratio < 1 and -1 <= threshold <= 1.')
        db = get_db()
        total = db.security_data.count_documents({'source_day': day})
        if not total:
            raise CommandError(f'No raw records found for source_day={day!r}. Ingest the day first.')
        count = (total + chunk_size - 1) // chunk_size
        if start >= count:
            raise CommandError(f'start-chunk={start} is outside valid range 0..{count - 1}.')
        stop = count if limit is None else min(count, start + limit)
        self.stdout.write(self.style.NOTICE(
            f'[HYPER] day={day}; raw_records={total:,}; chunk_size={chunk_size:,}; '
            f'total_chunks={count}; run={start}..{stop - 1}; each chunk runs all 10 layer-1 stages'
        ))
        forwarded = {name: options[name] for name in (
            'sample_per_day', 'batch_size', 'neighbors', 'threshold', 'degree_cap', 'ratio', 'skip_eigen',
        )}
        began = time.perf_counter()
        completed = []
        for index in range(start, stop):
            source = f'clustered-day-{day}-chunk-{index}'
            expected = min(chunk_size, total - index * chunk_size)
            self.stdout.write(self.style.NOTICE(
                f'[HYPER] CHUNK {index - start + 1}/{stop - start}: {source}; raw_chunk={expected:,}'
            ))
            try:
                # One implementation owns stage ordering, resume checks and reports.
                call_command('general-action', source_file=source, stdout=self.stdout,
                             stderr=self.stderr, **forwarded)
            except Exception as exc:
                raise CommandError(
                    f'Hyper pipeline stopped at chunk {index}; completed this run={completed}; '
                    f'{len(completed)}/{stop - start} chunks completed in {time.perf_counter() - began:.1f}s. '
                    f'Later chunks were not run. Resolve the cause and retry the same day command: {exc}'
                ) from exc
            completed.append(index)
            self.stdout.write(self.style.SUCCESS(f'[HYPER] COMPLETED {source}'))
        self.stdout.write(self.style.SUCCESS(
            f'[HYPER] ALL REQUESTED CHUNKS FINISHED; day={day}; range={start}..{stop - 1}; '
            f'completed={len(completed)}; elapsed={time.perf_counter() - began:.1f}s.'
        ))
