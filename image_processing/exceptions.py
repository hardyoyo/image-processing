
class ImageProcessingError(Exception):
    pass


class ImageMagickError(ImageProcessingError):
    pass


class KakaduError(ImageProcessingError):
    pass


class ValidationError(ImageProcessingError):
    pass