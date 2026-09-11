import json
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.lines import Line2D

HERE=Path(__file__).resolve().parent
BASE=json.loads((HERE/'basemap.bng.json').read_text())
FEAT={f['id']:f for f in json.loads((HERE/'features.bng.json').read_text())['features']}
PROP=json.loads((HERE/'museum_proposal.bng.json').read_text())
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
COLORS={'R1':'#163f6b','R2':'#087a72','R3':'#ae6339','R4':'#765596','R5':'#8a8a8a'}

def basemap(ax,extent):
    for r in BASE['roads']:
        pts=r['pts']; ax.plot([p[0] for p in pts],[p[1] for p in pts],color='#d3d3d3',lw=1.3 if r['cls'] in ['primary','secondary'] else .45,zorder=0)
    for b in BASE['buildings']:
        for ring in b['rings']:
            if not ring['hole']: ax.add_patch(Polygon(ring['pts'],facecolor='#dedede',edgecolor='#bcbcbc',lw=.2,zorder=1))
    for a in BASE['aeroways']:
        p=a['pts']; kind=a['tags'].get('aeroway',a['tags'].get('disused:aeroway'))
        if not p: continue
        if kind in ['apron','aerodrome'] and p[0]==p[-1]:
            ax.add_patch(Polygon(p,facecolor='#efefef' if kind=='apron' else 'none',edgecolor='#b9b9b9',lw=.6,zorder=0))
        else:
            ax.plot([v[0] for v in p],[v[1] for v in p],color='#b7b7b7',lw=5 if kind=='runway' else 1,zorder=1)
    ax.set_xlim(extent[0],extent[2]);ax.set_ylim(extent[1],extent[3]);ax.set_aspect('equal')
    ax.ticklabel_format(useOffset=False,style='plain');ax.tick_params(labelsize=8)
    ax.set_xlabel('British National Grid easting (m)');ax.set_ylabel('Northing (m)')
    ax.grid(alpha=.15,zorder=-1)
    x=extent[0]+120;y=extent[1]+100
    ax.plot([x,x+500],[y,y],color='black',lw=2);ax.text(x+250,y+40,'500 m',ha='center',fontsize=9)
    ax.annotate('N',xy=(extent[2]-150,extent[3]-150),xytext=(extent[2]-150,extent[3]-400),arrowprops={'arrowstyle':'->','color':'black'},ha='center',fontsize=12)

def finish(fig,name):
    fig.savefig(HERE/(name+'.png'),dpi=160,facecolor='white')
    fig.savefig(HERE/(name+'.svg'),facecolor='white')
    plt.close(fig)

fig=plt.figure(figsize=(15,10));ax=fig.add_axes([.065,.14,.65,.76]);side=fig.add_axes([.76,.14,.22,.76]);side.axis('off')
basemap(ax,[631350,164900,635050,167650])
fig.text(.065,.955,'Manston museum: proposed landscape plan',fontsize=21)
fig.text(.065,.92,'Present mapping with selected historical restorations. Paths and visitor gates are proposals.',fontsize=11)
for r in PROP['routes']:
    p=r['points'];ax.plot([v[0] for v in p],[v[1] for v in p],color=COLORS[r['id']],lw=2,ls='--' if r['id']=='R5' else '-',zorder=4)
entries=[('A','Museum gateway',[633315,166510]),('B','RAF tower / Battle HQ',[633540,166590]),('C','Erecting shops / railway',[632980,166560]),('D','Surviving fighter pen',[633060,166340]),('E','T2 aircraft hall',[632880,166170]),('F','Civil tower',[633460,165820]),('G','War Flight / chalk shelter',[634010,166230]),('H','FIDO interpretation',[634460,165220]),('I','Alland Grange hangar',[632310,166470]),('J','Cheeseman hangar',[632410,166740]),('K','Unfinished northern hangars',[634070,167340]),('L','The Loop / Hangar No.4',[631810,166580])]
for label,name,pt in entries:
    ax.scatter(*pt,s=160,color='white',edgecolors='black',zorder=5)
    ax.text(*pt,label,ha='center',va='center',fontsize=9,weight='bold',zorder=6)
for gate in PROP['gates']:
    if gate['id']=='G1':
        ax.annotate('G1',gate['bng'],xytext=(8,-16),textcoords='offset points',fontsize=8,weight='bold')
    else:
        ax.scatter(*gate['bng'],marker='D',s=35,color='black',zorder=7)
        ax.annotate(gate['id'],gate['bng'],xytext=(7,7),textcoords='offset points',fontsize=8,weight='bold',zorder=7)
side.text(0,1,'PLACES',fontsize=11,weight='bold',va='top')
for i,(label,name,pt) in enumerate(entries):side.text(0,.95-i*.038,f'{label}  {name}',fontsize=10,va='top')
side.text(0,.44,'PROPOSED ROUTES',fontsize=11,weight='bold')
for i,r in enumerate(PROP['routes']):
    side.text(0,.39-i*.068,r['id']+'  '+r['name'],color=COLORS[r['id']],fontsize=9,wrap=True)
    side.text(0,.365-i*.068,f"{r['length_m']/1000:.2f} km " + ('loop' if r['closed_loop'] else 'one-way branch'),fontsize=9)
