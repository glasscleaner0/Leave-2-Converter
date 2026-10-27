"""Process adapter for the independently supplied x360-convert tool."""
from dataclasses import dataclass
from pathlib import Path
import os
import queue
import re
import subprocess
import threading

ACTIONS = {
    'Extract game files': 'extract',
    'Create ISO': 'iso',
    'Create GOD': 'god',
    'Extract DLC': 'extract-dlc',
    'Inspect game package': 'inspect',
    'Verify GOD': 'verify-god',
}
READ_ONLY = {'inspect', 'verify-god'}

@dataclass
class ContainerOptions:
    executable: str
    action: str
    source: str
    output: str = ''
    title: str = ''
    title_id: str = ''

def command(options):
    exe = Path(options.executable).expanduser().resolve()
    source = Path(options.source).expanduser().resolve()
    if not options.executable.strip() or not exe.is_file():
        raise ValueError('Choose x360-convert.exe.')
    if options.action not in ACTIONS:
        raise ValueError('Choose an operation.')
    if not options.source.strip() or not source.exists():
        raise ValueError('Choose an existing input file or extracted game folder.')
    action = ACTIONS[options.action]
    if source.is_dir() and action not in ('iso', 'god'):
        raise ValueError('This operation needs a package or ISO file, not a folder.')
    args = [str(exe), action, str(source)]
    if action not in READ_ONLY:
        if not options.output.strip():
            raise ValueError('Choose a new output path.')
        output = Path(options.output).expanduser().resolve()
        if output.exists():
            raise ValueError('Output already exists. Choose a new file or folder.')
        if not output.parent.is_dir():
            raise ValueError('The output parent folder must already exist.')
        if source.is_dir() and output.is_relative_to(source):
            raise ValueError('Output must be outside the input folder.')
        args.append(str(output))
    if action == 'god':
        if options.title.strip():
            args += ['--title', options.title.strip()]
        if options.title_id.strip():
            value = options.title_id.strip()
            if not re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]{1,8}', value):
                raise ValueError('Title ID must contain up to eight hexadecimal digits.')
            args += ['--title-id', value.lower().removeprefix('0x')]
    return args

def parse_line(stream, line):
    parts = line.rstrip('\r\n').split('\t')
    if len(parts) == 4 and parts[0] == 'progress':
        try:
            done, total = int(parts[2]), int(parts[3])
            if done < 0 or total < 0:
                raise ValueError()
            return 'progress', {'stage': parts[1], 'done': done, 'total': total}
        except ValueError:
            pass
    if parts[0] == 'error':
        return 'error', '\t'.join(parts[1:])
    return 'message', line.rstrip('\r\n')

def run(options, emit, cancelled):
    """Drain both pipes while polling cancellation; no shell or UI calls."""
    args = command(options)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    events = queue.Queue()
    def reader(name, pipe):
        try:
            for line in pipe:
                events.put(parse_line(name, line))
        finally:
            pipe.close()
    readers = [threading.Thread(target=reader, args=(name, pipe), daemon=True)
        for name, pipe in [('stdout', process.stdout), ('stderr', process.stderr)]]
    for thread in readers:
        thread.start()
    stopped = False
    errors = []
    try:
        while process.poll() is None or any(t.is_alive() for t in readers) or not events.empty():
            if cancelled.is_set() and process.poll() is None and not stopped:
                stopped = True
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                except ProcessLookupError:
                    pass
            try:
                kind, data = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if kind == 'error':
                errors.append(data)
            emit(kind, data)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for thread in readers:
            thread.join()
    if stopped:
        return {'status': 'cancelled', 'message': 'Cancelled. An incomplete output may remain; choose a new output before retrying.'}
    if process.returncode:
        raise RuntimeError('\n'.join(errors) or f'x360-convert exited with code {process.returncode}.')
    return {'status': 'complete', 'message': 'Completed successfully.'}
