import augmentation
import tensorflow as tf
import numpy as np


class AugmentationTest(tf.test.TestCase):
    def test_flip(self):
        input = (tf.convert_to_tensor([
            [1, 2],
            [3, 4],
        ]), {
            'P3': tf.convert_to_tensor([
                [[0], [1]],
                [[2], [3]],
            ])
        }, {
            'P3':
            tf.convert_to_tensor([
                [[[0., 0., .25, .25]], [[.25, .25, .5, .5]]],
                [[[0., 0., .25, .25]], [[0., 0., 0., 0.]]],
            ])
        })

        actual = augmentation.flip(*input)

        expected = (tf.convert_to_tensor([
            [2, 1],
            [4, 3],
        ]), {
            'P3': tf.convert_to_tensor([
                [[1], [0]],
                [[3], [2]],
            ])
        }, {
            'P3':
            tf.convert_to_tensor([
                [[[.25, .5, .5, .75]], [[0., .75, .25, 1.]]],
                [[[0., 1., 0., 1.]], [[0., .75, .25, 1.]]],
            ])
        })

        a, e = self.evaluate([actual, expected])

        assert np.array_equal(a[0], e[0])
        assert np.array_equal(a[1]['P3'], e[1]['P3'])
        assert np.array_equal(a[2]['P3'], e[2]['P3'])
