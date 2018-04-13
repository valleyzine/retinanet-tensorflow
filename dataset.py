import os
import numpy as np
import tensorflow as tf
from coco import COCO
import utils
import augmentation
import argparse
import itertools
from tqdm import tqdm

NEG_IOU_THRESHOLD = 0.4
POS_IOU_THRESHOLD = 0.5
MEAN = [0.46618041, 0.44669811, 0.40252436]
STD = [0.27940595, 0.27489075, 0.28920765]


# TODO: remove image size and make all boxes 0-1
# TODO: background category
# TODO: ignored boxes
# def level_labels(image_size, class_ids, boxes, level, factor):
#     grid_size = tf.to_int32(tf.ceil(image_size / factor))
#     anchor_boxes = tf.to_float(level.anchor_boxes / image_size)
#
#     # extract targets ##########################################################
#     # [OBJECTS]
#     classes_true = tf.concat([[0], class_ids], 0)
#     # [OBJECTS, 4]
#     boxes_true = tf.concat([[[0, 0, 0, 0]], boxes], 0)
#
#     # compute iou ##############################################################
#     # [OBJECTS, 1, 1, 1, 4]
#     boxes_true_shape = tf.shape(boxes_true)
#     boxes_true = tf.reshape(boxes_true, (boxes_true_shape[0], 1, 1, 1, 4))
#
#     # [1, H, W, SIZES, 4]
#     anchor_boxmap = utils.anchor_boxmap(grid_size, anchor_boxes)
#
#     # [OBJECTS, H, W, SIZES]
#     iou = utils.iou(anchor_boxmap, boxes_true)
#     iou = tf.where(iou > IOU_THRESHOLD, iou, tf.zeros_like(iou))
#     # for the given anchor box, finds the ground truth box with the highest iou
#     # [H, W, SIZES]
#     indices = tf.argmax(iou, 0)
#     del iou
#
#     # build classification targets #############################################
#     # [H, W, SIZES]
#     classification = tf.gather(classes_true, indices)
#
#     # build regression targets #################################################
#     # [H, W, SIZES, 1]
#     indices_expanded = tf.expand_dims(indices, -1)
#     # [OBJECTS, H, W, SIZES, 1]
#     indices_expanded = tf.one_hot(
#         indices_expanded, boxes_true_shape[0], axis=0)
#     del indices
#
#     # [OBJECTS, H, W, SIZES, 4]
#     regression = boxes_true * indices_expanded
#     # [H, W, SIZES, 4]
#     regression = tf.reduce_sum(regression, 0)
#
#     return classification, regression

def position_grid(size):
    cell_size = tf.to_float(1 / size)

    y_pos = tf.linspace(cell_size[0] / 2, 1 - cell_size[0] / 2, size[0])
    x_pos = tf.linspace(cell_size[1] / 2, 1 - cell_size[1] / 2, size[1])

    x_pos, y_pos = tf.meshgrid(x_pos, y_pos)
    grid = tf.stack([y_pos, x_pos], -1)

    return grid


def to_center_box(box):
    a, b = tf.split(box, 2, -1)
    size = b - a

    return tf.concat([a + size / 2, size], -1)


def from_center_box(box):
    pos, size = tf.split(box, 2, -1)
    half_size = size / 2

    return tf.concat([pos - half_size, pos + half_size], -1)


def level_labels(image_size, class_id, true_box, level, factor):
    n_objects = tf.shape(true_box)[0]
    n_scales = level.anchor_boxes.shape[0]

    # [OBJECTS, 4]
    true_box = to_center_box(true_box)
    # [OBJECTS, 1, 1, 1, 4]
    true_box = tf.reshape(true_box, (n_objects, 1, 1, 1, 4))

    # [SCALES, 2]
    anchor_size = tf.to_float(level.anchor_boxes / image_size)

    grid_size = tf.to_int32(tf.ceil(image_size / factor))
    h = tf.shape(grid_size)[0]
    w = tf.shape(grid_size)[0]
    # [H, W, 2]
    anchor_position = position_grid(grid_size)
    del grid_size
    # [1, H, W, 1, 2]
    anchor_position = tf.reshape(anchor_position, (1, h, w, 1, 2))
    # [1, H, W, SCALES, 2]
    anchor_position = tf.tile(anchor_position, (1, 1, 1, n_scales, 1))
    # [1, 1, 1, SCALES, 2]
    anchor_size = tf.reshape(anchor_size, (1, 1, 1, n_scales, 2))
    # [1, H, W, SCALES, 2]
    anchor_size = tf.tile(anchor_size, [1, h, w, 1, 1])
    # [1, H, W, SCALES, 4]
    anchor = tf.concat([anchor_position, anchor_size], -1)

    # classification

    # [OBJECTS, H, W, SCALES]
    iou = utils.iou(from_center_box(anchor), from_center_box(true_box))
    # [H, W, SCALES]
    iou_index = tf.argmax(iou, 0)
    # [H, W, SCALES]
    iou_value = tf.reduce_max(iou, 0)

    # mask for assigning background class
    # [H, W, SCALES]
    bg_mask = iou_value < NEG_IOU_THRESHOLD
    # mask for ignoring unassigned anchors
    # [H, W, SCALES]
    ignored_mask = tf.logical_or(bg_mask, iou_value >= POS_IOU_THRESHOLD)

    # assign class labels to anchors
    # [H, W, SCALES]
    classification = tf.gather(class_id, iou_index)
    # assign background class to anchors with iou < NEG_IOU_THRESHOLD
    # [H, W, SCALES]
    classification = tf.where(bg_mask, tf.zeros_like(classification), classification)

    # regression

    # [OBJECTS, 1, 1, 1, 2], [OBJECTS, 1, 1, 1, 2],
    true_position, true_size = tf.split(true_box, 2, -1)

    # [OBJECTS, H, W, SCALES, 2]
    shifts = (true_position - anchor_position) / anchor_size
    # [OBJECTS, 1, 1, SCALES, 2]
    scales = true_size / anchor_size
    # [OBJECTS, H, W, SCALES, 2]
    scales = tf.tile(scales, (1, h, w, 1, 1))
    # [OBJECTS, H, W, SCALES, 4]
    regression = tf.concat([shifts, tf.log(scales)], -1)

    # select regression for assigned anchor
    # [H, W, SCALES, 1]
    iou_index_expanded = tf.expand_dims(iou_index, -1)
    # [OBJECTS, H, W, SCALES, 1]
    iou_index_expanded = tf.one_hot(iou_index_expanded, n_objects, axis=0)

    # [H, W, SCALES, 1]
    regression = tf.reduce_sum(regression * iou_index_expanded, 0)

    return classification, regression, ignored_mask


