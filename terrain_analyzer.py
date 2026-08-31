"""
Pond Analysis Engine v5 — Bug-fixed + Visualization
Critical fix: depression_depth = filled_dem - raw_dem (not gaussian - raw)
New: /api/plots returns base64 terrain images (3D elev, slope, TWI, flow)
"""
import math, heapq, io, base64
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter, distance_transform_edt, maximum_filter
from pyproj import Transformer
from shapely.geometry import box as sbox
from shapely.ops import unary_union
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

COLORS = ['#10B981','#06B6D4','#8B5CF6','#F59E0B','#EC4899']

# ── helpers ──────────────────────────────────────────────────────────────────

def haversine_distance(la1,lo1,la2,lo2):
    R=6_371_000; p1,p2=math.radians(la1),math.radians(la2)
    a=math.sin(math.radians((la2-la1)/2))**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians((lo2-lo1)/2))**2
    return R*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

def _utm_epsg(lon,lat):
    z=int((lon+180)/6)+1
    return f"EPSG:326{z:02d}" if lat>=0 else f"EPSG:327{z:02d}"

def _priority_flood(dem):
    """Barnes 2014 — fills pits. Returns filled DEM."""
    f=dem.copy().astype(np.float64); nr,nc=f.shape; EPS=1e-4
    vis=np.zeros((nr,nc),bool); heap=[]
    for r in range(nr):
        for c in [0,nc-1]:
            if not vis[r,c]: heapq.heappush(heap,(f[r,c],r,c)); vis[r,c]=True
    for c in range(nc):
        for r in [0,nr-1]:
            if not vis[r,c]: heapq.heappush(heap,(f[r,c],r,c)); vis[r,c]=True
    nb=[(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]
    while heap:
        e,r,c=heapq.heappop(heap)
        for dr,dc in nb:
            R2,C2=r+dr,c+dc
            if 0<=R2<nr and 0<=C2<nc and not vis[R2,C2]:
                vis[R2,C2]=True; f[R2,C2]=max(f[R2,C2],e+EPS)
                heapq.heappush(heap,(f[R2,C2],R2,C2))
    return f

def _horn_slope(dem,cx,cy):
    p=np.pad(dem,1,mode='edge')
    dzdx=((p[:-2,2:]+2*p[1:-1,2:]+p[2:,2:])-(p[:-2,:-2]+2*p[1:-1,:-2]+p[2:,:-2]))/(8*cx)
    dzdy=((p[2:,:-2]+2*p[2:,1:-1]+p[2:,2:])-(p[:-2,:-2]+2*p[:-2,1:-1]+p[:-2,2:]))/(8*cy)
    return np.degrees(np.arctan(np.sqrt(dzdx**2+dzdy**2)))

def _d8(dem):
    nr,nc=dem.shape
    pad=np.pad(dem.astype(np.float64),1,constant_values=np.inf)
    sh=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    ds=[math.sqrt(2),1,math.sqrt(2),1,1,math.sqrt(2),1,math.sqrt(2)]
    bd=np.full((nr,nc),-np.inf); fdr=np.zeros((nr,nc),np.int32); fdc=np.zeros((nr,nc),np.int32); ht=np.zeros((nr,nc),bool)
    for (dr,dc),d in zip(sh,ds):
        nb=pad[1+dr:1+dr+nr,1+dc:1+dc+nc]; drop=(dem-nb)/d; up=drop>bd
        bd[up]=drop[up]; fdr[up]=dr; fdc[up]=dc; ht[up]=True
    fa=np.ones(nr*nc,np.float32)
    for fi in np.argsort(dem.ravel())[::-1]:
        r,c=divmod(int(fi),nc)
        if ht[r,c]:
            R2,C2=r+int(fdr[r,c]),c+int(fdc[r,c])
            if 0<=R2<nr and 0<=C2<nc: fa[R2*nc+C2]+=fa[fi]
    return fa.reshape(nr,nc),fdr,fdc,ht

def _shapely_poly(cells,gx,gy,cx,cy,t2w):
    if not cells: return []
    boxes=[sbox(gx[c]-cx/2,gy[r]-cy/2,gx[c]+cx/2,gy[r]+cy/2) for r,c in cells]
    u=unary_union(boxes).simplify(max(cx,cy)*0.4)
    if u.is_empty: return []
    def tr(ring):
        return [[round(lo,6),round(la,6)] for lo,la in (t2w.transform(x,y) for x,y in ring)]
    poly=max(u.geoms,key=lambda g:g.area) if u.geom_type=='MultiPolygon' else u
    return tr(poly.exterior.coords)

def _b64(fig):
    buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=90,bbox_inches='tight'); plt.close(fig)
    buf.seek(0); return base64.b64encode(buf.read()).decode()