fig.text(.065,.082,'G1-G4: proposed entrances (roles in report). Routes still require terrain, parcel and building-collision checks.',fontsize=10)
fig.text(.065,.058,'Base: OpenStreetMap contributors (ODbL), existing Thanet survey products and fresh aeroway supplement; heritage: Kent HER.',fontsize=9)
fig.text(.065,.035,'This is a counterfactual museum plan for the explorer, not a map of current public access. Research: 11 September 2026.',fontsize=9)
finish(fig,'museum_masterplan')

fig=plt.figure(figsize=(15,10));ax=fig.add_axes([.065,.14,.64,.76]);side=fig.add_axes([.745,.14,.24,.76]);side.axis('off')
basemap(ax,[631500,164800,635000,167650])
fig.text(.065,.955,'Manston: below-ground evidence',fontsize=21)
fig.text(.065,.92,'Separate structures and groups. No surveyed cross-site pedestrian tunnel network has been established.',fontsize=11)
ids=['MKE92406','MKE92407','MKE97296','MKE125405','MKE90888','MKE98027','MKE125197','MKE125196','MKE125195','MKE125191','MKE125192','MKE125193','MKE125389','MKE125439','MKE104167','MKE125138','MKE97293','MKE98021']
for i,ident in enumerate(ids,1):
    f=FEAT[ident];color='#735399' if f['layer']=='sunken' else '#a76835' if f['layer'] in ['surface_services','surface','reported_subsurface'] else '#176875'
    ax.scatter(*f['anchor_bng'],s=130,color='white',edgecolors=color,zorder=4)
    ax.text(*f['anchor_bng'],str(i),ha='center',va='center',fontsize=8,color=color,zorder=5)
    side.text(0,1-(i-1)*.049,f'{i:02}  {f["name"]}',va='top',fontsize=9,color=color)
side.text(0,.075,'Circles are catalogue anchors.\nThey are not portals or footprints.\nGroup records may contain many shelters.',fontsize=9,va='top')
fig.text(.065,.083,'FIDO pipes and southern service trenches are buried infrastructure, not human passageways. Their full routes are not plotted here.',fontsize=10)
fig.text(.065,.058,'Coordinates: Kent HER representative points. No ground depth, tunnel bearing or portal coordinates are inferred from these markers.',fontsize=9)
fig.text(.065,.035,'Base: OpenStreetMap contributors / Thanet project. Record dates and survival conflicts are retained in features.bng.json.',fontsize=9)
finish(fig,'subsurface_evidence')

fig,axs=plt.subplots(3,1,figsize=(12,10));fig.subplots_adjust(top=.88,hspace=.72,bottom=.07)
fig.suptitle('Proposed interior treatment: evidence and reconstruction',fontsize=19,y=.96)
fig.text(.065,.91,'Concept diagrams only. No measured floorplan, burial depth or surveyed portal position is implied.',fontsize=11)
for a in axs:a.set_xlim(0,12);a.set_ylim(0,3);a.axis('off')
a=axs[0];a.set_title('Chalk shelter: two-ended passage; authentic scale requires separate access treatment',loc='left',fontsize=12)
a.plot([1,10],[1,1],color='#176875',lw=2);a.plot([1,10],[2,2],color='#176875',lw=2)
a.annotate('',xy=(9.5,1.5),xytext=(1.5,1.5),arrowprops={'arrowstyle':'<->','color':'#176875'})
a.text(.4,1.5,'A',ha='center');a.text(10.6,1.5,'B',ha='center')
a.text(5.5,2.35,'Length and alignment unknown; A/B are schematic historic ends',ha='center',fontsize=10)
a.text(5.5,.45,'Recorded width: 1.3 m. Exact portals, steps, depth below ground and clearance require the KURG survey.',ha='center',fontsize=10)
a=axs[1];a.set_title('Semi-sunken hangar: open ramp into a chalk excavation',loc='left',fontsize=12)
a.plot([.6,2,4,9,9,11.4],[2,2,.6,.6,2,2],color='#765596',lw=2)
a.plot([4,6.5,9],[2.1,2.7,2.1],color='#765596',lw=1.5,ls='--');a.plot([4,4],[.6,2.1],color='#765596',ls='--');a.plot([9,9],[.6,2.1],color='#765596',ls='--')
a.text(1.1,2.3,'Ground',fontsize=10);a.text(2.4,1.25,'Ramp',rotation=-28,fontsize=10)
a.text(6.5,.16,'Roof/frame shown as a reconstruction concept; no earth-covered roof.',ha='center',fontsize=10)
a=axs[2];a.set_title('Battle HQ: recorded relationships, not a recovered plan',loc='left',fontsize=12)
for x,y,w,h,label in [(2,1,4,1,'Main interior'),(7,1,3,1,'Extra room'),(3,2.4,2,.5,'Cupola')]:
    a.add_patch(plt.Rectangle((x,y),w,h,fill=False,color='#176875',lw=1.5));a.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=10)
a.annotate('Entry',xy=(2,1.5),xytext=(.5,1.5),arrowprops={'arrowstyle':'->'})
a.plot([6,7],[1.5,1.5],ls='--',color='#176875');a.annotate('',xy=(4,2.4),xytext=(4,2),arrowprops={'arrowstyle':'<->'})
a.text(6.2,2.45,'Internal ladder reported in 2009',fontsize=10)
a.text(6,.4,'Room sizes, circulation, floor depth and current survival are unresolved.',ha='center',fontsize=10)
finish(fig,'interior_concepts')
print('Created three PNG/SVG figures')
