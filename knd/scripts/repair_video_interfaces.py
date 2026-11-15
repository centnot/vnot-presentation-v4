"""Local, repeatable repairs of interface inserts. No GPU or old-project writes.

Moving remote-monitor insert: anchored planar tracking from the first frame.
Unstable generated close-ups: clean photographic plates, with the original
animation retained before a hard camera cut. Text is never cross-faded over UI.
"""
from itertools import islice
from pathlib import Path
import json
import shutil
import subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import gaussian_filter1d
from project_paths import ROOT, INTERFACES, previous_media, raw_media, font_path

OUT = ROOT / 'build/video-review/repaired'
OUT.mkdir(parents=True, exist_ok=True)
HD3 = HD2 = raw_media()
SHOTS = INTERFACES
SCALE = 1890 / 1344

def read(path, index):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, result = cap.read()
    cap.release()
    if not ok:
        raise ValueError((str(path), index))
    return result

def load_image(path):
    return cv2.cvtColor(np.asarray(Image.open(path).convert('RGB')), cv2.COLOR_RGB2BGR)

def composite(frame, insert, quad, occlude=False, ink=False, notch=False):
    """Opaque/clipped screen, or multiply ink onto the actual blank book paper."""
    height, width = frame.shape[:2]
    ih, iw = insert.shape[:2]
    quad = np.float32(quad) * SCALE
    transform = cv2.getPerspectiveTransform(np.float32([[0,0],[iw,0],[iw,ih],[0,ih]]), quad)
    mask = np.ones((ih, iw), np.float32)
    mask = cv2.copyMakeBorder(mask[2:-2,2:-2],2,2,2,2,cv2.BORDER_CONSTANT,value=0)
    mask = cv2.GaussianBlur(mask,(0,0),1)
    alpha = cv2.warpPerspective(mask, transform, (width,height))
    if occlude:
        # Feathers remain in front of the phone; the pasted UI cannot cover them.
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        inside = alpha > .2
        saturation = cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)[...,1]
        dark = ((gray < 150) & (saturation < 110) & inside).astype(np.uint8)
        left = np.zeros_like(dark)
        lq = quad.copy(); lq[1] = quad[0] + .30*(quad[1]-quad[0]); lq[2] = quad[3] + .30*(quad[2]-quad[3])
        cv2.fillConvexPoly(left,np.int32(lq),1)
        top_clear=np.zeros_like(left)
        tq=quad.copy();tq[2]=quad[1]+.28*(quad[2]-quad[1]);tq[3]=quad[0]+.28*(quad[3]-quad[0])
        cv2.fillConvexPoly(top_clear,np.int32(tq),1)
        left[top_clear>0]=0
        core=dark & left
        edge=np.zeros_like(left)
        eq=quad.copy();eq[1]=quad[0]+.025*(quad[1]-quad[0]);eq[2]=quad[3]+.025*(quad[2]-quad[3])
        cv2.fillConvexPoly(edge,np.int32(eq),1)
        _,labels=cv2.connectedComponents(core)
        touching=set(np.unique(labels[(edge>0)&(core>0)]))-{0}
        occ = cv2.dilate(np.isin(labels,list(touching)).astype(np.uint8),np.ones((3,3),np.uint8))
        alpha *= 1-cv2.GaussianBlur(occ.astype(np.float32),(0,0),.7)
    if notch:
        # Retain the actual phone notch and rounded top corners.
        top = np.zeros_like(alpha)
        tq = quad.copy(); tq[2] = quad[1]+.07*(quad[2]-quad[1]); tq[3] = quad[0]+.07*(quad[3]-quad[0])
        cv2.fillConvexPoly(top,np.int32(tq),1)
        alpha *= 1-((cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)<100)&(top>0)).astype(np.float32)
    if ink:
        multiplier = np.clip(insert.astype(np.float32) / np.float32([226,237,243]),0,1)
        warped = cv2.warpPerspective(multiplier,transform,(width,height),borderValue=(1,1,1))
        # Only dark ink changes the plate, preserving paper shading and curvature.
        alpha *= (cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)>135)
        result = frame.astype(np.float32)*(1-alpha[...,None]+alpha[...,None]*warped)
    else:
        warped = cv2.warpPerspective(insert,transform,(width,height))
        result = frame*(1-alpha[...,None])+warped*alpha[...,None]
    return np.uint8(np.clip(result,0,255))