def make_labels(image_size, class_ids, boxes, levels):
    labels = {
        pn: level_labels(
            image_size,
            class_ids,
            boxes,
            level=levels[pn],
            factor=2**int(pn[-1]))
        for pn in levels
    }

    classifications = {pn: labels[pn][0] for pn in labels}
    regressions = {pn: labels[pn][1] for pn in labels}

    return classifications, regressions


def gen(coco):
    for img in coco.load_imgs(coco.get_img_ids()):
        filename = os.path.join(coco.dataset_path,
                                img.filename).encode('utf-8')
        anns = list(coco.load_anns(coco.get_ann_ids(img_ids=img.id)))
        class_ids = np.array([a.category_id for a in anns])
        boxes = np.array([a.box for a in anns])

        # TODO: check why dataset has samples without boxes
        if len(anns) > 0:
            yield filename, class_ids, boxes
        else:
            yield filename, np.zeros([0]), np.zeros([0, 4])


def rescale_image(image, scale):
    size = tf.to_float(tf.shape(image)[:2])
    shorter = tf.argmin(size)
    ratio = scale / size[shorter]
    new_size = tf.to_int32(tf.round(size * ratio))

    return tf.image.resize_images(image, new_size, method=tf.image.ResizeMethod.BILINEAR)


def make_dataset(ann_path,
                 dataset_path,
                 levels,
                 download,
                 augment,
                 scale=None,
                 shuffle=None):
    def load_image_with_labels(filename, class_ids, boxes):
        image = tf.read_file(filename)
        image = tf.image.decode_jpeg(image, channels=3)
        image = tf.image.convert_image_dtype(image, tf.float32)
        image_size = tf.shape(image)[:2]
        boxes = tf.to_float(
            boxes / tf.concat([image_size, image_size], 0))

        if scale is not None:
            image = rescale_image(image, scale)
            image_size = tf.shape(image)[:2]

        classifications, regressions = make_labels(
            image_size, class_ids, boxes, levels=levels)

        return image, classifications, regressions

    def preprocess(image, classifications, regressions):
        image_flipped, classifications_flipped, regressions_flipped = augmentation.flip(image, classifications,
                                                                                        regressions)

        image = tf.stack([image, image_flipped], 0)
        classifications = {
            pn: tf.stack([classifications[pn], classifications_flipped[pn]], 0)
            for pn in classifications
        }
        regressions = {
            pn: tf.stack([regressions[pn], regressions_flipped[pn]], 0)
            for pn in regressions
        }
        # TODO: use level names
        classifications = {
            pn: tf.one_hot(classifications[pn], coco.num_classes)
            for pn in classifications
        }

        return image, classifications, regressions

    def augment_sample(image, classifications, regressions):
        # TODO: add augmentation
        # image = tf.image.random_contrast(image, 0.8, 1.2)
        # image = tf.image.random_brightness(image, 0.2)
        # image = tf.image.random_saturation(image, 0.8, 1.0)

        return image, classifications, regressions

    # coco = COCO(ann_path, dataset_path, download)
    coco = type("", (), dict(num_classes=81))()
    ds = tf.data.Dataset.from_generator(
        lambda: gen(coco),
        output_types=(tf.string, tf.int32, tf.int32),
        output_shapes=([], [None], [None, 4]))

    if shuffle is not None:
        ds = ds.shuffle(shuffle)

    ds = ds.map(load_image_with_labels)
    ds = ds.map(preprocess)

    if augment:
        ds = ds.map(augment_sample)

    return ds, coco.num_classes


def compute_mean_std():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str, nargs=2, required=True)

    args = parser.parse_args()
    ds, num_classes = make_dataset(
        ann_path=args.dataset[0],
        dataset_path=args.dataset[1],
        levels={},
        download=False,
        augment=False)
    iter = ds.make_initializable_iterator()
    image, classifications_true, regressions_true = iter.get_next()

    mean = np.array([0., 0., 0.])
    std = np.array([0., 0., 0.])
    i = 0

    with tf.Session() as sess:
        sess.run(iter.initializer)
        for _ in tqdm(itertools.count()):
            try:
                x = sess.run(image)
                i += x.shape[0] * x.shape[1] * x.shape[2]
                mean += x.sum((0, 1, 2))
            except tf.errors.OutOfRangeError:
                break

        mean = mean / i

        sess.run(iter.initializer)
        for _ in tqdm(itertools.count()):
            try:
                x = sess.run(image)
                std += ((x - mean)**2).sum((0, 1, 2))
            except tf.errors.OutOfRangeError:
                break

        std = np.sqrt(std / i)

    return mean, std


if __name__ == '__main__':
    mean, std = compute_mean_std()
    print('mean:', mean)
    print('std:', std)
