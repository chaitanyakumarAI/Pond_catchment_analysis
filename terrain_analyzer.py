"""
Pond Analysis Engine v6 — adds user-selected land-area analysis
(v5: bug-fixed + visualization;
critical fix: depression_depth = filled_dem - raw_dem (not gaussian - raw)
New: /api/plots returns base64 terrain images (3D elev, slope, TWI, flow)
"""
import math, heapq, io, base64, os
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
    u=unary_union(boxes).buffer(max(cx,cy)*0.6).simplify(max(cx,cy)*0.3)
    if u.is_empty: return []
    def tr(ring):
        return [[round(lo,6),round(la,6)] for lo,la in (t2w.transform(x,y) for x,y in ring)]
    poly=max(u.geoms,key=lambda g:g.area) if u.geom_type=='MultiPolygon' else u
    return tr(poly.exterior.coords)

PLOTS_DIR = os.path.join(os.path.dirname(__file__), 'outputs', 'plots')
os.makedirs(PLOTS_DIR, exist_ok=True)

def _b64(fig, name='plot'):
    """Save fig as PNG locally and return base64 string."""
    # Save local file
    fpath = os.path.join(PLOTS_DIR, f"{name}.png")
    fig.savefig(fpath, format='png', dpi=100, bbox_inches='tight')
    # Also encode to base64 for API response
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=90, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

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

    # 1. 3D Elevation Surface (scaled strictly to 250m - 300m elevation axis)
    fig=plt.figure(figsize=(9,6)); ax=fig.add_subplot(111,projection='3d')
    zlo,zhi=float(np.nanmin(dem_raw)),float(np.nanmax(dem_raw))
    surf=ax.plot_surface(XX,YY,Z,cmap='terrain',vmin=zlo,vmax=zhi,alpha=0.88,linewidth=0,antialiased=True)
    ax.set_zlim(zlo-max(2.0,0.25*(zhi-zlo)), zhi+2.0)
    # Mark pond sites
    for cand in candidates:
        lo,la=cand['pond_location']['longitude'],cand['pond_location']['latitude']
        el=cand['pond_location']['elevation_m']
        ax.scatter([lo],[la],[el+2],color=cand['color'],s=60,zorder=5)
    fig.colorbar(surf,ax=ax,shrink=0.4,label='Elevation (m)')
    ax.set_title(f'3D Terrain Elevation ({zlo:.0f}m - {zhi:.0f}m) + Pond Sites',fontsize=12,fontweight='bold')
    ax.set_xlabel('Longitude'); ax.set_ylabel('Latitude'); ax.set_zlabel('Elev (m)')
    ax.view_init(elev=35,azim=-60)
    fig.tight_layout(); plots['3d_elevation']=_b64(fig, '3d_elevation')

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
    fig.tight_layout(); plots['dem_heatmap']=_b64(fig, 'dem_heatmap')

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
    fig.tight_layout(); plots['slope_map']=_b64(fig, 'slope_map')

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
    fig.tight_layout(); plots['flow_accumulation']=_b64(fig, 'flow_accumulation')

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
    fig.tight_layout(); plots['twi_map']=_b64(fig, 'twi_map')

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
    fig.tight_layout(); plots['depression_map']=_b64(fig, 'depression_map')

    return plots

# ── main analysis ─────────────────────────────────────────────────────────────
#
# Two-stage design (Phase 3):
#   Stage A  build_terrain_model(parsed)   — DEM, sink fill, slope, D8, TWI, PSI.
#            Depends only on the contour map, so it is computed ONCE per dataset
#            and cached (≈0.6 s for the sample map).
#   Stage B  select_sites(model, polygon)  — restricts pond candidates to the land
#            area the user drew on the map, delineates their catchments on the
#            full terrain and estimates water volume. Takes a few milliseconds.
# analyze_terrain_and_catchment() keeps the Phase-1 signature and runs A+B.

class AreaSelectionError(ValueError):
    """Raised when a user-selected land area cannot be analysed (no data, too small, too big)."""
    def __init__(self, message, extra=None):
        super().__init__(message)
        self.extra = extra or {}


