"""Authoritative circular-orbit/waypoint proxy on the persistent scenario clock.

Inventory coordinates stay intact. This is deterministic kinematics, not SGP4/RF.
"""
import math
from datetime import datetime
from types import SimpleNamespace
from backend.models.network import Node
from backend.models.network_learning import NetworkClock

VERSION='shared-kinematics-v1'
R=6371.

def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(a):
    length=math.sqrt(sum(x*x for x in a))
    return tuple(x/length for x in a) if length>1e-12 else (1.,0.,0.)

def position_at(node,seconds):
    if node.type not in {'SPACE','AIR','SEA'} or getattr(node,'platform',None)=='RESEARCH_STATIC':
        return dict(lat=node.lat,lng=node.lng,alt=node.alt)
    lat,lng=math.radians(node.lat),math.radians(node.lng)
    radial=(math.cos(lat)*math.cos(lng),math.sin(lat),-math.cos(lat)*math.sin(lng))
    inclination=getattr(node,'orbit_inclination_deg',None)
    inclination=math.radians(53 if inclination is None else inclination)
    raan=getattr(node,'orbit_raan_deg',None)
    raan=math.radians(raan) if raan is not None else max(0,(getattr(node,'orbit_plane',None) or 1)-1)*math.pi/3
    epoch=datetime.fromisoformat((getattr(node,'epoch_utc',None) or '2026-10-11T00:00:00+00:00').replace('Z','+00:00')).timestamp()
    jd=epoch/86400+2440587.5;c=(jd-2451545)/36525
    gmst=math.radians((280.46061837+360.98564736629*(jd-2451545)+.000387933*c*c-c**3/38710000)%360)
    nx,ny=math.sin(inclination)*math.sin(raan),-math.sin(inclination)*math.cos(raan)
    normal=(math.cos(gmst)*nx+math.sin(gmst)*ny,math.cos(inclination),math.sin(gmst)*nx-math.cos(gmst)*ny)
    tangent=cross(normal,radial)
    if sum(x*x for x in tangent)<1e-12:tangent=cross((0,1,0),radial)
    tangent=unit(tangent)
    if node.type=='SPACE':
        period=2*math.pi*math.sqrt((R+max(100,node.alt))**3/398600.4418)
        phase=seconds*2*math.pi/period
        p=tuple(a*math.cos(phase)+b*math.sin(phase) for a,b in zip(radial,tangent))
        angle=-seconds*2*math.pi/86164.0905
        p=(p[0]*math.cos(angle)+p[2]*math.sin(angle),p[1],-p[0]*math.sin(angle)+p[2]*math.cos(angle))
    else:
        radius,speed=(120000,8) if node.type=='SEA' else (20000,15)
        phase=seconds*speed/radius;span=min(.035,radius/(R*1000))
        side=unit(cross(radial,tangent))
        p=unit(tuple(a+span*((math.cos(phase)-1)*b+math.sin(phase)*d) for a,b,d in zip(radial,tangent,side)))
    return dict(lat=math.degrees(math.asin(max(-1,min(1,p[1])))),lng=math.degrees(math.atan2(-p[2],p[0])),alt=node.alt)

def moving_node(node,seconds):
    fields={column.name:getattr(node,column.name) for column in Node.__table__.columns}
    return SimpleNamespace(**{**fields,**position_at(node,seconds)})

def poses(db,scenario_id,seconds=None):
    clock=db.get(NetworkClock,scenario_id)
    now=seconds if seconds is not None else clock.sim_time_s if clock else 0.
    return {n.id:moving_node(n,now) for n in db.query(Node).filter_by(scenario_id=scenario_id)}

def snapshot(db,scenario_id):
    clock=db.get(NetworkClock,scenario_id);now=clock.sim_time_s if clock else 0.
    nodes=db.query(Node).filter_by(scenario_id=scenario_id).all()
    from backend.models.network import NetworkLink
    from backend.services.service_routing_service import build_frame
    frame=build_frame(nodes,db.query(NetworkLink).all(),now)
    adjacent={key:[] for key in frame['nodes']}
    for edge in frame['edges'].values():adjacent[edge['source']].append(edge)
    display={}
    for edges in adjacent.values():
        for edge in sorted(edges,key=lambda e:e['features']['distance_km'])[:2]:
            display[str(edge['link_id'])]=dict(id=edge['link_id'],source=edge['source'],target=edge['target'],estimated=edge['estimated'])
    return dict(version=VERSION,scenario_id=scenario_id,clock_s=now,horizon_s=2,
        contacts=list(display.values()),total_contacts=len(frame['edges'])//2,
        nodes=[dict(id=n.id,**position_at(n,now),next=position_at(n,now+2)) for n in nodes])
