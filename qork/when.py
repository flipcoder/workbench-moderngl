#!/usr/bin/env python
import weakref

from qork.signal import Signal
from qork.defs import *


class When(Signal):
    def __init__(self):
        super().__init__()
        self.time = 0

    def update_slot(self, slot, dt):
        """
        Does timer checking on a specific slot
        """

        if isinstance(slot, weakref.ref):
            wref = slot
            slot = slot()
            if not slot:
                if isinstance(self.sig, weakref.ref):
                    sig = sig()
                    if not sig:
                        return
                self.sig.disconnect(sig)
                return

        if slot.start_t != 0:  # not infinite timer
            slot.t -= dt

        if slot.fade:
            slot.t = max(0.0, slot.t)
            p = 1.0 - (slot.t / slot.start_t)
            slot(p)
            if slot.t < EPSILON:
                slot.disconnect()  # queued
                return
        else:
            # not a fade
            while slot.t < EPSILON:
                if not slot.once or slot.count == 0:
                    slot()
                if slot.once:
                    slot.disconnect()  # queued
                    return
                if slot.start_t == 0:
                    break
                slot.t += slot.start_t  # wrap

    def update(self, dt):
        """
        Advance time by dt
        """
        self.time += dt
        super().each_slot(lambda slot: self.update_slot(slot, dt))

    def __call__(self, dt):
        return self.update(self, dt)

    def every(self, t, func, weak=True, once=False):
        """
        Every t seconds, call func.
        The first call is in t seconds.
        """
        slot = self.connect(func, weak)
        slot.t = slot.start_t = float(t)
        slot.fade = False
        slot.ease = None
        slot.once = once
        return slot

    def once(self, t, func, weak=True):
        return self.every(t, func, weak, True)

    def fade(self, length, func, ease=None, weak=True):
        """
        Every frame, call function with fade value [0,1] fade value
        """
        # slot = super().once(func, weak)
        # slot = super().connect(func, weak)
        slot = self.every(0, func, weak)
        slot.start_t = slot.t = float(length)
        slot.fade = True
        # slot.ease = ease
        return slot