# Engineering limits (documented in the report — "system limitations")
MIN_AREA_M2 = 5_000          # 0.5 ha  — below this a farm pond is not meaningful
MAX_AREA_M2 = 50_000_000     # 50 km²  — upper bound for one request
MIN_COVERAGE = 0.60          # ≥60 % of the drawn area must be covered by contour data
MAX_POLY_VERTICES = 500
MAX_GRID_POINTS = 12000      # contour vertices used for interpolation (sub-sampled above this)


def _robust_elevation_filter(elevs):
    """Drop spike/noise vertices (e.g. the stray 30 m points in the sample map)
    using a percentile window instead of fixed elevation constants."""
    lo, hi = np.percentile(elevs, [0.5, 99.5])
    pad = max(0.5 * (hi - lo), 2.0)
    return (elevs >= lo - pad) & (elevs <= hi + pad)


def build_terrain_model(parsed_kml_data):
    """Stage A — dataset-level terrain & hydrology model (cacheable)."""
    import time as _time
    t0 = _time.perf_counter()
    pts=parsed_kml_data['points']; bbox=parsed_kml_data['bbox']
    lons,lats,elevs=pts[:,0].copy(),pts[:,1].copy(),pts[:,2].copy()
    ok=_robust_elevation_filter(elevs)
    lons,lats,elevs=lons[ok],lats[ok],elevs[ok]
    if len(lons)>MAX_GRID_POINTS:
        s=len(lons)//MAX_GRID_POINTS; lons,lats,elevs=lons[::s],lats[::s],elevs[::s]

    cx0=(bbox['min_lon']+bbox['max_lon'])/2; cy0=(bbox['min_lat']+bbox['max_lat'])/2
    epsg=_utm_epsg(cx0,cy0)
    t2u=Transformer.from_crs("EPSG:4326",epsg,always_xy=True)
    t2w=Transformer.from_crs(epsg,"EPSG:4326",always_xy=True)
    xs,ys=t2u.transform(lons,lats); xs=np.asarray(xs); ys=np.asarray(ys)
    xmin,xmax,ymin,ymax=xs.min(),xs.max(),ys.min(),ys.max()
    wm,hm=xmax-xmin,ymax-ymin

    nc2=200; nr2=max(50,int(nc2*hm/max(wm,1)))
    cx=wm/nc2; cy=hm/nr2; ca=cx*cy
    gx=np.linspace(xmin,xmax,nc2); gy=np.linspace(ymin,ymax,nr2)
    GX,GY=np.meshgrid(gx,gy)
    q=np.column_stack((GX.ravel(),GY.ravel())); src=np.column_stack((xs,ys))
    dl=griddata(src,elevs,q,method='linear').reshape(nr2,nc2)
    dn=griddata(src,elevs,q,method='nearest').reshape(nr2,nc2)
    raw_interp=np.where(np.isnan(dl),dn,dl)
    has_data=~np.isnan(dl)                       # inside the convex hull of the contours
    dem_raw=np.clip(gaussian_filter(raw_interp,sigma=1.0),float(elevs.min())-1.0,float(elevs.max())+1.0)

    dem_filled=_priority_flood(dem_raw)
    depression_depth=dem_filled-dem_raw           # true sink depth
    slope=_horn_slope(dem_filled,cx,cy)
    fa,fdr,fdc,ht=_d8(dem_filled)

    umap={}
    ri,ci=np.where(ht)
    for r,c in zip(ri.tolist(),ci.tolist()):
        R2,C2=r+int(fdr[r,c]),c+int(fdc[r,c])
        if 0<=R2<nr2 and 0<=C2<nc2: umap.setdefault((R2,C2),[]).append((r,c))

    # River corridor: top 5 % flow accumulation OR low flat valley trough
    river_thresh = np.percentile(fa, 95)
    elev_river_thresh = np.percentile(dem_raw, 18)
    is_river = (fa >= river_thresh) | ((dem_raw <= elev_river_thresh) & (slope < 3.0))
    dist_r = distance_transform_edt(~is_river) * ((cx + cy) / 2)
    buf = max(120.0, dist_r.max() * 0.25)

    sr=np.radians(np.clip(slope,0.1,89)); spa=np.maximum(fa*cx,1.0)
    twi=np.clip(np.log(spa/(np.tan(sr)+1e-6)),0,None)
    twi_n=(twi-twi.min())/max(twi.max()-twi.min(),1e-6)

    fl=np.log1p(fa); fl_n=(fl-fl.min())/max(fl.max()-fl.min(),1e-6)
    mz,Mz=dem_filled.min(),dem_filled.max()
    zn=(dem_filled-mz)/max(Mz-mz,1)
    dep_n=np.clip(depression_depth/max(float(np.percentile(depression_depth[depression_depth>0],75)) if (depression_depth>0).any() else 1,1e-6),0,1)
    psi_raw=0.35*dep_n+0.30*fl_n+0.20*twi_n+0.15*(1-zn)      # Pond Suitability Index
    base_valid=(slope>=0.3)&(slope<8)&(depression_depth>0.001)

    border=np.ones((nr2,nc2),bool); b=5
    border[:b,:]=border[-b:,:]=border[:,:b]=border[:,-b:]=False

    # data-coverage footprint (for the map + selection validation)
    from shapely.geometry import MultiPoint
    stride=max(1,len(xs)//20000)
    hull=MultiPoint(list(zip(xs[::stride],ys[::stride]))).convex_hull
    hull_wgs=[[round(v,6) for v in t2w.transform(x,y)] for x,y in hull.exterior.coords]

    gx_wgs=np.array([t2w.transform(float(gx[c]),float(gy[nr2//2]))[0] for c in range(nc2)])
    gy_wgs=np.array([t2w.transform(float(gx[nc2//2]),float(gy[r]))[1] for r in range(nr2)])

    return dict(epsg=epsg,t2u=t2u,t2w=t2w,gx=gx,gy=gy,q=q,nr=nr2,nc=nc2,cx=cx,cy=cy,ca=ca,wm=wm,hm=hm,
                dem_raw=dem_raw,dem_filled=dem_filled,depression_depth=depression_depth,slope=slope,
                fa=fa,umap=umap,is_river=is_river,dist_r=dist_r,buf=buf,twi=twi,psi_raw=psi_raw,
                base_valid=base_valid,border=border,has_data=has_data,hull=hull,hull_wgs=hull_wgs,
                mz=float(mz),Mz=float(Mz),gx_wgs=gx_wgs,gy_wgs=gy_wgs,
                build_ms=round((_time.perf_counter()-t0)*1000,1))


def _selection_mask(model, area_polygon):
    """Rasterise the user polygon onto the model grid. Returns (mask, info, clipped_poly_utm)."""
    from shapely.geometry import Polygon
    from matplotlib.path import Path as _MPath
    if len(area_polygon) < 3 or len(area_polygon) > MAX_POLY_VERTICES:
        raise AreaSelectionError(f"Selected area must have 3–{MAX_POLY_VERTICES} vertices.")
    apoly=np.asarray(area_polygon,dtype=float)
    if apoly.ndim!=2 or apoly.shape[1]<2 or not np.isfinite(apoly).all():
        raise AreaSelectionError("Polygon must be a list of [longitude, latitude] pairs.")
    px,py=model['t2u'].transform(apoly[:,0],apoly[:,1])
    poly=Polygon(list(zip(px,py)))
    if not poly.is_valid: poly=poly.buffer(0)
    area=float(poly.area)
    if area < MIN_AREA_M2:
        raise AreaSelectionError(f"Selected area is {area/10000:.2f} ha — please select at least {MIN_AREA_M2/10000:.1f} ha.")
    if area > MAX_AREA_M2:
        raise AreaSelectionError(f"Selected area is {area/1e6:.1f} km² — the limit is {MAX_AREA_M2/1e6:.0f} km² per request.")
    inter=poly.intersection(model['hull'])
    coverage=100.0*(inter.area/area if area>0 else 0)
    if inter.is_empty or coverage < MIN_COVERAGE*100:
        raise AreaSelectionError(
            f"Only {coverage:.0f}% of the selected area has contour data (need ≥{MIN_COVERAGE*100:.0f}%). "
            "Draw the area inside the dashed data-coverage boundary, or upload a contour map for that region.",
            {'coverage_pct':round(coverage,1)})
    if inter.geom_type!='Polygon':
        inter=max(getattr(inter,'geoms',[inter]),key=lambda g:g.area)
    mask=_MPath(np.asarray(inter.exterior.coords)).contains_points(model['q']).reshape(model['nr'],model['nc'])
    if mask.sum() < 4:
        raise AreaSelectionError("Selected area is smaller than the terrain grid resolution "
                                 f"({model['cx']:.0f} m cells). Please draw a larger area.")
    info={'area_m2':round(area,1),'area_hectares':round(area/10000,2),
          'analysed_area_m2':round(float(inter.area),1),'data_coverage_pct':round(coverage,1),
          'grid_cells':int(mask.sum())}
    return mask, info, inter


def select_sites(model, area_polygon=None, max_candidate_ponds=4,
                 rainfall_mm=850.0, runoff_coeff=0.35, pond_depth_m=3.5):
    """Stage B — pond siting, catchment delineation and water-volume estimation
    inside the selected land area (whole map when area_polygon is None)."""
    import time as _time
    t0=_time.perf_counter()
    rainfall_mm=float(rainfall_mm); runoff_coeff=float(runoff_coeff); pond_depth_m=float(pond_depth_m)
    M=model; nr2,nc2=M['nr'],M['nc']; cx,cy,ca=M['cx'],M['cy'],M['ca']
    gx,gy,t2w=M['gx'],M['gy'],M['t2w']
    dem_filled,depression_depth,slope,twi=M['dem_filled'],M['depression_depth'],M['slope'],M['twi']
    is_river,dist_r,umap=M['is_river'],M['dist_r'],M['umap']

    sel_info=None; sel_poly=None
    if area_polygon:
        inside,sel_info,sel_poly=_selection_mask(M,area_polygon)
        zone=inside&M['border']
        if zone.sum()==0: zone=inside.copy()
    else:
        inside=np.ones((nr2,nc2),bool); zone=M['border']

    # River buffer ≥120 m; relaxed step-wise only when a small parcel has no site otherwise
    buf=M['buf']
    for cand_buf in [buf,90.0,60.0,30.0,0.0]:
        valid=(dist_r>=cand_buf)&M['base_valid']&zone
        if valid.sum()>=20 or cand_buf==0.0:
            buf=cand_buf; break
    psi=np.where(valid,M['psi_raw'],0.0)

    lmx=maximum_filter(psi,size=16)
    peaks=sorted(np.argwhere((psi==lmx)&(psi>0.01)),key=lambda rc:psi[rc[0],rc[1]],reverse=True)
    sep=max(12,int(350/((cx+cy)/2)))
    mc=max(5,int(10000/ca))                                   # ≥1 ha catchment
    if area_polygon:
        mc=max(3,min(mc,int(0.5*inside.sum())))
    sel=[]
    for r,c in peaks:
        t=set(); stk=[(int(r),int(c))]
        while stk and len(t)<mc*3:
            cell=stk.pop()
            if cell not in t and not is_river[cell[0],cell[1]]:
                t.add(cell); stk.extend(umap.get(cell,[]))
        if len(t)<mc: continue
        if all((r-pr)**2+(c-pc)**2>=sep**2 for pr,pc in sel): sel.append((r,c))
        if len(sel)>=max_candidate_ponds: break
    fallback=False
    if not sel:
        fallback=True
        pool=valid if valid.any() else zone
        # prefer the cell with the largest upstream area among the lowest-risk cells
        score=np.where(pool&~is_river,np.log1p(M['fa'])+M['psi_raw'],-np.inf)
        if not np.isfinite(score).any(): score=np.where(inside,-dem_filled,-np.inf)
        br,bc=np.unravel_index(np.argmax(score),dem_filled.shape)
        sel=[(int(br),int(bc))]

    cands=[]; geo=[]
    for rank,(pr,pc) in enumerate(sel,1):
        cat=set(); stk=[(int(pr),int(pc))]
        while stk:
            cell=stk.pop()
            if cell not in cat and (not is_river[cell[0],cell[1]] or cell==(int(pr),int(pc))):
                cat.add(cell); stk.extend(umap.get(cell,[]))
        am2=len(cat)*ca; aha=am2/10000; aac=am2/4046.86
        in_parcel=sum(1 for r,c in cat if inside[r,c])*ca
        bnd=_shapely_poly(cat,gx,gy,cx,cy,t2w)
        rf=rainfall_mm/1000.0; rc2=runoff_coeff; rm3=am2*rf*rc2          # Q = C·P·A
        cap=min(rm3*0.18,25000); surf=cap/pond_depth_m; side=math.sqrt(max(surf,1))
        base_e=float(dem_filled[pr,pc])
        els=[float(dem_filled[r,c]) for r,c in cat]
        curve=[]
        for d in [0.5,1.0,1.5,2.0,3.0]:
            we=base_e+d; fl2=sum(1 for e in els if e<=we)
            curve.append({'depth_m':d,'surface_elev_m':round(we,2),
                         'area_m2':round(fl2*ca,1),'volume_m3':round(sum((we-e)*ca for e in els if e<=we),1)})
        col=COLORS[(rank-1)%len(COLORS)]
        px_u,py_u=float(gx[pc]),float(gy[pr])
        plo,pla=t2w.transform(px_u,py_u)
        h=side/2   # pond footprint (square sized from the recommended capacity) for the map overlay
        foot=[[round(v,7) for v in t2w.transform(px_u+dx,py_u+dy)] for dx,dy in [(-h,-h),(h,-h),(h,h),(-h,h),(-h,-h)]]
        wh={'assumed_annual_rainfall_mm':rainfall_mm,
            'runoff_coefficient_C':rc2,
            'estimated_annual_runoff_m3':round(rm3,2),
            'estimated_annual_runoff_liters':round(rm3*1000,0),
            'expected_water_volume_m3':round(rm3,2),
            'recommended_pond_capacity_m3':round(cap,2),
            'recommended_pond_depth_m':pond_depth_m,
            'recommended_pond_surface_area_m2':round(surf,2),
            'recommended_dimensions_m':f"{round(side,1)}m x {round(side,1)}m"}
        loc={'latitude':round(pla,6),'longitude':round(plo,6),
             'elevation_m':round(float(dem_filled[pr,pc]),2),
             'river_buffer_distance_m':round(float(dist_r[pr,pc]),1),
             'depression_depth_m':round(float(depression_depth[pr,pc]),3),
             'twi':round(float(twi[pr,pc]),2),
             'suitability_score_pct':round(float(M['psi_raw'][pr,pc] if fallback else psi[pr,pc])*100,1),
             'terrain_slope_deg':round(float(slope[pr,pc]),2)}
        c_obj={'rank':rank,'is_primary':rank==1,'color':col,
               'pond_location':loc,
               'catchment_summary':{'area_m2':round(am2,2),'area_hectares':round(aha,2),
                                    'area_acres':round(aac,2),'contributing_cells':len(cat),
                                    'area_inside_selected_land_m2':round(in_parcel,1)},
               'water_harvesting':{'rainfall_mm':rainfall_mm,'runoff_coeff':rc2,
                                   'annual_runoff_m3':round(rm3,2),
                                   'annual_runoff_liters':round(rm3*1000,0),
                                   'pond_capacity_m3':round(cap,2),
                                   'pond_depth_m':pond_depth_m,
                                   'pond_surface_m2':round(surf,2),
                                   'dimensions':f"{round(side,1)}m x {round(side,1)}m"},
               'stage_storage':curve,
               'pond_footprint':foot,
               'water_harvesting_estimates':wh}
        cands.append(c_obj)
        geo.append({'type':'Feature','geometry':{'type':'Point','coordinates':[round(plo,6),round(pla,6)]},
                    'properties':{'rank':rank,'kind':'pond_site','name':f"Farm Pond #{rank}",'elevation_m':loc['elevation_m'],
                                  'river_distance_m':loc['river_buffer_distance_m'],
                                  'depression_depth_m':loc['depression_depth_m'],'twi':loc['twi'],
                                  'suitability_score':loc['suitability_score_pct'],
                                  'area_ha':round(aha,2),'water_volume_m3':round(rm3,1),
                                  'pond_capacity_m3':round(cap,1),'color':col}})
        if bnd:
            geo.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[bnd]},
                        'properties':{'rank':rank,'kind':'catchment','name':f"Basin #{rank}",'area_ha':round(aha,2),
                                      'water_volume_m3':round(rm3,1),'color':col}})
        geo.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[foot]},
                    'properties':{'rank':rank,'kind':'pond_footprint','name':f"Pond #{rank} footprint",
                                  'pond_capacity_m3':round(cap,1),'dimensions':wh['recommended_dimensions_m'],
                                  'depth_m':pond_depth_m,'color':'#2563EB'}})

    if sel_poly is not None:
        ring=[[round(v,7) for v in t2w.transform(x,y)] for x,y in sel_poly.exterior.coords]
        sel_info['polygon']=ring
        geo.append({'type':'Feature','geometry':{'type':'Polygon','coordinates':[ring]},
                    'properties':{'kind':'selected_area','name':'Selected land area',
                                  'area_ha':sel_info['area_hectares'],'color':'#FFFFFF'}})

    p=cands[0]
    ins=inside if area_polygon else np.ones_like(inside)
    return {
        'pond_location':p['pond_location'],
        'catchment_summary':p['catchment_summary'],
        'water_harvesting_estimates':p['water_harvesting_estimates'],
        'expected_water_volume_m3':p['water_harvesting_estimates']['expected_water_volume_m3'],
        'total_expected_water_volume_all_sites_m3':round(sum(c['water_harvesting_estimates']['expected_water_volume_m3'] for c in cands),2),
        'stage_storage':p['stage_storage'],
        'total_catchments_detected':len(cands),
        'all_candidate_sites':cands,
        'selected_area':sel_info,
        'site_selection_note':('No site met all suitability rules inside the selected area; '
                               'the best-drained non-river cell was chosen instead.') if fallback else None,
        'terrain_statistics':{'min_elevation_m':round(float(dem_filled[ins].min()),2),
                               'max_elevation_m':round(float(dem_filled[ins].max()),2),
                               'elevation_range_m':round(float(dem_filled[ins].max()-dem_filled[ins].min()),2),
                               'avg_slope_deg':round(float(slope[ins].mean()),2),
                               'avg_twi':round(float(twi[ins].mean()),2),
                               'utm_projection':M['epsg'],'river_buffer_used_m':round(buf,1),
                               'map_width_meters':round(M['wm'],1),'map_height_meters':round(M['hm'],1),
                               'grid_resolution':f"{nc2} x {nr2}",'cell_size_m':round((cx+cy)/2,1)},
        'geojson_layers':{'type':'FeatureCollection','features':geo},
        'timing_ms':{'terrain_model_build':M['build_ms'],'site_selection':round((_time.perf_counter()-t0)*1000,1)},
        '_dem_raw':M['dem_raw'],'_dem_filled':dem_filled,'_slope':slope,
        '_flow_acc':M['fa'],'_twi':twi,'_gx_wgs':M['gx_wgs'],'_gy_wgs':M['gy_wgs'],
    }


def analyze_terrain_and_catchment(parsed_kml_data, max_candidate_ponds=4, area_polygon=None,
                                  rainfall_mm=850.0, runoff_coeff=0.35, pond_depth_m=3.5):
    """Phase-1 compatible one-shot call (Stage A + Stage B)."""
    model=build_terrain_model(parsed_kml_data)
    return select_sites(model, area_polygon, max_candidate_ponds, rainfall_mm, runoff_coeff, pond_depth_m)


if __name__=='__main__':
    import time
    from kml_parser import parse_kml_or_kmz
    t0=time.time()
    d=parse_kml_or_kmz('contours_1m.kml')
    r=analyze_terrain_and_catchment(d)
    epsg = r['terrain_statistics']['utm_projection']
    t2w  = Transformer.from_crs(epsg, 'EPSG:4326', always_xy=True)
    generate_plots(r['_dem_raw'], r['_dem_filled'], r['_slope'], r['_flow_acc'], r['_twi'], r['_gx_wgs'], r['_gy_wgs'], r['all_candidate_sites'], t2w)
    print(f"[{time.time()-t0:.2f}s] {r['total_catchments_detected']} sites | buf={r['terrain_statistics']['river_buffer_used_m']}m | Plots saved to outputs/plots/")
    for c in r['all_candidate_sites']:
        l=c['pond_location']; cs=c['catchment_summary']
        print(f"  #{c['rank']} {l['latitude']:.5f},{l['longitude']:.5f} | dep={l['depression_depth_m']}m | TWI={l['twi']} | {cs['area_hectares']}ha | {l['suitability_score_pct']}%")
