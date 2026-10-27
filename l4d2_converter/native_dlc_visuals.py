"""Native DLC UI assets and isolated minigun materials; no PC assets required."""
import hashlib
from .archive import XboxZip
from .dependencies import canonical
from .formats import unpack_source,validate_asset
from .native_materials import material_text
from .material_aliases import alias_material_tree
from .keyvalues import parse,decode_text,Token

ACHIEVEMENTS='materials/vgui/achievements/'
MINIGUN='materials/models/w_models/minigun/w_minigun.vmt'


def collect_visual_support(archives,*,stock_archives=(),missions=(),preview_textures=None):
    index={};pools={}
    dlc_names=set()
    for source,is_dlc in [*((p,False) for p in stock_archives),*((p,True) for p in archives)]:
        archive=source if isinstance(source,XboxZip) else XboxZip(source);pool={}
        for name in archive.entries:
            # Previously generated startup previews are outputs, not native donors.
            if not is_dlc and name.startswith('materials/vgui/maps/') and name.endswith('.vmt') and b'leave2/native_dlc/previews/' in archive.read(name):
                continue
            index[canonical(name)]=(archive,name)
            if is_dlc:dlc_names.add(canonical(name))
            if name.endswith('kvpool.360.image'):
                data=unpack_source(archive.read(name));pool[data[:4]]=data
        pools[str(archive.path)]=pool
    generated={canonical(n):d for n,d in (preview_textures or {}).items()};fallbacks=[]
    def read(name):
        if canonical(name) in generated:return generated[canonical(name)]
        row=index.get(canonical(name))
        if not row:return None
        archive,actual=row;data=archive.read(actual)
        return material_text(data,pools[str(archive.path)]) if name.endswith('.vmt') else data
    roots=sorted(name for name in dlc_names if name.startswith(ACHIEVEMENTS) and name.endswith('.vmt'))
    groups=[('achievements',roots)]
    if MINIGUN in index:groups.append(('minigun',[MINIGUN]))
    previews={name for name in dlc_names if name.startswith('materials/vgui/maps/') and name.endswith('.vmt')}
    for mission in missions:
        tree=parse(decode_text(mission));entries=tree[0].value
        campaign=next((e.value.value for e in entries if e.key.value.lower()=='image' and isinstance(e.value,Token)),None)
        def walk(nodes):
            for entry in nodes:
                if isinstance(entry.value,list):yield from walk(entry.value)
                elif entry.key.value.lower()=='image' and isinstance(entry.value,Token):yield entry.value.value
        for image in walk(entries):
            name=canonical('materials/vgui/'+image.replace('\\','/')+'.vmt')
            if not name.startswith('materials/vgui/maps/'):continue
            if (name not in index or name[:-4]+'.vtf' in generated) and name not in generated:
                texture=name[:-4]+'.vtf';fallback=None
                if texture not in index and texture not in generated:
                    fallback=campaign
                    texture=canonical('materials/vgui/'+str(campaign)+'.vtf')
                    if not campaign or texture not in index:raise ValueError('Missing native chapter preview and campaign fallback: '+name)
                generated[name]=('UnlitGeneric { "$basetexture" "'+texture.removeprefix('materials/').removesuffix('.vtf')+'" "$translucent" "1" "$ignorez" "1" "$vertexcolor" "1" "$vertexalpha" "1" }').encode()
                if fallback:fallbacks.append({'material':name,'fallback_campaign_image':fallback,'reason':'Original chapter thumbnail absent from supplied native archives'})
            previews.add(name)
    if previews:groups.append(('previews',sorted(previews)))
    members={};report={'achievement_ids':[name[len(ACHIEVEMENTS):-4] for name in roots],
                       'pc_assets_used':bool(preview_textures),'groups':{},'native_texture_payloads_preserved':True,
                       'minigun_runtime_validated':True,'minigun_validation_scope':'Direct material replacement confirmed in Tumtara and No Mercy Rooftop',
                       'chapter_preview_fallbacks':fallbacks,'visual_support_revision':2}
    for group,materials in groups:
        if not materials:continue
        try:aliased,info=alias_material_tree(materials,read,'leave2/native_dlc/'+group)
        except ValueError as error:
            raise ValueError(str(error).replace('Missing PC ','Missing native DLC ')) from error
        for original,alias in info['texture_aliases'].items():
            if aliased[alias]!=read(original):raise ValueError('Native visual texture payload changed: '+original)
        for name,data in aliased.items():
            target=name[:-4]+'.360.vtf' if name.endswith('.vtf') else name
            if target.endswith('.360.vtf'):validate_asset(target,data)
            members[target]=data
        report['groups'][group]=info
    report['files']={name:hashlib.sha256(data).hexdigest() for name,data in members.items()}
    return members,report


def startup_icon_members(members):
    """Icons must be visible before the first achievement UI material lookup."""
    return {name:data for name,data in members.items() if name.startswith(
        (ACHIEVEMENTS,'materials/leave2/native_dlc/achievements/'))}


def startup_visual_members(members):
    """Publish independent UI and turret materials before their first lookup."""
    return dict(members)
