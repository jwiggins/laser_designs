import argparse
from contextlib import closing
import os

import dicom
import numpy as np
import tables


# XXX: This assumes the DICOM data is int16
INT16_ATOM = tables.Int16Atom()


def split_path(path):
    path_parts = path.split('/')
    parent_path = '/' + '/'.join(path_parts[:-1])
    node_name = path_parts[-1]
    return parent_path, node_name


def dicom_to_h5(input_directory, output_path, node_path):
    dicom_names = os.listdir(input_directory)
    slices = []
    for name in dicom_names:
        path = os.path.join(input_directory, name)
        dcm = dicom.read_file(path)
        slices.append(dcm.pixel_array)

    slice_shape = slices[0].shape
    volume = np.concatenate(slices).reshape((-1,) + slice_shape)

    with closing(tables.openFile(output_path, mode='a')) as h5:
        parent_path, node_name = split_path(node_path)
        arr = h5.createCArray(parent_path, node_name, INT16_ATOM, volume.shape,
                              createparents=True)
        arr[:] = volume


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-n', '--node', default='/ct',
                        help='The path to the node in the HDF5 file '
                             'containing the volume data.')
    parser.add_argument('input_directory',
                        help='The path to the directory containing the DICOM'
                             ' slices.')
    parser.add_argument('output_file',
                        help='The HDF5 file containing the volume data.')

    args = parser.parse_args()
    dicom_to_h5(args.input_directory, args.output_file, args.node)

if __name__ == '__main__':
    main()
