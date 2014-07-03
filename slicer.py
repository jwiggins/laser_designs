import numpy as np
from reportlab.lib.units import mm, inch
from reportlab.pdfgen.canvas import Canvas
from skimage import measure
import tables

from kiva.pdf import GraphicsContext as PdfGraphicsContext
from traits.api import (HasStrictTraits, Array, Bool, List, Instance, Int,
                        Property)


PARAMS = {
    'bone': {
        'contour_index': [None] * 60,
        'isovalue': 0.425,
        'last_slice': 57,
    },
    'skin': {
        'contour_index': [0] * 52 + [1] + [2] * 6 + [0],
        'isovalue': 0.17,
        'last_slice': 59,
    },
}
TISSUE = 'skin'
params = PARAMS[TISSUE]

# Slice Thickness = 3.0 mm
THICKNESS_SCALE = 2.3622/3.0  # 0.093" thick material
# Pixel Spacing DS: ['0.48828125', '0.48828125']
PIXEL_SPACING = 0.48828125
pixels_to_points = lambda con: con * PIXEL_SPACING * mm * THICKNESS_SCALE
box_area = lambda box: box[2] * box[3]

LASER_HAIRLINE = 0.001 * inch
PDF_DPI = 72.0
CANVAS_W = 24.0 * PDF_DPI
CANVAS_H = 18.0 * PDF_DPI

MACHINE_BOX_0 = [0, 190, 120, 322]
MACHINE_BOX_1 = [392, 190, 120, 322]
SLICE_BOX = [0, 0, 512, 512]
AXIS_CENTER = (238, 346)

# Post Radius (1/16" welding rod)
POST_RADIUS = 0.889  # mm
POST0_CENTER = (225, 345)
POST1_CENTER = (250, 345)


class Contour(HasStrictTraits):
    #: The actual contours
    contours = List(Array)

    #: A bounding rectangle for the slice
    bounding_box = Array

    #: Which slice is this
    index = Int


class ContourBag(HasStrictTraits):
    #: Contour objects
    contours = List(Instance(Contour))

    #: Are there still contours to consume?
    has_contours = Property(Bool)

    def _contours_changed(self):
        sort_key = lambda x: x.bounding_box[2] * x.bounding_box[3]
        self.contours.sort(key=sort_key, reverse=True)

    def _get_has_contours(self):
        return bool(self.contours)

    def get_contour_less_than_width(self, width):
        for i, cntr in enumerate(self.contours):
            if cntr.bounding_box[3] < width:
                break
        else:
            return None

        return self.contours.pop(i)


def box_to_line_points(box):
    x, y, w, h = box
    xs = (x, x + w, x + w, x, x)
    ys = (y, y, y + h, y + h, y)
    return xs, ys


def build_post_contours(radius=POST_RADIUS):
    radius /= PIXEL_SPACING
    contours = []
    for center in (POST0_CENTER, POST1_CENTER):
        cy, cx = center
        thetas = np.linspace(0, 2*np.pi, 15)
        xs = np.cos(thetas)*radius + cx
        ys = np.sin(thetas)*radius + cy
        contours.append(pixels_to_points(np.vstack((xs, ys)).T))
    return contours


def contour_bounding_box(contour, offset=0.0):
    ys, xs = contour.T
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    width, height = x1 - x0, y1 - y0
    return np.asarray([x0-offset, y0-offset, width+offset*2, height+offset*2])


def contour_centroid(contour):
    ys, xs = contour.T
    return xs.mean(), ys.mean()


def create_graphics_context(index):
    canvas = Canvas(filename="laser{}.pdf".format(index),
                    pagesize=(CANVAS_W, CANVAS_H))
    gc = PdfGraphicsContext(canvas)
    gc.set_line_width(LASER_HAIRLINE)
    gc.set_stroke_color((0.0, 1.0, 0.0))

    return gc


