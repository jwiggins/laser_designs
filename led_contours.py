import json

import numpy as np
from reportlab.lib.units import mm


THICKNESS_SCALE = 2.3622/3.0  # 0.093" thick material
# Pixel Spacing DS: ['0.48828125', '0.48828125']
PIXEL_SPACING = 0.48828125
pixels_to_points = lambda con: con * PIXEL_SPACING * mm * THICKNESS_SCALE

# Radius (10mm LED)
RADIUS = 5.75  # mm
LED_CENTERS = (
    (260, 370),
    (290, 345),
    (316, 315),
    (335, 280),
    (348, 240),
    (352, 205),
    (350, 170),
    (340, 135),
    (320, 110),
    (290, 97),
    (260, 82),
    (240, 50),
    (220, 80),
    (190, 92),
    (160, 104),
    (135, 130),
    (125, 165),
    (117, 200),
    (120, 235),
    (128, 270),
    (143, 305),
    (166, 340),
    (190, 365),
    (225, 375),
)


def build_post_contours(radius=RADIUS):
    radius /= PIXEL_SPACING
    marks = []
    for center in LED_CENTERS:
        cy, cx = center
        thetas = np.linspace(0, 2*np.pi, 25)
        xs = np.cos(thetas)*radius + cx
        ys = np.sin(thetas)*radius + cy
        mark = {
            "color": "blue",
            "points": pixels_to_points(np.vstack((xs, ys)).T).tolist(),
        }
        print json.dumps(mark) + ","


if __name__ == '__main__':
    build_post_contours()
