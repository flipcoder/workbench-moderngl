#!/usr/bin/env python
from .node import *
from PIL import Image
import moderngl as gl
from .defs import *
import cson
from glm import ivec2, vec2
from .sprite import *
from .util import *
from .animator import *
from copy import copy
from os import path
import struct


class MeshBuffer(Resource):
    def __init__(self, app, name, data, shader, meshtype, *args, **kwargs):
        if len(args) == 1:
            assert False
            return
        super().__init__(app, name, *args, **kwargs)
        self.cache = app.cache
        self._data = Reactive(data)
        self.ctx = app.ctx
        self.shader = shader
        self.mesh_type = meshtype
        self.flipped = {}
        self.generated = False
        self.vbo = self.vao = None
        self.solid = kwargs.pop("solid", False)
        self._box = Lazy(self.calculate_box, [self._data])
        self.on_pend = Signal()

    @property
    def box(self):
        return self._box()

    @property
    def data(self):
        return self._data()

    @data.setter
    def data(self, d):
        self._data(d)
        self.on_pend()

    def __iadd__(self, sig):
        self.on_pend += sig

    def __isub__(self, sig):
        self.on_pend -= sig

    def connect(self, sig, weak=True):
        return self.on_pend.connect(sig, weak)

    def disconnect(self, sig, weak=True):
        return self.on_pend.disconnect(sig, weak)

    def calculate_box(self):
        d = self._data()
        if not d:
            return None
        mini = vec3(float("inf"))
        maxi = -mini
        for i in range(0, len(d), 5):
            for c in range(3):
                idx = i + c
                if d[idx] < mini[c]:
                    mini[c] = d[idx]
                if d[idx] > maxi[c]:
                    maxi[c] = d[idx]

        # check for infs and nans
        for c in (*mini, *maxi):
            if c != c or c == float("inf") or c == float("-inf"):
                print("warning: invalid box for", self)
                self.on_pend()
                return None

        return [mini, maxi]

    def generate(self):
        if self.generated:
            if self.vao:
                self.vao.delete()
            if self.vao:
                self.vbo.delete()
        # self.vbo = self.ctx.buffer(self.data.astype("f4").tobytes())
        self.vbo = self.ctx.buffer(struct.pack("f" * len(self.data), *self.data))
        # self.vbo = self.ctx.buffer(self.data.bytes())
        self.vao = self.ctx.simple_vertex_array(
            self.shader, self.vbo, "in_vert", "in_text"
        )
        self.generated = True

    def render(self):
        if not self.generated:
            self.generate()
        self.vao.render(self.mesh_type)

    def cleanup(self):
        flipped = self.flipped
        self.flipped = {}  # prevent recursion
        if self.generated:
            if self.vao:
                self.vao.delete()
            if self.vao:
                self.vbo.delete()
        for flip in flipped:
            flip.cleanup()
            flip.cleanup = None

    def hflip(self):
        return self.flip("h")

    def vflip(self):
        return self.flip("v")

    def hvflip(self):
        return self.flip("hv")

    def flip(self, flags):
        if ":+" in self.fn:
            assert False  # already flipped, not yet impl
        flags = str(sorted(flags))  # normalize flags
        if flags in self.flipped:
            return self.flipped[flags]
        newdata = self.data.copy()
        for i in range(len(newdata) // 5):
            if "h" in flags:  # flip U coordinate
                newdata[i * 5 + 3] = 1.0 - newdata[i * 5 + 3]
            if "v" in flags:  # flip V cordinate
                newdata[i * 5 + 4] = 1.0 - newdata[i * 5 + 4]
        if self.fn:  # if not temp name, append flags to cached name
            meshname = self.fn + ":+" + flags
        meshdata = MeshBuffer(
            self.app,
            meshname,
            newdata,
            self.shader,
            self.mesh_type,
            *self.args,
            **self.kwargs
        )
        # meshdata.flipped[flags] = self
        flipped = self.flipped[flags] = self.cache.ensure(meshname, meshdata)
        assert flipped
        return flipped


class Mesh(Node):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vertices = None
        self.layers = []  # layers -> skins -> images
        self.skin = 0
        self.sprite = None  # frame data here if mesh is a sprite
        self.animator = None
        self.image = None
        self.frame = 0
        self.loaded = False
        self.resources = []
        self.vbo = None
        self.vao = None
        self.mesh_type = kwargs.get("mesh_type")

        self.data_con = None

        pos = kwargs.get("position") or kwargs.get("pos")
        scale = to_vec3(kwargs.get("scale"))
        self.filter = kwargs.get("filter")
        self._data = Reactive(kwargs.get("data"))
        # if self._data():
        #     self.connections += self._data().data.connect(self.set_box)

        rot = kwargs.get("rot") or kwargs.get("rotation")
        initfunc = kwargs.get("init")

        if pos is not None:
            self.position(pos)
        if scale is not None:
            self.scale(scale)
        if rot is not None:
            self.rotate(*rot)

        if initfunc:
            initfunc(self)
        if self.fn:
            self.load()

    # meshdata
    @property
    def data(self):
        return self._data() if self._data else None

    # meshdata
    @data.setter
    def data(self, d):
        self._data(d)

    def flip(self, flags):
        self.meshdata = self.meshdata.hflip(flags)

    def hflip(self):
        self.meshdata = self.meshdata.hflip()

    def vflip(self):
        self.meshdata = self.meshdata.vflip()

    def hvflip(self):
        self.meshdata = self.meshdata.hvflip()

    def load(self, fn=None):
        assert not self.loaded

        fn = self.fn = fn or self.fn  # use either filename from ctor or arg

        # cson = sprite data
        if fn and fn.lower().endswith(".cson"):
            self.sprite = self.app.cache(fn)
            self.resources.append(self.sprite)
            self.layers = self.sprite.layers
            if not self.layers or not self.sprite:
                assert False  # failed to load
            # self.scale(self.sprite['size'])
        else:  # not sprite
            if isinstance(fn, str):
                fns = [fn]
            if not self.image:  # mesh image not preloaded?
                self.layers = self.layers or [[[]]]  # layers -> skins -> images
                for img in fns:
                    # [0][0] = default layer and skin (image list)
                    # p = path.join(self.app.data_path(), img)
                    img = Image.open(path.join(self.app.data_path(), img))
                    img = img.convert("RGBA")
                    self.layers[0][0].append(img)
        for layer in self.layers:
            for skin in layer:
                for i in range(len(skin)):  # for img in skin:
                    img = skin[i]
                    tex = self.ctx.texture(img.size, 4, img.tobytes())
                    if self.filter:
                        tex.filter = self.filter
                    skin[i] = tex
        # if no data and not temp name
        meshname = ""

        # no prefab or temp name? load a quad for image
        if not isinstance(self.data, Prefab) or (not self.fn or "." not in self.fn):
            self.data = TEXTURED_QUAD_CENTERED
            self.mesh_type = gl.TRIANGLE_STRIP
            self.filter = (gl.NEAREST, gl.NEAREST)
            meshname = self.data.name

        # does cache already have this mesh?
        if self.data:
            if not self.cache.has(meshname):
                meshdata = MeshBuffer(
                    self.app,
                    self.data.name,
                    self.data.data,
                    self.app.shader,
                    self.mesh_type,
                )
                self.meshdata = self.cache.ensure(meshname, meshdata)
            else:
                self.meshdata = self.cache(meshname)
        else:
            self.meshdata = None

        if self.sprite:
            self.animator = Animator(self)
        self.loaded = True

        reset_local_box = lambda d: self.set_local_box(d)
        self.meshdata_con = self.meshdata.connect(reset_local_box)
        reset_local_box(self.meshdata.box)

    def update(self, t):
        super().update(t)
        if self.animator:
            self.animator.update(t)

    def render(self):
        assert self.loaded
        if self.visible and self.meshdata:
            self.app.matrix(self.matrix(WORLD))
            for i in range(len(self.layers)):
                self.layers[i][self.skin][self.frame].use(i)
            self.meshdata.render()
        super().render()

    def cleanup(self):
        for r in self.resources:
            if r:
                r.deref()
        self.resources = []
        super().cleanup()
