import argparse
import json

import numpy as np
from reportlab.lib.units import mm, inch
from reportlab.pdfgen.canvas import Canvas
from skimage import measure
import tables

from kiva.pdf import GraphicsContext as PdfGraphicsContext

from colors import COLOR_TABLE


class Contour(object):
    def __init__(self, points=None, color='black'):
        self.points = points
        self.color = color


class ContourSet(object):
    def __init__(self, contours=None, bounding_box=None, index=0):
        self.contours = contours
        self.bounding_box = bounding_box
        self.index = index


class ContourSetCollection(object):
    def __init__(self, contour_sets=None):
        self.contour_sets = contour_sets

        sort_key = lambda x: x.bounding_box[2] * x.bounding_box[3]
        self.contour_sets.sort(key=sort_key, reverse=True)

    @property
    def has_contours(self):
        return bool(self.contour_sets)

    def get_contour_less_than_width(self, width):
        for i, cntr_set in enumerate(self.contour_sets):
            if cntr_set.bounding_box[3] < width:
                break
        else:
            return None

        return self.contour_sets.pop(i)


def box_area(box):
    return box[2] * box[3]


def contour_bounding_box(contour, offset=0.0):
    ys, xs = contour.T
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    width, height = x1 - x0, y1 - y0
    return np.asarray([x0-offset, y0-offset, width+offset*2, height+offset*2])


def create_graphics_context(params):
    pagesize = (params['output_width'] * params['output_dpi'],
                params['output_height'] * params['output_dpi'])
    canvas = Canvas(filename="laser.pdf", pagesize=pagesize)

    gc = PdfGraphicsContext(canvas)
    gc.set_line_width(params['hairline_width'] * inch)

    default_color = COLOR_TABLE[params['default_color']]
    gc.set_stroke_color(default_color)
    gc.set_fill_color(default_color)

    return gc


def draw_contours(contour_collection, params):
    gc = create_graphics_context(params)

    output_w = params['output_width'] * params['output_dpi']
    output_h = params['output_height'] * params['output_dpi']
    origin_x, origin_y = 0.0, 0.0
    line_height = 0.0

    next_contour_set = contour_collection.get_contour_less_than_width

    while contour_collection.has_contours:
        remaining_width = output_w - origin_x
        contour_set = next_contour_set(remaining_width)

        # Start a new row/page as needed
        if contour_set is None:
            origin_y += line_height
            origin_x = line_height = 0.0

            if (origin_y + 2.75 * params['output_dpi']) > output_h:
                # Start a new page
                origin_y = 0.0
                gc.begin_page()
            continue

        contours = contour_set.contours
        x, y, height, width = contour_set.bounding_box

        # Trace the contours
        with gc:
            gc.translate_ctm(origin_x, origin_y)
            for cntr in contours:
                points = cntr.points
                points[:, 1] -= x
                points[:, 0] -= y

                with gc:
                    gc.set_stroke_color(COLOR_TABLE[cntr.color])
                    gc.lines(points)
                    gc.close_path()
                    gc.stroke_path()

        # Add a slice index
        with gc:
            pos_x = origin_x + width / 2.
            pos_y = origin_y + height / 2.
            gc.show_text_at_point(str(contour_set.index), pos_x, pos_y)

        line_height = max(height, line_height)
        origin_x += width

    gc.save()


def get_all_slice_contours(volume, params):
    bbox_padding = params['output_dpi'] * params['contour_bbox_padding']
    bbox_index = params['contour_bbox_index']
    contour_sets = []
    for i, slc in enumerate(volume):
        contours = get_slice_contours(slc, i, params)
        if contours:
            bbox = contour_bounding_box(contours[bbox_index].points,
                                        offset=bbox_padding)
            contours.extend(get_registration_contours(params))
            cntr = ContourSet(contours=contours, index=i, bounding_box=bbox)
            contour_sets.append(cntr)

    return ContourSetCollection(contour_sets=contour_sets)


def get_registration_contours(params):
    contours = []
    for mark in params['registration_marks']:
        points = np.asarray(mark['points'])
        points = pixels_to_points(points, params)
        contours.append(Contour(points=points, color=mark['color']))
    return contours


def get_slice_contours(slice, slice_index, params):
    slice_contours = []
    clip_boxes = params['clip_boxes']
    clip_overlap_percentage = params['clip_overlap_percentage']
    for contour_params in params['contours']:
        if slice_index > contour_params['last_slice']:
            break
        contours = measure.find_contours(slice, contour_params['isovalue'])
        # Only add contours if they don't maximally intersect the clip boxes
        for cntr in contours:
            bbox = contour_bounding_box(cntr)
            max_overlap_area = clip_overlap_percentage * box_area(bbox)
            for clip_box in clip_boxes:
                int_area = intersection_area(bbox, clip_box)
                if int_area > max_overlap_area:
                    break
            else:
                cntr_pnts = pixels_to_points(cntr, params)
                cntr = Contour(points=cntr_pnts, color=contour_params['color'])
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


def pixels_to_points(contour, params):
    scale_factor = params['scale_factor']
    voxel_dims = params['voxel_dims']
    x_dims, y_dims = voxel_dims[:2]
    x_factor = x_dims * mm * scale_factor
    y_factor = y_dims * mm * scale_factor
    return contour * np.array([y_factor, x_factor])


def read_params(filename):
    with open(filename, 'r') as fp:
        params = json.load(fp)
    return params


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('input_file',
                        help='The path to the HDF5 file containing the volume'
                             ' data.')
    parser.add_argument('-n', '--node-path', default='/ct',
                        help='The path to the node in the HDF5 file '
                             'containing the volume.')
    parser.add_argument('-p', '--params',
                        help='The path to the parameters file')

    args = parser.parse_args()

    params = read_params(args.params)

    h5 = tables.openFile(args.input_file)
    volume = h5.getNode(args.node_path)[:]
    h5.close()

    vol_max = volume.max()
    for contour in params['contours']:
        contour['isovalue'] *= vol_max

    contour_collection = get_all_slice_contours(volume, params)
    draw_contours(contour_collection, params)


if __name__ == '__main__':
    main()
