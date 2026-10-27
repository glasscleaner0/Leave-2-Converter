"""Read declared sound-event waves and extend existing Xbox resource lists.

Event selection is explicit: this helper does not guess that every sound in
an addon is needed by every map. Resource lists request preparation; they do
not guarantee a resident-memory budget or fix missing engine features.
"""
from .dependencies import reference_name, canonical
from .keyvalues import parse, decode_text

SOUND_PREFIXES = '*#@><^)}$!?('


def event_waves(data):
    result = {}

    def visit(entries):
        for entry in entries:
            if isinstance(entry.value, list):
                yield from visit(entry.value)
            elif entry.key.value.lower() == 'wave':
                value = entry.value.value.lstrip(SOUND_PREFIXES).replace('\\', '/').lower()
                if value.endswith('.wav'):
                    yield reference_name(value if value.startswith('sound/') else 'sound/' + value, 'sound')

    for entry in parse(decode_text(data)):
        if isinstance(entry.value, list):
            # Sound script entries are not a single KeyValues root. Preserve
            # declaration order for duplicate events instead of silently merging.
            result[entry.key.value.lower()] = set(visit(entry.value))
    return result


def extend_sound_list(data, waves):
    text = decode_text(data)
    # Resource lists are standalone quoted strings, not key/value pairs.
    from .keyvalues import tokens
    existing = set()
    for token in tokens(text):
        if token.kind == 'brace':
            raise ValueError('Unexpected block in Xbox resource list')
        existing.add(canonical(reference_name(token.value)))
    requested = set()
    for name in waves:
        name = canonical(reference_name(name, 'sound'))
        if not name.startswith('sound/') or not name.endswith('.wav'):
            raise ValueError('Sound prefetch path must be a WAV under sound/')
        requested.add(name)
    added = sorted(requested - existing)
    if not added:
        return text.encode('cp1252'), []
    if text and not text.endswith(('\r', '\n')):
        text += '\r\n'
    text += ''.join('"' + name.replace('/', '\\') + '"\r\n' for name in added)
    return text.encode('cp1252'), added
