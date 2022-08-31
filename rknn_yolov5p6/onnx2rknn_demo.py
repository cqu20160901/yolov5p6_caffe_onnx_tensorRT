import os
import urllib
import traceback
import time
import sys
import numpy as np
import cv2
from rknn.api import RKNN
from math import exp


ONNX_MODEL = 'yolov5_p6_512x512_6head.onnx'
RKNN_MODEL = 'yolov5_p6_512x512_6head.rknn'
DATASET = './dataset.txt'

QUANTIZE_ON = True


CLASSES = ['car', 'ped']
class_num = len(CLASSES)
anchor_num = 3
output_head = 6
cell_size = [[64, 64], [32, 32], [16, 16], [8, 8], [4, 4], [2, 2]]
anchor_size = [
    [[16, 14], [9, 30], [25, 22]],
    [[18, 52], [40, 32], [27, 83]],
    [[55, 46], [82, 60], [41, 122]],
    [[100, 84], [75, 162], [138, 110]],
    [[190, 158], [121, 251], [259, 246]],
    [[191, 378], [451, 269], [683, 393]]
]

stride = [8, 16, 32, 64, 128, 256]
grid_cell = np.zeros(shape=(output_head, 64, 64, 2))

nms_thre = 0.45
obj_thre = [0.4, 0.4]

input_imgW = 512
input_imgH = 512


class DetectBox:
    def __init__(self, classId, score, xmin, ymin, xmax, ymax):
        self.classId = classId
        self.score = score
        self.xmin = xmin
        self.ymin = ymin
        self.xmax = xmax
        self.ymax = ymax


def grid_cell_init():
    for index in range(output_head):
        for w in range(cell_size[index][1]):
            for h in range(cell_size[index][0]):
                grid_cell[index][h][w][0] = w
                grid_cell[index][h][w][1] = h


def IOU(xmin1, ymin1, xmax1, ymax1, xmin2, ymin2, xmax2, ymax2):
    xmin = max(xmin1, xmin2)
    ymin = max(ymin1, ymin2)
    xmax = min(xmax1, xmax2)
    ymax = min(ymax1, ymax2)

    innerWidth = xmax - xmin
    innerHeight = ymax - ymin

    innerWidth = innerWidth if innerWidth > 0 else 0
    innerHeight = innerHeight if innerHeight > 0 else 0

    innerArea = innerWidth * innerHeight

    area1 = (xmax1 - xmin1) * (ymax1 - ymin1)
    area2 = (xmax2 - xmin2) * (ymax2 - ymin2)

    total = area1 + area2 - innerArea

    return innerArea / total


def NMS(detectResult):
    predBoxs = []

    sort_detectboxs = sorted(detectResult, key=lambda x: x.score, reverse=True)

    for i in range(len(sort_detectboxs)):
        xmin1 = sort_detectboxs[i].xmin
        ymin1 = sort_detectboxs[i].ymin
        xmax1 = sort_detectboxs[i].xmax
        ymax1 = sort_detectboxs[i].ymax
        classId = sort_detectboxs[i].classId

        if sort_detectboxs[i].classId != -1:
            predBoxs.append(sort_detectboxs[i])
            for j in range(i + 1, len(sort_detectboxs), 1):
                if classId == sort_detectboxs[j].classId:
                    xmin2 = sort_detectboxs[j].xmin
                    ymin2 = sort_detectboxs[j].ymin
                    xmax2 = sort_detectboxs[j].xmax
                    ymax2 = sort_detectboxs[j].ymax
                    iou = IOU(xmin1, ymin1, xmax1, ymax1, xmin2, ymin2, xmax2, ymax2)
                    if iou > nms_thre:
                        sort_detectboxs[j].classId = -1
    return predBoxs


def sigmoid(x):
    return 1 / (1 + exp(-x))


