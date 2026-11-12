"""Stabilize the owl shot and rebuild the frontal monitor from the clean source.

Tracks stationary office features, keeping the owl animation intact. Replaces
the entire display, including generated browser chrome and the old taskbar.
Writes only KND review outputs; it never modifies the source project.
"""
from pathlib import Path
import json
import subprocess
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from project_paths import ROOT, RAW_MEDIA, INTERFACES

SOURCE=RAW_MEDIA/'V3_1344x768_s313_00001__1080p_00001_.mp4'
SHOT=INTERFACES/'erknm_card.jpg'
OUT=ROOT/'build/video-review/repaired'
SCALE=1890/1344
CUT=124

def camera_path():
    capture=cv2.VideoCapture(str(SOURCE));gray=[]
    for _ in range(CUT):
        ok,frame=capture.read()
        if not ok:raise RuntimeError('Incomplete first shot')
        gray.append(cv2.cvtColor(cv2.resize(frame,(1344,768)),cv2.COLOR_BGR2GRAY))
    capture.release()
    mask=np.zeros_like(gray[0])
    mask[:85,:]=255;mask[:640,:310]=255;mask[:640,1000:]=255
    points=cv2.goodFeaturesToTrack(gray[0],800,.01,5,mask=mask)
    original=points.copy()
    matrices=[np.float64([[1,0,0],[0,1,0]])]
    for i in range(1,CUT):
        dest,s1,error=cv2.calcOpticalFlowPyrLK(gray[i-1],gray[i],points,None,winSize=(31,31),maxLevel=4)
        back,s2,_=cv2.calcOpticalFlowPyrLK(gray[i],gray[i-1],dest,None,winSize=(31,31),maxLevel=4)
        keep=(s1[:,0]>0)&(s2[:,0]>0)&(np.linalg.norm(back[:,0]-points[:,0],axis=1)<.7)&(error[:,0]<25)
        points,original=dest[keep],original[keep]
        matrix,inliers=cv2.estimateAffinePartial2D(original[:,0],points[:,0],method=cv2.RANSAC,ransacReprojThreshold=1.3,maxIters=3000,confidence=.999)
        if matrix is None or int(inliers.sum())<30:raise RuntimeError(f'Unreliable camera track at {i}')
        matrices.append(matrix)
    matrices=np.asarray(matrices)
    center=np.array([672,384,1.])
    centers=matrices@center
    parameters=np.column_stack([centers[:,0]-672,centers[:,1]-384,np.arctan2(matrices[:,1,0],matrices[:,0,0]),np.hypot(matrices[:,0,0],matrices[:,1,0])])
    smooth=gaussian_filter1d(parameters,6,axis=0,mode='nearest')
    corrections=[]
    for matrix,(tx,ty,angle,scale) in zip(matrices,smooth):
        a,b=scale*np.cos(angle),scale*np.sin(angle)
        target=np.array([[a,-b,672+tx-a*672+b*384],[b,a,384+ty-b*672-a*384],[0,0,1.]])
        correction=(target@np.linalg.inv(np.vstack([matrix,[0,0,1]])))[:2]
        correction[:,2]*=SCALE
        corrections.append(correction)
    return corrections,parameters,smooth

def monitor_plate():
    capture=cv2.VideoCapture(str(SOURCE));capture.set(cv2.CAP_PROP_POS_FRAMES,174)
    ok,plate=capture.read();capture.release()
    if not ok:raise RuntimeError('No monitor reference')
    height,width=plate.shape[:2]
    source=np.float32([[222,98],[1119,98],[1132,650],[205,650]])*SCALE
    target=np.float32([[209,98],[1131,98],[1131,650],[209,650]])*SCALE
    matrix=cv2.getPerspectiveTransform(source,target)
    plate=cv2.warpPerspective(plate,matrix,(width,height),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
    valid=cv2.warpPerspective(np.full((height,width),255,np.uint8),matrix,(width,height),flags=cv2.INTER_NEAREST)
    x0,y0=np.floor(target[0]).astype(int);x1,y1=np.ceil(target[2]).astype(int)
    plate[y0-2:y1+2,x0-2:x1+2]=[8,9,10]
    insert=cv2.imread(str(SHOT))
    ratio=min((x1-x0)/insert.shape[1],(y1-y0)/insert.shape[0])
    insert=cv2.resize(insert,(x1-x0,round(insert.shape[0]*ratio)),interpolation=cv2.INTER_LANCZOS4)
    canvas=np.full((y1-y0,x1-x0,3),255,np.uint8);canvas[:insert.shape[0]]=insert
    plate[y0:y1,x0:x1]=canvas
    # Remove all pixels created outside the original frame during rectification.
    for margin in range(1,100):
        vertical=int(np.ceil(margin*height/width))
        if np.all(valid[vertical:-vertical,margin:-margin]==255):break
    else:raise RuntimeError('Rectification needs excessive crop')
    plate=cv2.resize(plate[vertical:-vertical,margin:-margin],(width,height),interpolation=cv2.INTER_CUBIC)
    return plate,dict(source=source.tolist(),target=target.tolist(),border_crop=[margin,vertical])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    corrections,parameters,smooth=camera_path()
    plate,geometry=monitor_plate()
    cv2.imwrite(str(OUT/'erknm-monitor-front.jpg'),plate)
    pipe=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s','1890x1080','-r','24','-i','-','-an','-c:v','libx264','-profile:v','high','-level:v','4.1','-crf','17','-preset','fast','-pix_fmt','yuv420p','-movflags','+faststart',str(OUT/'erknm.mp4')],stdin=subprocess.PIPE)
    cap=cv2.VideoCapture(str(SOURCE));index=0
    while True:
        ok,frame=cap.read()
        if not ok:break
        if index<CUT:
            frame=cv2.warpAffine(frame,corrections[index],(1890,1080),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
            frame=cv2.resize(frame[8:-8,14:-14],(1890,1080),interpolation=cv2.INTER_CUBIC)
        else:frame=plate
        pipe.stdin.write(frame.tobytes());index+=1
    cap.release();pipe.stdin.close()
    if pipe.wait() or index!=175:raise RuntimeError(f'Incomplete render ({index} frames)')
    (OUT/'erknm-repair.json').write_text(json.dumps(dict(frames=index,cut_frame=CUT,geometry=geometry,camera=parameters.tolist(),smooth=smooth.tolist(),corrections=[m.tolist() for m in corrections]),indent=2),encoding='utf-8')
    print(f'ERKNM: stabilized {CUT} animated frames; frontal monitor for {index-CUT} frames; crop {geometry["border_crop"]}')

if __name__=='__main__':main()
