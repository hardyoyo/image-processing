from __future__ import absolute_import
from __future__ import print_function
from __future__ import division

import os
import shutil

import logging
import tempfile
import io

from uuid import uuid4

from image_processing import format_converter, validation
import libxmp

DEFAULT_TIFF_FILENAME = 'full.tiff'
DEFAULT_XMP_FILENAME = 'xmp.xml'
DEFAULT_JPG_FILENAME = 'full.jpg'
DEFAULT_LOSSLESS_JP2_FILENAME = 'full_lossless.jp2'
DEFAULT_LOSSY_JP2_FILENAME = 'full_lossy.jp2'

DEFAULT_ICC_PROFILE = "/opt/kakadu/sRGB_v4_ICC_preference.icc"
DEFAULT_IMAGE_MAGICK_PATH = '/usr/bin/'


class Transform(object):

    def __init__(self, kakadu_base_path, image_magick_path=DEFAULT_IMAGE_MAGICK_PATH, tiff_filename=DEFAULT_TIFF_FILENAME,
                 xmp_filename=DEFAULT_XMP_FILENAME, jpg_filename=DEFAULT_JPG_FILENAME,
                 lossless_jp2_filename=DEFAULT_LOSSLESS_JP2_FILENAME,
                 lossy_jp2_filename=DEFAULT_LOSSY_JP2_FILENAME, icc_profile=DEFAULT_ICC_PROFILE):
        self.tiff_filename = tiff_filename
        self.xmp_filename = xmp_filename
        self.jpg_filename = jpg_filename
        self.lossless_jp2_filename = lossless_jp2_filename
        self.lossy_jp2_filename = lossy_jp2_filename
        self.icc_profile = icc_profile
        self.format_converter = format_converter.FormatConverter(kakadu_base_path=kakadu_base_path,
                                                                 image_magick_path=image_magick_path)
        self.log = logging.getLogger(__name__)

    def generate_derivatives_from_jpg(self, jpg_file, output_folder, strip_embedded_metadata=False, save_xmp=False):
        """
        Creates a copy of the jpg file and a validated jpeg2000 file and stores both in the given folder
        :param jpg_file:
        :param output_folder: the folder where the related dc.xml will be stored, with the dataset's uuid as foldername
        :param strip_embedded_metadata: True if you want to remove the embedded image metadata during the tiff
        conversion process. (no effect if image is already a tiff)
        :param save_xmp: If true, metadata will be extracted from the image file and preserved in a separate xmp file
        :return: filepaths of created images
        """

        scratch_output_folder = tempfile.mkdtemp(prefix='image_ingest_')
        try:

            jpeg_filepath = os.path.join(output_folder, self.jpg_filename)
            shutil.copy(jpg_file, jpeg_filepath)
            generated_files = [jpeg_filepath]

            if save_xmp:
                xmp_file_path = os.path.join(output_folder, self.xmp_filename)
                self.extract_xmp(jpeg_filepath, xmp_file_path)
                generated_files += [xmp_file_path]

            scratch_tiff_filepath = os.path.join(scratch_output_folder, str(uuid4()) + '.tif')
            tif_conversion_options = ['-strip'] if strip_embedded_metadata else []
            self.format_converter.convert_to_tiff(jpeg_filepath, scratch_tiff_filepath, tif_conversion_options)

            generated_files += self.generate_jp2_derivatives_from_tiff(scratch_tiff_filepath, output_folder)

            return generated_files
        finally:
            if scratch_output_folder:
                shutil.rmtree(scratch_output_folder, ignore_errors=True)

    def generate_derivatives_from_tiff(self, tiff_file, output_folder, include_tiff=True, save_xmp=False,
                                       repage_image=False):
        """
        Creates a copy of the jpg fil and a validated jpeg2000 file and stores both in the given folder
        :param tiff_file:
        :param output_folder: the folder where the related dc.xml will be stored, with the dataset's uuid as foldername
        :param include_tiff: Include copy of source tiff file in derivatives
        :param repage_image: True if you want to remove the embedded image metadata during the tiff conversion process.
        (no effect if image is already a tiff)
        :param save_xmp: If true, metadata will be extracted from the image file and preserved in a separate xmp file
        :return: filepaths of created images
        """

        scratch_output_folder = tempfile.mkdtemp(prefix='image_ingest_')
        try:

            jpeg_filepath = os.path.join(output_folder, self.jpg_filename)
            self.format_converter.convert_to_jpg(tiff_file, jpeg_filepath)
            self.log.debug('jpeg file {0} generated'.format(jpeg_filepath))
            generated_files = [jpeg_filepath]

            if save_xmp:
                xmp_file_path = os.path.join(output_folder, self.xmp_filename)
                self.extract_xmp(tiff_file, xmp_file_path)
                generated_files += [xmp_file_path]

            if include_tiff:
                tiff_filepath = os.path.join(output_folder, self.tiff_filename)
                shutil.copy(tiff_file, tiff_filepath)
                generated_files += [tiff_filepath]

            scratch_tiff_filepath = os.path.join(scratch_output_folder, str(uuid4()) + '.tiff')
            shutil.copy(tiff_file, scratch_tiff_filepath)

            if repage_image:
                # remove negative offsets by repaging the image. (It's the most common error during conversion)
                self.format_converter.repage_image(scratch_tiff_filepath, scratch_tiff_filepath)

            generated_files += self.generate_jp2_derivatives_from_tiff(scratch_tiff_filepath, output_folder)

            return generated_files

        finally:
            if scratch_output_folder:
                shutil.rmtree(scratch_output_folder, ignore_errors=True)

    def generate_jp2_derivatives_from_tiff(self, scratch_tiff_file, output_folder):
        lossless_filepath = os.path.join(output_folder, self.lossless_jp2_filename)
        self.format_converter.convert_to_jpeg2000(scratch_tiff_file, lossless_filepath, lossless=True)
        validation.validate_jp2(lossless_filepath)
        self.log.debug('Lossless jp2 file {0} generated'.format(lossless_filepath))

        lossy_filepath = os.path.join(output_folder, self.lossy_jp2_filename)
        # todo: should be mogrify
        self.format_converter.convert_tiff_colour_profile(scratch_tiff_file, scratch_tiff_file, self.icc_profile)
        self.format_converter.convert_colour_to_jpeg2000(scratch_tiff_file, lossy_filepath, lossless=False)
        validation.validate_jp2(lossy_filepath)
        self.log.debug('Lossy jp2 file {0} generated'.format(lossy_filepath))

        return [lossless_filepath, lossy_filepath]

    # todo: move to format_converter
    def extract_xmp(self, image_file, xmp_file_path):

        image_xmp_file = libxmp.XMPFiles(file_path=image_file)
        try:
            xmp = image_xmp_file.get_xmp()

            # using io.open for unicode compatibility
            with io.open(xmp_file_path, 'a') as output_xmp_file:
                output_xmp_file.write(xmp.serialize_to_unicode())
            self.log.debug('XMP file {0} generated'.format(xmp_file_path))
        finally:
            image_xmp_file.close_file()
