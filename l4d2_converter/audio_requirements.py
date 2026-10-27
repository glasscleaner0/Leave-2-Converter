"""Report audio registration/availability gaps without inventing sound assets."""
from .dependencies import canonical
from .sound_prefetch import event_waves


def audit_audio(members,native_names=()):
    available={canonical(n) for n in members}|{canonical(n) for n in native_names}
    audio=sorted(canonical(n) for n in members if canonical(n).startswith('sound/') and canonical(n).endswith('.wav'))
    scripts=[n for n in members if n.endswith('.txt') and
             (n.startswith('scripts/game_sounds') and not n.endswith('manifest.txt') or
              n.startswith('maps/') and n.endswith('_level_sounds.txt'))]
    missing=set();dynamic=set();definitions={};issues=[]
    for name in sorted(scripts):
        try:events=event_waves(members[name])
        except ValueError as error:
            issues.append({'path':name,'reason':str(error)});continue
        definitions[name]=len(events)
        for waves in events.values():
            for wave in waves:
                if '$' in wave:dynamic.add(wave)
                elif canonical(wave) not in available:missing.add(wave)
    music=[n for n in audio if n.startswith('sound/music/')]
    scenes=sorted(n for n in members if n.startswith('scenes/'))
    needs=bool(audio or scripts or scenes)
    note=('Use the current Loader Patch (audio compatibility revision 1) for late music loading and L4D1 $survivor voice selection. '
          'These runtime fixes do not supply missing WAVs, register arbitrary custom scenes, or add newer engine APIs.')
    warnings=[]
    if needs:warnings.append(note)
    if missing:warnings.append(f'Audio definitions reference {len(missing)} WAV paths absent from this output and the selected console references; see audio_compatibility.missing_declared_waves. No audio substitutes were added.')
    if issues:warnings.append('Some sound definitions could not be audited; see audio_compatibility.definition_audit_issues.')
    return {'loader_audio_revision_recommended':1 if needs else None,'converted_wave_files':len(audio),
            'packaged_music_files':music,'sound_definition_events':definitions,
            'missing_declared_waves':sorted(missing),'dynamic_survivor_wave_paths':sorted(dynamic),
            'scene_files':scenes,'definition_audit_issues':issues,'audio_rewritten_by_audit':False,
            'runtime_tested':False,'note':note if needs else 'No packaged audio definitions or waves detected.'},warnings
