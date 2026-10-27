"""Independent verifier for observed L4D NAV16/14 and NAV15/13 layouts."""
import struct

def transcode(b):
 endian='>' if b[:4]==bytes.fromhex('feedface') else '<';other='<' if endian=='>' else '>'
 pos=0;out=bytearray();ids=set();refs=[];connections=[];ladderrefs=[];hidecount=0;visiblecount=0
 def raw(n):
  nonlocal pos
  assert 0<=n<=len(b)-pos,(pos,n,len(b));a=b[pos:pos+n];pos+=n;out.extend(a);return a
 def number(width=4):
  nonlocal pos
  assert width in (1,2,4) and pos+width<=len(b),(pos,width)
  a=b[pos:pos+width];pos+=width;out.extend(a[::-1]);return int.from_bytes(a,'big' if endian=='>' else 'little')
 def many(n,width=4):
  assert 0<=n<=1000000,(pos,n)
  return [number(width) for _ in range(n)]
 def count(width=4):
  n=number(width);assert n<=100000,(pos,n);return n
 if number()!=0xfeedface:raise ValueError('Invalid NAV signature')
 version=number();subversion=number()
 if (version,subversion) not in ((16,14),(15,13)):
  raise ValueError(f'Unsupported NAV version {version}/{subversion}; supported layouts: 16/14 and 15/13')
 bspsize=number();analyzed=number(1);assert analyzed in (0,1)
 places=[]
 for _ in range(count(2)):places.append(raw(count(2)).rstrip(b'\0').decode())
 assert number(1) in (0,1)
 population=raw(b.index(0,pos)-pos+1).rstrip(b'\0').decode()
 fog=[]
 for _ in range(count(2)):fog.append(raw(count(2)).rstrip(b'\0').decode())
 areas=count();assert areas>0
 for _ in range(areas):
  aid=number();assert aid and aid not in ids;ids.add(aid);number();many(8)
  for direction in range(4):connections.extend(many(count()))
  n=count(1);hidecount+=n
  for _ in range(n):many(4);number(1)
  for _ in range(count()):
   refs.append(number());assert number(1)<4;refs.append(number());assert number(1)<4
   for _ in range(count(1)):number();number(1)
  place=number(2);assert place<=len(places)
  for _ in range(2):ladderrefs.extend(many(count()))
  many(6);number();fogid=number(2);assert fogid<=len(fog)
  n=count();visiblecount+=n
  for _ in range(n):refs.append(number());number(1)
  refs.append(number())
 ladders=count();ladderids=set()
 for _ in range(ladders):
  lid=number();assert lid and lid not in ladderids;ladderids.add(lid);many(8);assert number()<4;refs.extend(many(5))
 number() # nav_max_view_distance float
 assert pos==len(b),(pos,len(b),len(b)-pos)
 missing=sorted(set(refs)-ids-{0,0xffffffff});missing_ladders=sorted(set(ladderrefs)-ladderids-{0});missing_connections=sorted(set(connections)-ids-{0})
 assert not missing_connections and not missing_ladders,(missing_connections[:10],missing_ladders)
 return bytes(out),dict(bytes=len(b),endian=endian,version=version,subversion=subversion,areas=areas,ladders=ladders,hiding_spots=hidecount,visible_connections=visiblecount,population=population,places=places,fog_places=fog,bsp_size=bspsize,all_movement_connections_resolve=True,unresolved_visibility_or_encounter_ids=missing)