def write(path, frames, size=(1890,1080), maxrate=None):
    # maxrate caps noisy upscales (fine SeedVR2 grain) so the clip streams from GitHub Pages without stalls.
    rate = ['-preset','slow','-crf','19','-maxrate',maxrate,'-bufsize',str(2*int(maxrate[:-1]))+'M'] if maxrate else ['-preset','fast','-crf','17']
    pipe = subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{size[0]}x{size[1]}','-r','24','-i','-','-an','-c:v','libx264',*rate,'-pix_fmt','yuv420p','-movflags','+faststart',str(path)],stdin=subprocess.PIPE)
    count = 0
    for f in frames:
        pipe.stdin.write(f.tobytes()); count += 1
    pipe.stdin.close()
    if pipe.wait():
        raise RuntimeError(f'Encoding failed: {path}')
    print(path.name,count,flush=True)

def closeup(name, source, cut, plate_index, image_path, quad, trim=0, ink=False, occlude=False, notch=False):
    plate = read(source,plate_index)
    insert = load_image(image_path)
    if ink:
        mid=insert.shape[1]//2
        plate=composite(plate,insert[:,:mid],quad[0],ink=True)
        plate=composite(plate,insert[:,mid:],quad[1],ink=True)
    else:
        plate=composite(plate,insert,quad,occlude=occlude,notch=notch)
    cv2.imencode('.jpg',plate)[1].tofile(OUT/f'{name}-plate.jpg')  # cv2.imwrite fails on non-ASCII Windows paths
    def frames():
        cap=cv2.VideoCapture(str(source)); i=0
        while True:
            ok,f=cap.read()
            if not ok:break
            if i>=trim:
                yield f if i<cut else plate
            i+=1
        cap.release()
    write(OUT/f'{name}.mp4',frames())

def track_between(gray, a, b, qa, qb):
    """LK camera motion, corrected by independent measured anchors at both ends."""
    q=np.float32(qa); values=[q.copy()]
    for i in range(a+1,b+1):
        mask=np.zeros_like(gray[i-1]);cv2.fillConvexPoly(mask,np.int32(q),255)
        mask=cv2.dilate(mask,np.ones((21,21),np.uint8))
        points=cv2.goodFeaturesToTrack(gray[i-1],500,.01,4,mask=mask)
        if points is None or len(points)<8:
            raise RuntimeError(f'Monitor tracking lost at {i}')
        dest,s1,_=cv2.calcOpticalFlowPyrLK(gray[i-1],gray[i],points,None,winSize=(25,25),maxLevel=4)
        back,s2,_=cv2.calcOpticalFlowPyrLK(gray[i],gray[i-1],dest,None,winSize=(25,25),maxLevel=4)
        ok=(s1.ravel()>0)&(s2.ravel()>0)&(np.linalg.norm(points-back,axis=2).ravel()<1.2)
        if ok.sum()<8:raise RuntimeError(f'Too few tracking points at {i}')
        matrix,inliers=cv2.findHomography(points[ok],dest[ok],cv2.RANSAC,2.0)
        if matrix is None:raise RuntimeError(f'No homography at {i}')
        q=cv2.perspectiveTransform(q.reshape(-1,1,2),matrix).reshape(4,2)
        values.append(q.copy())
    arr=np.asarray(values)
    # A short segment cannot accumulate drift beyond its measured end position.
    arr += np.linspace(0,1,len(arr))[:,None,None]*(np.float32(qb)-arr[-1])
    return arr

def remote():
    source=HD3/'V6_1344x768_s602_00001__1080p_00001_.mp4'
    anchors={
        0:[[821,193],[906,190],[888,412],[805,401]],
        24:[[741,181],[853,178],[834,429],[721,418]],
        48:[[558,157],[732,151],[710,470],[541,457]],
        72:[[337,113],[594,109],[575,544],[320,532]],
        96:[[165,74],[500,67],[489,623],[151,607]],
        120:[[85,47],[467,45],[457,662],[70,653]],
        144:[[73,44],[462,42],[453,667],[59,660]],
        174:[[73,44],[461,42],[450,665],[60,659]],
    }
    cap=cv2.VideoCapture(str(source));gray=[]
    while True:
        ok,f=cap.read()
        if not ok:break
        gray.append(cv2.cvtColor(cv2.resize(f,(1344,768)),cv2.COLOR_BGR2GRAY))
    cap.release()
    quads=np.zeros((len(gray),4,2),np.float32)
    keys=list(anchors)
    for a,b in zip(keys,keys[1:]):quads[a:b+1]=track_between(gray,a,b,anchors[a],anchors[b])
    quads=gaussian_filter1d(quads,.65,axis=0,mode='nearest')
    quads[0]=anchors[0];quads[-1]=anchors[174]
    (OUT/'remote-quads.json').write_text(json.dumps(quads.tolist()),encoding='utf-8')
    original=load_image(SHOTS/'mp_split.jpg')
    left=original[8:-8,8:790]
    canvas=np.full((1240,left.shape[1],3),255,np.uint8)
    canvas[:left.shape[0]]=left
    def frames():
        cap=cv2.VideoCapture(str(source));i=0
        while True:
            ok,f=cap.read()
            if not ok:break
            yield composite(f,canvas,quads[i]);i+=1
        cap.release()
    write(OUT/'remote.mp4',frames())