def postprocess(out, img_h, img_w):
    print('postprocess ... ')

    detectResult = []

    output = []
    for i in range(len(out)):
        output.append(out[i].reshape((-1)))

    gs = 4 + 1 + class_num
    scale_h = img_h / input_imgH
    scale_w = img_w / input_imgW

    for head in range(output_head):
        y = output[head]
        for h in range(cell_size[head][0]):

            for w in range(cell_size[head][1]):
                for a in range(anchor_num):
                    conf_scale = sigmoid(y[((a * gs + 4) * cell_size[head][0] * cell_size[head][1]) + h * cell_size[head][1] + w])
                    for cl in range(class_num):
                        conf = sigmoid(y[((a * gs + 5 + cl) * cell_size[head][0] * cell_size[head][1]) + h * cell_size[head][1] + w]) * conf_scale

                        if conf > obj_thre[cl]:
                            bx = (sigmoid(y[((a * gs + 0) * cell_size[head][0] * cell_size[head][1]) + h * cell_size[head][1] + w]) * 2.0 - 0.5 + grid_cell[head][h][w][0]) * stride[head]
                            by = (sigmoid(y[((a * gs + 1) * cell_size[head][0] * cell_size[head][1]) + h * cell_size[head][1] + w]) * 2.0 - 0.5 + grid_cell[head][h][w][1]) * stride[head]
                            bw = pow((sigmoid(y[((a * gs + 2) * cell_size[head][0] * cell_size[head][1]) + h * cell_size[head][1] + w]) * 2), 2) * anchor_size[head][a][0]
                            bh = pow((sigmoid(y[((a * gs + 3) * cell_size[head][0] * cell_size[head][1]) + h * cell_size[head][1] + w]) * 2), 2) * anchor_size[head][a][1]

                            xmin = (bx - bw / 2) * scale_w
                            ymin = (by - bh / 2) * scale_h
                            xmax = (bx + bw / 2) * scale_w
                            ymax = (by + bh / 2) * scale_h

                            xmin = xmin if xmin > 0 else 0
                            ymin = ymin if ymin > 0 else 0
                            xmax = xmax if xmax < img_w else img_w
                            ymax = ymax if ymax < img_h else img_h

                            if xmin >= 0 and ymin >= 0 and xmax <= img_w and ymax <= img_h:
                                box = DetectBox(cl, conf, xmin, ymin, xmax, ymax)
                                detectResult.append(box)

    # NMS 过程
    print('detectResult:', len(detectResult))
    predBox = NMS(detectResult)
    return predBox

def export_rknn_inference(img):
    # Create RKNN object
    rknn = RKNN(verbose=True)

    # pre-process config
    print('--> Config model')
    rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]])
    print('done')

    # Load ONNX model
    print('--> Loading model')
    ret = rknn.load_onnx(model=ONNX_MODEL, outputs=['output1', 'output2', 'output3', 'output4', 'output5', 'output6'])
    if ret != 0:
        print('Load model failed!')
        exit(ret)
    print('done')

    # Build model
    print('--> Building model')
    ret = rknn.build(do_quantization=QUANTIZE_ON, dataset=DATASET)
    if ret != 0:
        print('Build model failed!')
        exit(ret)
    print('done')
    
    # Export RKNN model

    print('--> Export rknn model')
    ret = rknn.export_rknn(RKNN_MODEL)
    if ret != 0:
        print('Export rknn model failed!')
        exit(ret)
    print('done')

    # Init runtime environment
    print('--> Init runtime environment')
    ret = rknn.init_runtime()
    # ret = rknn.init_runtime('rk3566')
    if ret != 0:
        print('Init runtime environment failed!')
        exit(ret)
    print('done')

    # Inference
    print('--> Running model')
    outputs = rknn.inference(inputs=[img])
    rknn.release()
    print('done')
    
    return outputs
    

if __name__ == '__main__':
    print('This is main ....')
    grid_cell_init()
    
    # Set inputs
    img_path = 'test.jpg'
    origimg = cv2.imread(img_path)
    origimg = cv2.cvtColor(origimg, cv2.COLOR_BGR2RGB)
    img_h, img_w = origimg.shape[:2]
    img = cv2.resize(origimg, (input_imgW, input_imgH))

    outputs = export_rknn_inference(img)

    # postprocess
    out = []
    for i in range(len(outputs)):
        print(outputs[i].shape)
        out.append(outputs[i])
    
    predbox = postprocess(out, img_h, img_w)

    print(len(predbox))

    for i in range(len(predbox)):
        xmin = int(predbox[i].xmin)
        ymin = int(predbox[i].ymin)
        xmax = int(predbox[i].xmax)
        ymax = int(predbox[i].ymax)
        classId = predbox[i].classId
        score = predbox[i].score

        cv2.rectangle(origimg, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
        ptext = (xmin, ymin)
        title = CLASSES[classId] + "%.2f" % score
        cv2.putText(origimg, title, ptext, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)

    cv2.imwrite('./result_rknn.jpg', origimg)
    # cv2.imshow("test", origimg)
    # cv2.waitKey(0)

    
