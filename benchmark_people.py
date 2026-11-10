"""Offline comparison of current detector and an operator-supplied COCO YOLOv8/v11 nano ONNX.
No model upload, API or automatic replacement. Use labels to measure accuracy.
"""
import argparse
import json
from pathlib import Path
import time
from person_analysis import settings,iou
from reports import Detector

class YoloNano:
    def __init__(self,path):
        import cv2
        self.cv=cv2;cv2.setNumThreads(1);self.net=cv2.dnn.readNetFromONNX(str(path))
    def detect(self,jpeg,config=None):
        import numpy as np
        c=settings(config);frame=self.cv.imdecode(np.frombuffer(jpeg,np.uint8),self.cv.IMREAD_COLOR)
        if frame is None:return [],None
        h,w=frame.shape[:2];ratio=min(640/w,640/h);rw,rh=round(w*ratio),round(h*ratio)
        x,y=(640-rw)//2,(640-rh)//2
        canvas=np.full((640,640,3),114,dtype=np.uint8);canvas[y:y+rh,x:x+rw]=self.cv.resize(frame,(rw,rh))
        self.net.setInput(self.cv.dnn.blobFromImage(canvas,1/255.,(640,640),swapRB=True))
        output=self.net.forward()
        if output.ndim!=3:raise ValueError('Use um ONNX COCO YOLOv8/v11 sem NMS embutido.')
        rows=output[0];rows=rows.T if rows.shape[0]==84 else rows
        if rows.shape[1]!=84:raise ValueError('Modelo deve ter 80 classes COCO e saída xywh + 80 escores.')
        found=[]
        for row in rows:
            if int(row[4:].argmax())!=0 or float(row[4])<c['confidence']:continue
            cx,cy,bw,bh=map(float,row[:4]);box=[max(0,(cx-bw/2-x)/ratio/w),max(0,(cy-bh/2-y)/ratio/h),min(1,(cx+bw/2-x)/ratio/w),min(1,(cy+bh/2-y)/ratio/h)]
            if box[2]<=box[0] or box[3]-box[1]<c['min_height']:continue
            found.append({'kind':'person','confidence':float(row[4]),'box':box})
        indices=self.cv.dnn.NMSBoxes([[r['box'][0],r['box'][1],r['box'][2]-r['box'][0],r['box'][3]-r['box'][1]] for r in found],[r['confidence'] for r in found],c['confidence'],.4)
        return ([found[int(i)] for i in np.asarray(indices).flatten()] if len(indices) else []),frame

def evaluate(detector,files,labels=None):
    samples=[];tp=fp=fn=0;detected=0
    if files:detector.detect(files[0].read_bytes()) # warmup excluded
    for file in files:
        start=time.perf_counter();rows,_=detector.detect(file.read_bytes());samples.append((time.perf_counter()-start)*1000);detected+=len(rows)
        if labels is not None:
            remaining=list(labels[file.name])
            for row in sorted(rows,key=lambda r:r['confidence'],reverse=True):
                scores=[iou(row['box'],box) for box in remaining]
                if scores and max(scores)>=.5:tp+=1;remaining.pop(scores.index(max(scores)))
                else:fp+=1
            fn+=len(remaining)
    result={'images':len(files),'detections':detected,'mean_ms':round(sum(samples)/max(1,len(samples)),2),'max_ms':round(max(samples,default=0),2)}
    if labels is not None:result.update(true_positive=tp,false_positive=fp,missed=fn,precision=round(tp/max(1,tp+fp),3),recall=round(tp/max(1,tp+fn),3))
    else:result['accuracy']='Não avaliada: forneça --labels com caixas reais de pessoas.'
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--images',type=Path,required=True);p.add_argument('--onnx',type=Path);p.add_argument('--labels',type=Path);a=p.parse_args()
    files=sorted(f for f in a.images.iterdir() if f.suffix.lower() in ('.jpg','.jpeg','.png'))[:100]
    labels=json.loads(a.labels.read_text()) if a.labels else None
    if not files:p.error('Escolha uma pasta com fotos reais de teste.')
    if labels is not None and any(f.name not in labels for f in files):p.error('Os rótulos devem incluir cada foto; use [] quando não houver pessoa.')
    results={'current':evaluate(Detector(),files,labels)}
    if a.onnx:results['candidate_onnx']=evaluate(YoloNano(a.onnx),files,labels)
    print(json.dumps(results,ensure_ascii=False,indent=2))