def hold_clean_book():
    source=previous_media()/'V1_s102.mp4'
    plate=read(source,174)
    def frames():
        cap=cv2.VideoCapture(str(source));i=0
        while True:
            ok,f=cap.read()
            if not ok:break
            yield f if i<140 else plate
            i+=1
        cap.release()
    write(OUT/'ervk.mp4',frames())

def monitoring():
    # 13.11.2026 take: the owl is clearly frightened by the scheme (KND_fear s4101, SeedVR2 1080p).
    source=HD3/'KND_fear_1344x768_s4101_00001__1080p_00001_.mp4'
    quad=[[61.9,131.6],[686.3,119.4],[686.1,462.2],[61.9,476.0]]
    scheme=load_image(SHOTS/'scheme.jpg')
    # The screen is wider than the scheme: fit it by height on a white slide instead of stretching.
    width=round(scheme.shape[0]*(quad[1][0]-quad[0][0])/(quad[3][1]-quad[0][1]))
    insert=np.full((scheme.shape[0],width,3),255,np.uint8)
    left=(width-scheme.shape[1])//2
    insert[:,left:left+scheme.shape[1]]=scheme
    def frames():
        cap=cv2.VideoCapture(str(source))
        while True:
            ok,f=cap.read()
            if not ok:break
            yield composite(f,insert,quad)
        cap.release()
    write(OUT/'monitoring.mp4',frames())

def frames_of(path):
    cap=cv2.VideoCapture(str(path))
    while True:
        ok,f=cap.read()
        if not ok:break
        yield f
    cap.release()

