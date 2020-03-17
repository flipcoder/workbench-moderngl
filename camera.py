#!/usr/bin/python
from node import *
import glm
import math

class Camera(Node):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        fov = 90.0
        self.projection = glm.perspectiveFov(
            math.radians(fov), 800.0, 600.0, 0.01, 1000.0
        )

