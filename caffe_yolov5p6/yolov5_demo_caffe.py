import numpy as np
import sys, os
from math import sqrt
from math import exp
import cv2

caffe_root = '/root/caffe-master/'
sys.path.insert(0, caffe_root + 'python')
import caffe

net_file = './yolov5n_p6.prototxt'
caffe_model = './yolov5n_p6_new.caffemodel'

if not os.path.exists(caffe_model):
    print(caffe_model + " does not exist")
    exit()
if not os.path.exists(net_file):
    print(net_file + " does not exist")
    exit()

net = caffe.Net(net_file, caffe_model, caffe.TEST)

CLASSES = ('car', 'ped')

class_num = 2
anchor_num = 3
output_head = 3
cell_size = [[48, 80], [24, 40], [12, 20]]
anchor_size = [
    [[10, 13], [16, 30], [33, 23]],
    [[30, 61], [62, 45], [59, 119]],
    [[116, 90], [156, 198], [373, 326]]
]

stride = [8, 16, 32]
grid_cell = np.zeros(shape=(3, 48, 80, 2))

nms_thre = 0.45
obj_thre = [0.4, 0.2]

input_imgW = 640
input_imgH = 384


class DetectBox:
    def __init__(self, classId, score, xmin, ymin, xmax, ymax):
        self.classId = classId
        self.score = score
        self.xmin = xmin
        self.ymin = ymin
        self.xmax = xmax
        self.ymax = ymax


def grid_cell_init():
    for h in range(output_head):
        for i in range(cell_size[h][1]):
            for j in range(cell_size[h][0]):
                grid_cell[h][j][i][0] = i;
                grid_cell[h][j][i][1] = j;


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


def postprocess(out, img_h, img_w):
    print('postprocess ... ')

    detectResult = []

    output = []
    output.append(out['sigmoid1'].reshape((-1)))
    output.append(out['sigmoid2'].reshape((-1)))
    output.append(out['sigmoid3'].reshape((-1)))

    gs = 4 + 1 + class_num
    scale_h = img_h / input_imgH
    scale_w = img_w / input_imgW

    for i in range(output_head):
        y = output[i]
        for ss in range(cell_size[i][0]):

            for ff in range(cell_size[i][1]):
                for jj in range(anchor_num):
                    conf_scale = y[((jj * gs + 4) * cell_size[i][0] * cell_size[i][1]) + ss * cell_size[i][1] + ff]
                    for cl in range(class_num):
                        conf = y[((jj * gs + 5 + cl) * cell_size[i][0] * cell_size[i][1]) + ss * cell_size[i][1] + ff] * conf_scale

                        if conf > obj_thre[cl]:
                            bx = (y[((jj * gs + 0) * cell_size[i][0] * cell_size[i][1]) + ss * cell_size[i][1] + ff] * 2.0 - 0.5 + grid_cell[i][ss][ff][0]) * stride[i]
                            by = (y[((jj * gs + 1) * cell_size[i][0] * cell_size[i][1]) + ss * cell_size[i][1] + ff] * 2.0 - 0.5 + grid_cell[i][ss][ff][1]) * stride[i]
                            bw = pow((y[((jj * gs + 2) * cell_size[i][0] * cell_size[i][1]) + ss * cell_size[i][1] + ff] * 2), 2) * anchor_size[i][jj][0]
                            bh = pow((y[((jj * gs + 3) * cell_size[i][0] * cell_size[i][1]) + ss * cell_size[i][1] + ff] * 2), 2) * anchor_size[i][jj][1]

                            xmin = (bx - bw / 2) * scale_w
                            ymin = (by - bh / 2) * scale_h
                            xmax = (bx + bw / 2) * scale_w
                            ymax = (by + bh / 2) * scale_h

                            xmin = xmin if xmin > 0 else 0
                            ymin = ymin if ymin > 0 else 0
                            xmax = xmax if xmax < img_w else img_w
                            ymax = ymax if ymax < img_h else img_h

                            box = DetectBox(cl, conf, xmin, ymin, xmax, ymax)
                            detectResult.append(box)

    # NMS 过程
    print('detectResult:', len(detectResult))
    predBox = NMS(detectResult)
    return predBox


def preprocess(src):
    img = cv2.resize(src, (input_imgW, input_imgH))
    img = img * 0.00392156
    return img


def detect(imgfile):
    origimg = cv2.imread(imgfile)
    img_h, img_w = origimg.shape[:2]
    img = preprocess(origimg)

    img = img.astype(np.float32)
    img = img.transpose((2, 0, 1))

    net.blobs['blob1'].data[...] = img
    out = net.forward()
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

    cv2.imwrite('./result.jpg', origimg)
    # cv2.imshow("test", origimg)
    # cv2.waitKey(0)


if __name__ == '__main__':
    print('This is main .... ')
    grid_cell_init()
    detect('./test.jpg')