def worker_box(frame):
    """Full-body box of the roof worker: snow separates the saturated jacket and the dark trousers."""
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    h,s,v=hsv[...,0],hsv[...,1],hsv[...,2]
    # Orange jacket and yellow helmet anchor the person; the city lights are small and on the left.
    warm=((h>=5)&(h<=35)&(s>=120)&(v>=120)).astype(np.uint8)
    warm=cv2.morphologyEx(warm,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    n,_,stats,_=cv2.connectedComponentsWithStats(warm)
    best=max(range(1,n),key=lambda k:stats[k,cv2.CC_STAT_AREA]*(stats[k,cv2.CC_STAT_LEFT]>700))
    x,y,w,hh=stats[best,:4]
    cx=x+w/2
    person=((s>=70)|(v<110)).astype(np.uint8)
    rows=person[:,int(cx-.6*w):int(cx+.6*w)].sum(1)
    bottom,gap=y+hh,0
    for r in range(y+hh,min(frame.shape[0],y+6*hh)):
        if rows[r]>=3:bottom,gap=r,0
        else:
            gap+=1
            # Reflective stripes and snow on the boots are thinner than the snow below the feet.
            if gap>30:break
    near=warm[max(0,y-int(1.2*hh)):y+hh,max(0,x-int(.3*w)):x+w+int(.3*w)]
    ys=np.where(near.any(1))[0]
    top=max(0,y-int(1.2*hh))+int(ys.min()) if len(ys) else y
    bottom+=int(.06*(bottom-top))  # snow-covered boots below the dark trousers
    x0=int(cx-1.3*w)
    cols=set(np.where(person[top:bottom+1,x0:int(cx+1.3*w)].mean(0)>=.22)[0].tolist())
    # Contiguous body columns around the centre: the thin shovel handle stays outside the box.
    left=right=int(cx)-x0
    while left-1 in cols or left-2 in cols:left-=1
    while right+1 in cols or right+2 in cols:right+=1
    pad=.05*(right-left)
    return [x0+left-pad,top-pad,x0+right+pad,bottom+pad]

def detection(frame, box, label, alpha):
    """AI-camera style box with corner marks and a label; alpha 0..1 animates its appearance."""
    if alpha<=0:return frame
    x0,y0,x1,y1=box
    grow=1+.12*(1-alpha)
    cx,cy=(x0+x1)/2,(y0+y1)/2
    x0,x1=cx+(x0-cx)*grow,cx+(x1-cx)*grow
    y0,y1=cy+(y0-cy)*grow,cy+(y1-cy)*grow
    red=(229,57,53)
    layer=Image.new('RGBA',(frame.shape[1],frame.shape[0]),(0,0,0,0))
    draw=ImageDraw.Draw(layer)
    draw.rectangle([x0,y0,x1,y1],fill=red+(22,),outline=red+(255,),width=4)
    # Corner marks as solid L-shapes that overlap the outline exactly.
    c,t=.22*min(x1-x0,y1-y0),9
    for bx,by,sx,sy in [(x0,y0,1,1),(x1,y0,-1,1),(x0,y1,1,-1),(x1,y1,-1,-1)]:
        hx=sorted([bx,bx+sx*c]);hy=sorted([by,by+sy*t]);vx=sorted([bx,bx+sx*t]);vy=sorted([by,by+sy*c])
        draw.rectangle([hx[0],hy[0],hx[1],hy[1]],fill=red+(255,))
        draw.rectangle([vx[0],vy[0],vx[1],vy[1]],fill=red+(255,))
    font=ImageFont.truetype(str(font_path(bold=True)),38)
    left,top,right,bottom=draw.textbbox((0,0),label,font=font)
    tw,th=right-left,bottom-top
    lx=min(x0-2,frame.shape[1]-tw-40)
    ly=y0-th-26 if y0-th-26>10 else y0+8
    draw.rectangle([lx,ly,lx+tw+28,ly+th+20],fill=red+(255,))
    draw.text((lx+14-left,ly+10-top),label,font=font,fill=(255,255,255,255))
    rgba=np.asarray(layer).astype(np.float32)
    a=rgba[...,3:]/255*alpha
    result=frame.astype(np.float32)*(1-a)+rgba[...,2::-1]*a
    return np.uint8(np.clip(result,0,255))

def ai_cameras():
    # 13.11.2026: the owl spots something on the monitoring screen (KND_cameras s4202, SeedVR2 1080p) and points;
    # hard cut to the roof camera, where an AI detection box marks the worker at height without a harness.
    owl=HD3/'KND_cameras_1344x768_s4202_00001__1080p_00001_.mp4'
    roof=previous_media()/'V9_s910_v4.mp4'
    cut,first,last,delay=72,50,152,8
    raw=[worker_box(f) for i,f in enumerate(frames_of(roof)) if first<=i<=last]
    boxes=gaussian_filter1d(np.float32(raw),2.5,axis=0,mode='nearest')
    (OUT/'ai-cameras-boxes.json').write_text(json.dumps(boxes.round(1).tolist()),encoding='utf-8')
    def frames():
        for i,f in enumerate(frames_of(owl)):
            if i>=cut:break
            yield f
        for i,f in enumerate(frames_of(roof)):
            if first<=i<=last:
                k=i-first
                yield detection(f,boxes[k],'Работа на высоте без страховки',min(1,max(0,(k-delay+1)/4)))
    write(OUT/'ai-cameras.mp4',frames())

def gold(img):
    hsv=cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
    return ((hsv[...,0]>=10)&(hsv[...,0]<=35)&(hsv[...,1]>=80)&(hsv[...,2]>=120)).astype(np.uint8)

def name_tape(source, ref, window, until=None, follow=None, text='РОСТРУД'):
    """Replace garbled gold lettering on the owl's name tape, tracked frame to frame from a reference frame.
    From `follow` the template is taken from the previous frame (the owl leans and comes closer);
    frames after `until` pass unchanged: there the owl moves fast and the tape is a blurred smear anyway."""
    plate=read(source,ref)
    x0,y0,x1,y1=window
    n,_,st,_=cv2.connectedComponentsWithStats(gold(plate[y0:y1,x0:x1]))
    comps=[k for k in range(1,n) if st[k,cv2.CC_STAT_AREA]>=2 and st[k,cv2.CC_STAT_HEIGHT]<=18]
    bx0=min(st[k,0] for k in comps)+x0;by0=min(st[k,1] for k in comps)+y0
    bx1=max(st[k,0]+st[k,2] for k in comps)+x0;by1=max(st[k,1]+st[k,3] for k in comps)+y0
    letters=plate[by0:by1,bx0:bx1]
    colour=np.percentile(letters[gold(letters)>0],80,axis=0)
    pad,reach=30,30
    template=cv2.cvtColor(plate[by0-pad:by1+pad,bx0-pad:bx1+pad],cv2.COLOR_BGR2GRAY)
    offsets,dx,dy=[],0,0
    for i,f in enumerate(frames_of(source)):
        if until is not None and i>until:break
        sx,sy=max(0,bx0-pad-reach+dx),max(0,by0-pad-reach+dy)
        area=cv2.cvtColor(f[sy:by1+pad+reach+dy,sx:bx1+pad+reach+dx],cv2.COLOR_BGR2GRAY)
        _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(area,template,cv2.TM_CCOEFF_NORMED))
        if score<.6:raise RuntimeError(f'Name tape tracking lost at frame {i}: {score:.2f}')
        dx,dy=loc[0]+sx-(bx0-pad),loc[1]+sy-(by0-pad)
        offsets.append([dx,dy])
        if follow is not None and i>=follow:
            template=cv2.cvtColor(f[by0-pad+dy:by1+pad+dy,bx0-pad+dx:bx1+pad+dx],cv2.COLOR_BGR2GRAY)
    # No temporal smoothing: matches are exact to a pixel, and smoothing lags when the owl crouches.
    # Lettering rendered large and reduced to the tape size, slightly softened like embroidery.
    font=ImageFont.truetype(str(font_path(bold=True)),200)
    l,t,r,b=ImageDraw.Draw(Image.new('L',(1,1))).textbbox((0,0),text,font=font)
    big=Image.new('L',(r-l,b-t));ImageDraw.Draw(big).text((-l,-t),text,font=font,fill=255)
    w,h=bx1-bx0,by1-by0
    small=big.resize((w*4,h*4),Image.LANCZOS).resize((w,h),Image.LANCZOS).filter(ImageFilter.GaussianBlur(.35))
    alpha=np.asarray(small).astype(np.float32)[...,None]/255
    for i,f in enumerate(frames_of(source)):
        if i<len(offsets):
            dx,dy=offsets[i]
            vx,vy=np.subtract(offsets[i],offsets[i-1]) if i else (0,0)
            # Fast moves blur the frame; the new lettering gets the same motion blur, and a taller patch.
            m=max(3,int(abs(vy)*.6)+3)
            X0,Y0,X1,Y1=bx0+dx-3,by0+dy-m,bx1+dx+3,by1+dy+m
            patch=f[Y0:Y1,X0:X1]
            mask=cv2.dilate(gold(patch),np.ones((3,3),np.uint8),iterations=2)
            f[Y0:Y1,X0:X1]=cv2.inpaint(patch,mask*255,3,cv2.INPAINT_TELEA)
            a=alpha
            if abs(vx)+abs(vy)>6:
                k=int(np.hypot(vx,vy)*.6)|1
                kernel=np.zeros((k,k),np.float32)
                cv2.line(kernel,(k//2-int(vx*.3),k//2-int(vy*.3)),(k//2+int(vx*.3),k//2+int(vy*.3)),1,1)
                a=cv2.copyMakeBorder(alpha[...,0],k,k,k,k,cv2.BORDER_CONSTANT)
                a=cv2.filter2D(a,-1,kernel/kernel.sum())[...,None]
                ya,xa=by0+dy-k,bx0+dx-k
            else:
                ya,xa=by0+dy,bx0+dx
            region=f[ya:ya+a.shape[0],xa:xa+a.shape[1]].astype(np.float32)
            f[ya:ya+a.shape[0],xa:xa+a.shape[1]]=np.uint8(region*(1-a)+colour*a)
        yield f

def drones():
    # The owl takes off with the drone and flies over the site (V8_s802_v3; the flight stays, decision of 15.11).
    # The clip ends at frame 102 while the owl glides next to the drone: later frames smear it into the roof,
    # and the last frame stays on screen. The garbled name tape is replaced until the jump blurs it (frames 0-40).
    source=previous_media()/'V8_s802_v3.mp4'
    write(OUT/'drones.mp4',islice(name_tape(source,5,(560,405,660,450),until=40,follow=34),103),maxrate='8M')

def main():
    closeup('assistant',HD2/'V10_1344x768_s1001_00001__1080p_00001_.mp4',98,108,
            INTERFACES/'v3_spread_ai.png',
            [[[309,71],[666,112],[666,644],[300,659]],[[670,112],[1048,85],[1049,655],[670,644]]],trim=48,ink=True)
    closeup('onsite',HD3/'V5_1344x768_s502_00001__1080p_00001_.mp4',102,174,
            SHOTS/'mp_checklist.png',[[265,193],[464,198],[456,551],[257,549]],occlude=True)
    closeup('execution',HD3/'V7_1344x768_s703_00001__1080p_00001_.mp4',118,174,
            SHOTS/'mp_checklist_photo.png',[[566,217],[727,219],[725,587],[560,586]],notch=True)
    remote()
    hold_clean_book()
    monitoring()
    ai_cameras()
    drones()
    from repair_erknm import main as repair_erknm
    repair_erknm()

if __name__=='__main__':
    main()
