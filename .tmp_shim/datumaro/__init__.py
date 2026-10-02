from enum import Enum


class AnnotationType(Enum):
    label = "label"
    bbox = "bbox"
    polygon = "polygon"
    mask = "mask"
    points = "points"
    polyline = "polyline"
    skeleton = "skeleton"
    ellipse = "ellipse"
    rotated_bbox = "rotated_bbox"
    cuboid_3d = "cuboid_3d"


# Placeholder classes used at import time in type alias positions;
# matching logic is never executed against these shims.
class Annotation:
    pass


class Points(Annotation):
    class Visibility(Enum):
        absent = 0
        hidden = 1
        visible = 2


class RleMask(Annotation):
    pass


class Skeleton(Annotation):
    pass


class Bbox(Annotation):
    pass


class Ellipse(Annotation):
    pass


class Polygon(Annotation):
    pass


class PolyLine(Annotation):
    pass


class Label:
    pass


class LabelCategories:
    class Category:
        pass


class DatasetItem:
    pass


class CategoriesInfo:
    pass


class CompiledMask:
    pass


class Image:
    pass


class Transform:
    pass


class ItemTransform(Transform):
    pass


class Extractor:
    pass


class Dataset:
    @classmethod
    def from_iterable(cls, *args, **kwargs):
        return cls()

    @classmethod
    def from_extractors(cls, *args, **kwargs):
        return cls()


def __getattr__(name):
    # Generic placeholders for class-body references in the import chain;
    # quality matching logic is never executed against these shims.
    if name and name[0].isupper():
        return type(name, (), {})
    raise AttributeError(name)

