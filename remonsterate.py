from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses, get_random_degree,
    get_activated_patches, mutate_normal, shuffle_normal, write_patch)
from randomtools.utils import (
    classproperty, cached_property, get_snes_palette_transformer,
    read_multi, write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, get_activated_codes, activate_code,
    run_interface, rewrite_snes_meta, clean_and_write, finish_interface)
from collections import defaultdict
from os import path
from time import time, sleep, gmtime
from collections import Counter
from itertools import combinations
from sys import argv, exc_info
from traceback import print_exc


VERSION = 1
ALL_OBJECTS = None


class MouldObject(TableObject): pass
class FormationObject(TableObject): pass


class MonsterSpriteObject(TableObject):
    @property
    def is_8color(self):
        return bool(self.misc_sprite_pointer & 0x8000)

    @property
    def sprite_pointer(self):
        base_address = addresses.monster_graphics
        return (self.misc_sprite_pointer & 0x7FFF) * 8 + base_address

    @property
    def palette_index(self):
        return ((self.misc_palette_index & 0x3) << 8) | self.low_palette_index

    @property
    def is_big(self):
        return bool(self.misc_palette_index & 0x80)

    @property
    def palette(self):
        return MonsterPaletteObject.get(self.palette_index)

    @property
    def stencil(self):
        mcomp = MonsterComp16Object if self.is_big else MonsterComp8Object
        return mcomp.get(self.stencil_index).stencil

    @property
    def num_tiles(self):
        return sum([bin(v).count('1') for v in self.stencil])

    def deinterleave_tile(self, tile):
        rows = []
        for i in range(8):
            if self.is_8color:
                interleaved = (tile[i*2], tile[(i*2)+1],
                               tile[i+16])
            else:
                interleaved = (tile[i*2], tile[(i*2)+1],
                               tile[(i*2)+16], tile[(i*2)+17])
            row = []
            for j in range(7, -1, -1):
                pixel = 0
                mask = 1 << j
                for k, v in enumerate(interleaved):
                    pixel |= bool(v & mask) << k

                if self.is_8color:
                    assert 0 <= pixel <= 7
                else:
                    assert 0 <= pixel <= 0xf
                row.append(pixel)

            assert len(row) == 8
            rows.append(row)

        assert len(rows) == 8
        return rows

    @property
    def tiles(self):
        if self.is_8color:
            numbytes = 24
        else:
            numbytes = 32

        f = open(get_outfile(), 'r+b')
        tiles = []
        for i in range(self.num_tiles):
            f.seek(self.sprite_pointer + (numbytes*i))
            tiles.append(self.deinterleave_tile(f.read(numbytes)))
        f.close()
        return tiles

    @property
    def all_pixels(self):
        tiles = self.tiles
        if self.is_big:
            width = 16
        else:
            width = 8

        blank_tile = [[0]*8]*8

        height = width
        rows = []
        for y in range(height):
            row = []
            for x in range(width):
                stencil_value = self.stencil[y]
                if self.is_big:
                    stencil_value = ((stencil_value >> 8) |
                                     ((stencil_value & 0xff) << 8))
                to_tile = stencil_value & (1 << (width-(x+1)))
                if to_tile:
                    row.append(tiles.pop(0))
                else:
                    row.append(blank_tile)
            rows.append(row)

        all_pixels = []
        for row in rows:
            for i in range(8):
                for tile in row:
                    tile_row = tile[i]
                    all_pixels.extend(tile_row)

        return all_pixels

    @property
    def image(self):
        from PIL import Image
        if self.is_big:
            width = 16*8
        else:
            width = 8*8
        height = width
        data = bytes(self.all_pixels)
        im = Image.frombytes(mode='P', size=(width, height), data=data)
        palette = [v for vs in self.palette.rgb for v in vs]
        im.putpalette(palette)
        return im


class MonsterPaletteObject(TableObject):
    @property
    def successor(self):
        return MonsterPaletteObject.get(self.index + 1)

    @property
    def rgb(self):
        multiplier = 0xff / 0x1f
        rgbs = []
        for c in self.colors + self.successor.colors:
            r = c & 0x1f
            g = (c >> 5) & 0x1f
            b = (c >> 10) & 0x1f
            a = (c >> 15)
            assert not a
            if a:
                r, g, b = 0, 0, 0
            r = int(round(multiplier * r))
            g = int(round(multiplier * g))
            b = int(round(multiplier * b))
            rgbs.append((r, g, b))
        return rgbs


class MonsterComp8Object(TableObject): pass
class MonsterComp16Object(TableObject): pass


if __name__ == '__main__':
    try:
        print ('You are using the FF6 Remonsterator '
               'version %s.' % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        run_interface(ALL_OBJECTS, snes=False, custom_degree=False)

        for mso in MonsterSpriteObject.every:
            im = mso.image
            im.show()
            input()

        clean_and_write(ALL_OBJECTS)
        finish_interface()

    except Exception:
        print_exc()
        print('ERROR:', exc_info()[1])
        input('Press Enter to close this program. ')
