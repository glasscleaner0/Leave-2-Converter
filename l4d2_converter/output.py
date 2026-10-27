"""Reuse recognized build directories without deleting their prior contents."""
from datetime import datetime, timezone
from pathlib import Path
import json
import stat


def prepare_output(options):
    requested = Path(options.output).absolute()
    # Check before resolve(): a junction/symlink must never redirect a move.
    for component in (requested, *requested.parents):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise ValueError('Output path must not pass through a symlink or junction')
    output = requested.resolve()
    if output == output.parent:
        raise ValueError('A drive root cannot be an output folder')
    from .app_paths import application_home
    protected = [application_home()]
    protected.extend(Path(value).resolve() for key in ('input','sdk_bin','runtime_bin','xbox_game','pc_game','xbox_assets','audio_decoder')
                     if (value := getattr(options, key, '')))
    protected.extend(Path(value).resolve() for value in getattr(options,'additional_inputs',()))
    for source in protected:
        if output == source or output in source.parents or source in output.parents:
            raise ValueError('Output must be separate from the input, tools, converter source, and game reference folders')
    if output.exists() and not output.is_dir():
        raise ValueError('Output path is a file, not a folder')
    backup = None
    if output.exists() and any(output.iterdir()):
        if not options.overwrite:
            raise ValueError('Output folder is not empty. Enable Overwrite existing converter output, or choose an empty folder.')
        try:
            previous = json.loads((output/'report.json').read_text(encoding='utf8'))
            previous_path = Path(previous['options']['output']).resolve()
            recognized = (previous_path == output and isinstance(previous['version'], str)
                          and previous['status'] in ('failed','cancelled','partial','converted-awaiting-console-test')
                          and isinstance(previous['jobs'], list) and isinstance(previous['failures'], list))
        except (OSError, ValueError, KeyError, TypeError):
            recognized = False
        if not recognized:
            raise ValueError('Overwrite is allowed only for a finished or failed converter build with its original report.json')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = output.with_name(output.name + '.previous-' + stamp)
        # Both resolved absolute paths must remain siblings at the user-selected
        # location. Rename the directory as one unit; never traverse its contents.
        if backup.resolve().parent != output.parent or backup.exists():
            raise ValueError('Cannot create a safe previous-build backup beside the output')
        output.rename(backup)
    output.mkdir(parents=True, exist_ok=True)
    return output, backup
