# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Transform values: the xformOps BowerBot authors."""

from pxr import Sdf
from pxr import UsdGeom


class TransformUsd:
    """The xformOp type and value type for each op name."""

    XFORM_OPS: dict[str, tuple[object, Sdf.ValueTypeName]] = {
        "translate": (UsdGeom.XformOp.TypeTranslate, Sdf.ValueTypeNames.Double3),
        "rotateX": (UsdGeom.XformOp.TypeRotateX, Sdf.ValueTypeNames.Float),
        "rotateY": (UsdGeom.XformOp.TypeRotateY, Sdf.ValueTypeNames.Float),
        "rotateZ": (UsdGeom.XformOp.TypeRotateZ, Sdf.ValueTypeNames.Float),
        "rotateXYZ": (UsdGeom.XformOp.TypeRotateXYZ, Sdf.ValueTypeNames.Float3),
        "rotateXZY": (UsdGeom.XformOp.TypeRotateXZY, Sdf.ValueTypeNames.Float3),
        "rotateYXZ": (UsdGeom.XformOp.TypeRotateYXZ, Sdf.ValueTypeNames.Float3),
        "rotateYZX": (UsdGeom.XformOp.TypeRotateYZX, Sdf.ValueTypeNames.Float3),
        "rotateZXY": (UsdGeom.XformOp.TypeRotateZXY, Sdf.ValueTypeNames.Float3),
        "rotateZYX": (UsdGeom.XformOp.TypeRotateZYX, Sdf.ValueTypeNames.Float3),
        "scale": (UsdGeom.XformOp.TypeScale, Sdf.ValueTypeNames.Float3),
        "orient": (UsdGeom.XformOp.TypeOrient, Sdf.ValueTypeNames.Quatf),
        "transform": (UsdGeom.XformOp.TypeTransform, Sdf.ValueTypeNames.Matrix4d),
    }