# ── plot generators ───────────────────────────────────────────────────────────

def generate_plots(dem_raw, dem_filled, slope, flow_acc, twi, grid_x, grid_y,
                   candidates, to_wgs84):
    """Returns dict of base64 PNG plots."""
    nr,nc=dem_raw.shape
    # subsample for 3D (keep fast)
    step=max(1,min(nr,nc)//60)
    X=grid_x[::step]; Y=grid_y[::step]
    Z=dem_raw[::step,::step]; XX,YY=np.meshgrid(X,Y)

    plots={}

    # 1. 3D Elevation Surface
    fig=plt.figure(figsize=(9,6)); ax=fig.add_subplot(111,projection='3d')
    surf=ax.plot_surface(XX,YY,Z,cmap='terrain',alpha=0.85,linewidth=0,antialiased=True)
    # Mark pond sites
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        el=cand['pond_location']['elevation_m']
        ax.scatter([lo],[la],[el+2],color=cand['color'],s=60,zorder=5)
    fig.colorbar(surf,ax=ax,shrink=0.4,label='Elevation (m)')
    ax.set_title('3D Terrain Elevation + Pond Sites',fontsize=12,fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude'); ax.set_zlabel('Elev (m)')
    ax.view_init(elev=35,azim=-60)
    fig.tight_layout(); plots['3d_elevation']=_b64(fig)

    # 2. DEM Hillshade + Pond overlay
    fig,ax=plt.subplots(figsize=(8,6))
    hs=ax.imshow(dem_raw,cmap='terrain',origin='lower',
                 extent=[grid_x.min(),grid_x.max(),grid_y.min(),grid_y.max()],aspect='auto')
    plt.colorbar(hs,ax=ax,label='Elevation (m)')
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        ax.plot(lo,la,'o',color=cand['color'],ms=10,mec='white',mew=2,
                label=f"Site #{cand['rank']} ({cand['catchment_summary']['area_hectares']} ha)")
    ax.legend(fontsize=8,loc='upper right'); ax.set_title('DEM Heatmap + Candidate Pond Sites',fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    fig.tight_layout(); plots['dem_heatmap']=_b64(fig)

    # 3. Slope Map
    fig,ax=plt.subplots(figsize=(8,6))
    sm=ax.imshow(slope,cmap='RdYlGn_r',origin='lower',vmin=0,vmax=15,
                 extent=[grid_x.min(),grid_x.max(),grid_y.min(),grid_y.max()],aspect='auto')
    plt.colorbar(sm,ax=ax,label='Slope (degrees)')
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        ax.plot(lo,la,'o',color=cand['color'],ms=10,mec='white',mew=2)
    ax.set_title('Slope Map  (green=flat, red=steep)',fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    fig.tight_layout(); plots['slope_map']=_b64(fig)

    # 4. Flow Accumulation (log scale)
    fig,ax=plt.subplots(figsize=(8,6))
    fm=ax.imshow(np.log1p(flow_acc),cmap='Blues',origin='lower',
                 extent=[grid_x.min(),grid_x.max(),grid_y.min(),grid_y.max()],aspect='auto')
    plt.colorbar(fm,ax=ax,label='ln(1 + Flow Accumulation)')
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        ax.plot(lo,la,'o',color=cand['color'],ms=10,mec='white',mew=2)
    ax.set_title('D8 Flow Accumulation (log scale)  — dark blue = river',fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    fig.tight_layout(); plots['flow_accumulation']=_b64(fig)

    # 5. TWI Map
    fig,ax=plt.subplots(figsize=(8,6))
    tm=ax.imshow(twi,cmap='YlGnBu',origin='lower',
                 extent=[grid_x.min(),grid_x.max(),grid_y.min(),grid_y.max()],aspect='auto')
    plt.colorbar(tm,ax=ax,label='TWI = ln(A / tan β)')
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        ax.plot(lo,la,'o',color=cand['color'],ms=10,mec='white',mew=2)
    ax.set_title('Topographic Wetness Index  (high = natural water accumulation zones)',fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    fig.tight_layout(); plots['twi_map']=_b64(fig)

    # 6. Depression Depth (filled - raw)
    dep=dem_filled - dem_raw
    fig,ax=plt.subplots(figsize=(8,6))
    dm=ax.imshow(dep,cmap='PuBu',origin='lower',vmin=0,
                 extent=[grid_x.min(),grid_x.max(),grid_y.min(),grid_y.max()],aspect='auto')
    plt.colorbar(dm,ax=ax,label='Depression Depth (m)')
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        ax.plot(lo,la,'o',color=cand['color'],ms=10,mec='white',mew=2)
    ax.set_title('Terrain Depressions / Sinks  (blue = natural basins)',fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude')
    fig.tight_layout(); plots['depression_map']=_b64(fig)

    return plots

# ── main analysis ─────────────────────────────────────────────────────────────

def analyze_terrain_and_catchment(parsed_kml_data, max_candidate_ponds=4):
    pts=parsed_kml_data['points']; bbox=parsed_kml_data['bbox']
    lons,lats,elevs=pts[:,0].copy(),pts[:,1].copy(),pts[:,2].copy()
    ok=(elevs>0)&(elevs<9000); lons,lats,elevs=lons[ok],lats[ok],elevs[ok]
    if len(lons)>12000:
        s=len(lons)//12000; lons,lats,elevs=lons[::s],lats[::s],elevs[::s]

    cx0=(bbox['min_lon']+bbox['max_lon'])/2; cy0=(bbox['min_lat']+bbox['max_lat'])/2
    epsg=_utm_epsg(cx0,cy0)
    t2u=Transformer.from_crs("EPSG:4326",epsg,always_xy=True)
    t2w=Transformer.from_crs(epsg,"EPSG:4326",always_xy=True)
    xs,ys=t2u.transform(lons,lats)
    xmin,xmax,ymin,ymax=xs.min(),xs.max(),ys.min(),ys.max()
    wm,hm=xmax-xmin,ymax-ymin

    nc2=200; nr2=max(50,int(nc2*hm/max(wm,1)))
    cx=wm/nc2; cy=hm/nr2; ca=cx*cy
    gx=np.linspace(xmin,xmax,nc2); gy=np.linspace(ymin,ymax,nr2)
    GX,GY=np.meshgrid(gx,gy)
    q=np.column_stack((GX.ravel(),GY.ravel())); src=np.column_stack((xs,ys))
    dl=griddata(src,elevs,q,method='linear').reshape(nr2,nc2)
    dn=griddata(src,elevs,q,method='nearest').reshape(nr2,nc2)
    dem_raw=gaussian_filter(np.where(np.isnan(dl),dn,dl),sigma=1.0)

    # ── CRITICAL FIX: fill AFTER saving raw ──────────────────────────────────
    dem_filled=_priority_flood(dem_raw)
    # True depression depth = how much was filled = filled - raw (positive = sink)
    depression_depth=dem_filled-dem_raw  # ← correct definition

    slope=_horn_slope(dem_filled,cx,cy)

    # D8 on FILLED dem (hydrologically correct)
    fa,fdr,fdc,ht=_d8(dem_filled)

    # upstream map
    umap={}
    ri,ci=np.where(ht)
    for r,c in zip(ri.tolist(),ci.tolist()):
        R2,C2=r+int(fdr[r,c]),c+int(fdc[r,c])
        if 0<=R2<nr2 and 0<=C2<nc2: umap.setdefault((R2,C2),[]).append((r,c))

    # river = top 1% FA cells; buffer = 40% of max distance
    river_thresh=np.percentile(fa,99); is_river=fa>=river_thresh
    dist_r=distance_transform_edt(~is_river)*((cx+cy)/2)
    buf=max(50.0,dist_r.max()*0.40)

    # TWI
    sr=np.radians(np.clip(slope,0.1,89)); spa=np.maximum(fa*cx,1.0)
    twi=np.clip(np.log(spa/(np.tan(sr)+1e-6)),0,None)
    twi_n=(twi-twi.min())/max(twi.max()-twi.min(),1e-6)

    # PSI
    fl=np.log1p(fa); fl_n=(fl-fl.min())/max(fl.max()-fl.min(),1e-6)
    sg=np.where(slope>8,0,np.exp(-((slope-2.5)**2)/(2*2**2)))
    mz,Mz=dem_filled.min(),dem_filled.max()
    zn=(dem_filled-mz)/max(Mz-mz,1)
    # depression norm — key fix: use correct depression_depth
    dep_n=np.clip(depression_depth/max(float(np.percentile(depression_depth[depression_depth>0],75)) if (depression_depth>0).any() else 1,1e-6),0,1)

    valid=(dist_r>=buf)&(slope>=0.3)&(slope<8)&(depression_depth>0.001)
    psi=np.where(valid,0.35*dep_n+0.30*fl_n+0.20*twi_n+0.15*(1-zn),0.0)
    b=5; psi[:b,:]=psi[-b:,:]=psi[:,:b]=psi[:,-b:]=0

    lmx=maximum_filter(psi,size=16)
    peaks=sorted(np.argwhere((psi==lmx)&(psi>0.01)),key=lambda rc:psi[rc[0],rc[1]],reverse=True)
    sep=max(12,int(350/((cx+cy)/2))); mc=max(5,int(10000/ca))
    sel=[]
    for r,c in peaks:
        t=set(); stk=[(int(r),int(c))]
        while stk and len(t)<mc*3:
            cell=stk.pop()
            if cell not in t: t.add(cell); stk.extend(umap.get(cell,[]))
        if len(t)<mc: continue
        if all((r-pr)**2+(c-pc)**2>=sep**2 for pr,pc in sel): sel.append((r,c))
        if len(sel)>=max_candidate_ponds: break
    if not sel:
        m=np.where(valid,dem_filled,np.inf); m[:b,:]=m[-b:,:]=m[:,:b]=m[:,-b:]=np.inf
        br,bc=np.unravel_index(np.argmin(m if np.isfinite(m).any() else dem_filled),dem_filled.shape)
        sel=[(int(br),int(bc))]

    cands=[]; geo=[]
    for rank,(pr,pc) in enumerate(sel,1):
        cat=set(); stk=[(int(pr),int(pc))]
        while stk:
            cell=stk.pop()
            if cell not in cat: cat.add(cell); stk.extend(umap.get(cell,[]))
        am2=len(cat)*ca; aha=am2/10000; aac=am2/4046.86
        bnd=_shapely_poly(cat,gx,gy,cx,cy,t2w)
        rf=0.85; rc2=0.35; rm3=am2*rf*rc2
        cap=min(rm3*0.18,25000); surf=cap/3.5; side=math.sqrt(max(surf,1))
        # stage-storage
        base_e=float(dem_filled[pr,pc])
        els=[float(dem_filled[r,c]) for r,c in cat]
        curve=[]
        for d in [0.5,1.0,1.5,2.0,3.0]:
            we=base_e+d; fl2=sum(1 for e in els if e<=we)
            curve.append({'depth_m':d,'surface_elev_m':round(we,2),
                         'area_m2':round(fl2*ca,1),'volume_m3':round(sum((we-e)*ca for e in els if e<=we),1)})
        col=COLORS[(rank-1)%len(COLORS)]
        plo,pla=t2w.transform(float(gx[pc]),float(gy[pr]))
        c_obj={'rank':rank,'is_primary':rank==1,'color':col,
               'pond_location':{'latitude':round(pla,6),'longitude':round(plo,6),
                                'elevation_m':round(float(dem_filled[pr,pc]),2),
                                'river_buffer_distance_m':round(float(dist_r[pr,pc]),1),
                                'depression_depth_m':round(float(depression_depth[pr,pc]),3),
                                'twi':round(float(twi[pr,pc]),2),
                                'suitability_score_pct':round(float(psi[pr,pc])*100,1),
                                'terrain_slope_deg':round(float(slope[pr,pc]),2)},
               'catchment_summary':{'area_m2':round(am2,2),'area_hectares':round(aha,2),
                                    'area_acres':round(aac,2),'contributing_cells':len(cat)},
               'water_harvesting':{'rainfall_mm':850,'runoff_coeff':rc2,
                                   'annual_runoff_m3':round(rm3,2),
                                   'annual_runoff_liters':round(rm3*1000,0),
                                   'pond_capacity_m3':round(cap,2),
                                   'pond_depth_m':3.5,
                                   'pond_surface_m2':round(surf,2),
                                   'dimensions':f"{round(side,1)}m x {round(side,1)}m"},
               'stage_storage':curve,
               'water_harvesting_estimates':{'assumed_annual_rainfall_mm':850,
                                             'runoff_coefficient_C':rc2,
                                             'estimated_annual_runoff_m3':round(rm3,2),
                                             'estimated_annual_runoff_liters':round(rm3*1000,0),
                                             'recommended_pond_capacity_m3':round(cap,2),
                                             'recommended_pond_depth_m':3.5,
                                             'recommended_pond_surface_area_m2':round(surf,2),
                                             'recommended_dimensions_m':f"{round(side,1)}m x {round(side,1)}m"}}
        cands.append(c_obj)
        geo.append({'type':'Feature','geometry':{'type':'Point','coordinates':[round(plo,6),round(pla,6)]},
                    'properties':{'rank':rank,'name':f"Farm Pond #{rank}",'elevation_m':round(float(dem_filled[pr,pc]),2),
                                  'river_distance_m':round(float(dist_r[pr,pc]),1),
                                  'depression_depth_m':round(float(depression_depth[pr,pc]),3),
                                  'twi':round(float(twi[pr,pc]),2),
                                  'suitability_score':round(float(psi[pr,pc])*100,1),
                                  'area_ha':round(aha,2),'color':col}})
        if bnd:
            geo.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[bnd]},
                        'properties':{'rank':rank,'name':f"Basin #{rank}",'area_ha':round(aha,2),'color':col}})

    # Convert WGS84 coords for plots
    lo_arr=np.array([t2w.transform(float(gx[c]),float(gy[r]))[0] for r in range(nr2) for c in range(nc2)]).reshape(nr2,nc2)
    la_arr=np.array([t2w.transform(float(gx[c]),float(gy[r]))[1] for r in range(nr2) for c in range(nc2)]).reshape(nr2,nc2)
    # Use center column/row lon/lat for extent
    gx_wgs=np.array([t2w.transform(float(gx[c]),float(gy[nr2//2]))[0] for c in range(nc2)])
    gy_wgs=np.array([t2w.transform(float(gx[nc2//2]),float(gy[r]))[1] for r in range(nr2)])

    p=cands[0]
    return {
        'pond_location':p['pond_location'],
        'catchment_summary':p['catchment_summary'],
        'water_harvesting_estimates':p['water_harvesting_estimates'],
        'stage_storage':p['stage_storage'],
        'total_catchments_detected':len(cands),
        'all_candidate_sites':cands,
        'terrain_statistics':{'min_elevation_m':round(float(mz),2),'max_elevation_m':round(float(Mz),2),
                               'elevation_range_m':round(float(Mz-mz),2),
                               'avg_slope_deg':round(float(slope.mean()),2),
                               'avg_twi':round(float(twi.mean()),2),
                               'utm_projection':epsg,'river_buffer_used_m':round(buf,1),
                               'map_width_meters':round(wm,1),'map_height_meters':round(hm,1),
                               'grid_resolution':f"{nc2} x {nr2}",'cell_size_m':round((cx+cy)/2,1)},
        'geojson_layers':{'type':'FeatureCollection','features':geo},
        # store for plot generation
        '_dem_raw':dem_raw,'_dem_filled':dem_filled,'_slope':slope,
        '_flow_acc':fa,'_twi':twi,'_gx_wgs':gx_wgs,'_gy_wgs':gy_wgs,
    }


if __name__=='__main__':
    import time
    from kml_parser import parse_kml_or_kmz
    t0=time.time()
    d=parse_kml_or_kmz('contours_1m.kml')
    r=analyze_terrain_and_catchment(d)
    print(f"[{time.time()-t0:.2f}s] {r['total_catchments_detected']} sites | buf={r['terrain_statistics']['river_buffer_used_m']}m")
    for c in r['all_candidate_sites']:
        l=c['pond_location']; cs=c['catchment_summary']
        print(f"  #{c['rank']} {l['latitude']:.5f},{l['longitude']:.5f} | dep={l['depression_depth_m']}m | TWI={l['twi']} | {cs['area_hectares']}ha | {l['suitability_score_pct']}%")