def draw_contours(contour_bag):
    context_count = 0
    gc = create_graphics_context(context_count)

    origin_x, origin_y = 0.0, 0.0
    line_height = 0.0

    while contour_bag.has_contours:
        remaining_width = CANVAS_W - origin_x
        slc_cntr = contour_bag.get_contour_less_than_width(remaining_width)

        # Start a new row/PDF as needed
        if slc_cntr is None:
            origin_y += line_height
            origin_x = line_height = 0.0

            if (origin_y + 2.75*PDF_DPI) > CANVAS_H:
                # Start a new file
                origin_y = 0.0
                context_count += 1
                gc.save()
                gc = create_graphics_context(context_count)
            continue

        contours = slc_cntr.contours
        x, y, height, width = slc_cntr.bounding_box

        # Trace the contours
        with gc:
            gc.translate_ctm(origin_x, origin_y)
            for i, cntr in enumerate(contours):
                cntr[:, 1] -= x
                cntr[:, 0] -= y
                with gc:
                    # Everything after the first 3 contours is bone and should
                    # be black so that the laser can etch it first.
                    if i >= 3:
                        gc.set_stroke_color((0.0, 0.0, 0.0))
                    gc.lines(cntr)
                    gc.close_path()
                    gc.stroke_path()

        # Add a slice index in red
        with gc:
            gc.set_stroke_color((1.0, 0.0, 0.0))
            gc.set_fill_color((1.0, 0.0, 0.0))
            pos_x = origin_x + width / 2.
            pos_y = origin_y + height / 2.
            gc.show_text_at_point(str(slc_cntr.index), pos_x, pos_y)

        line_height = max(height, line_height)
        origin_x += width

    gc.save()


def get_all_slice_contours(volume):
    all_contours = []
    last_slice = PARAMS['skin']['last_slice']
    for i, slc in enumerate(volume[:last_slice]):
        contours = get_slice_contours(slc, i)
        bbox_padding = PDF_DPI * 0.125
        bbox = contour_bounding_box(contours[0], offset=bbox_padding)
        cntr = Contour(contours=contours, index=i, bounding_box=bbox)
        all_contours.append(cntr)

    return ContourBag(contours=all_contours)


def get_slice_contours(slice, slice_index):
    post_contours = build_post_contours()
    slice_contours = []
    for tissue in ('skin', 'bone'):
        tissue_params = PARAMS[tissue]
        contours = measure.find_contours(slice, tissue_params['isovalue'])
        contour_index = tissue_params['contour_index'][slice_index]
        if contour_index is not None:
            # We know these are skin contours
            cntr = pixels_to_points(contours[contour_index])
            slice_contours.append(cntr)
            slice_contours.extend(post_contours)
        else:
            # Only add bone contours if they don't maximally intersect
            # the pre-defined bounding boxes of the CT scanner machine
            for cntr in contours:
                bbox = contour_bounding_box(cntr)
                area = box_area(bbox)
                for mach_box in (MACHINE_BOX_0, MACHINE_BOX_1):
                    int_area = intersection_area(bbox, mach_box)
                    if int_area > (0.95 * area):
                        break
                else:
                    cntr = pixels_to_points(cntr)
                    slice_contours.append(cntr)

    return slice_contours


def intersection_area(box0, box1):
    def min_max(box):
        x, y, w, h = box
        return x, x+w, y, y+h

    def overlap(s0, s1, e0, e1):
        return min(e0, e1) - max(s0, s1)

    x00, x01, y00, y01 = min_max(box0)
    x10, x11, y10, y11 = min_max(box1)
    return overlap(x00, x10, x01, x11) * overlap(y00, y10, y01, y11)


def main():
    h5 = tables.openFile("head_ct.h5")
    volume = h5.getNode("/scan0")[:]
    h5.close()

    vol_max = volume.max()
    for parms in PARAMS.values():
        parms['isovalue'] *= vol_max

    contour_bag = get_all_slice_contours(volume)
    draw_contours(contour_bag)


if __name__ == '__main__':
    main()
