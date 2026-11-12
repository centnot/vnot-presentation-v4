"""Local, repeatable repairs of interface inserts. No GPU or old-project writes.

Moving remote-monitor insert: anchored planar tracking from the first frame.
Unstable generated close-ups: clean photographic plates, with the original
animation retained before a hard camera cut. Text is never cross-faded over UI.
"""
from pathlib import Path
import json
import shutil
import subprocess
import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from project_paths import ROOT, INTERFACES, previous_media, raw_media

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

def write(path, frames, size=(1890,1080)):
    pipe = subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{size[0]}x{size[1]}','-r','24','-i','-','-an','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],stdin=subprocess.PIPE)
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
    source=HD3/'V4_1344x768_s406_00001__1080p_00001_.mp4'
    insert=load_image(SHOTS/'scheme.jpg')
    def frames():
        cap=cv2.VideoCapture(str(source))
        while True:
            ok,f=cap.read()
            if not ok:break
            # Remove the generated pseudo-label outside the projected screen.
            x0,y0,x1,y1=np.int32(np.array([660,458,792,520])*SCALE)
            patch=f[y0:y1,x0:x1].copy()
            mask=np.zeros(patch.shape[:2],np.uint8)
            poly=np.float32([[684,478],[775,480],[775,503],[684,501]])*SCALE-[x0,y0]
            cv2.fillConvexPoly(mask,np.int32(poly),255)
            f[y0:y1,x0:x1]=cv2.inpaint(patch,mask,5,cv2.INPAINT_TELEA)
            yield composite(f,insert,[[40,27],[699,79],[695,478],[32,478]])
        cap.release()
    write(OUT/'monitoring.mp4',frames())

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
    from repair_erknm import main as repair_erknm
    repair_erknm()

if __name__=='__main__':
    main()
