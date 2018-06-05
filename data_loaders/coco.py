import numpy as np
import pycocotools.coco as pycoco
import os


class COCO(object):
    def __init__(self, ann_path, dataset_path):
        self.coco = pycoco.COCO(ann_path)
        self.dataset_path = dataset_path
        self.category_ids = sorted(self.coco.getCatIds())
        self.num_classes = len(self.category_ids)

    def download(self):
        self.coco.download(tarDir=self.dataset_path)

    def __iter__(self):
        image_ids = self.coco.getImgIds()
        images = self.coco.loadImgs(ids=image_ids)
        for image in images:
            image_file = os.path.join(self.dataset_path, image['file_name']).encode('utf-8')
            annotation_ids = self.coco.getAnnIds(imgIds=image['id'])
            annotations = self.coco.loadAnns(ids=annotation_ids)

            boxes = []
            class_ids = []

            for a in annotations:
                [left, top, width, height] = a['bbox']
                if height <= 0 or width <= 0:
                    continue  # FIXME:
                assert height > 0, 'height {} <= 0'.format(height)  # FIXME:
                assert width > 0, 'width {} <= 0'.format(width)  # FIXME:
                boxes.append([top, left, top + height, left + width])
                class_ids.append(self.category_ids.index(a['category_id']))

            boxes = np.array(boxes)  # TODO: normalize boxes
            class_ids = np.array(class_ids)

            # ignore samples without ground true boxes
            if len(annotations) > 0:
                yield {
                    'image_file': image_file,
                    'class_ids': class_ids,
                    'boxes': boxes
                }


# class Image(object):
#     def __init__(self, img):
#         self.id = img['id']
#         self.filename = img['file_name']
#         self.size = np.array([img['height'], img['width']])


if __name__ == '__main__':
    for x in COCO(
            os.path.expanduser('~/Datasets/coco/instances_train2017.json'),
            os.path.expanduser('~/Datasets/coco/images')):
        print(x)
        break