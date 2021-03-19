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
        if hasattr(self, '_palette'):
            return self._palette
        mpo = MonsterPaletteObject.get(self.palette_index)
        self._palette = [v for vs in mpo.rgb_palette for v in vs]
        return self.palette

    @property
    def stencil(self):
        if hasattr(self, '_stencil'):
            return self._stencil
        mcomp = MonsterComp16Object if self.is_big else MonsterComp8Object
        self._stencil =  list(mcomp.get(self.stencil_index).stencil)
        return self.stencil

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
        #assert self.interleave_tile(rows) == tile
        return rows

    def interleave_tile(self, old_tile):
        if self.is_8color:
            new_tile = [0]*24
        else:
            new_tile = [0]*32

        assert len(old_tile) == 8
        for (j, old_row) in enumerate(old_tile):
            assert len(old_row) == 8
            for (i, pixel) in enumerate(old_row):
                i = 7 - i
                a = bool(pixel & 1)
                b = bool(pixel & 2)
                c = bool(pixel & 4)
                d = bool(pixel & 8)

                new_tile[(j*2)] |= (a << i)
                new_tile[(j*2)+1] |= (b << i)
                if self.is_8color:
                    new_tile[j+16] |= (c << i)
                else:
                    new_tile[(j*2)+16] |= (c << i)
                    new_tile[(j*2)+17] |= (d << i)

        assert self.deinterleave_tile(new_tile) == old_tile
        return bytes(new_tile)

    @property
    def tiles(self):
        if hasattr(self, '_tiles'):
            return self._tiles

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

        self._tiles = tiles
        return self.tiles

    @property
    def all_pixels(self):
        tiles = list(self.tiles)
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
    def palette_indexes(self):
        return set(self.all_pixels)

    @property
    def image(self):
        if hasattr(self, '_image'):
            return self._image

        from PIL import Image
        if self.is_big:
            width = 16*8
        else:
            width = 8*8
        height = width
        data = bytes(self.all_pixels)
        im = Image.frombytes(mode='P', size=(width, height), data=data)
        im.putpalette(self.palette)

        self._image = im
        return self.image

    def load_image(self, image, transparency=None):
        self._image = image
        assert self.image == image
        assert self.image.mode == 'P'

        width, height = image.size
        assert width <= 128
        assert height <= 128
        is_big = width > 64 or height > 64
        if is_big:
            self.misc_palette_index |= 0x80
        else:
            self.misc_palette_index &= 0x7f
        assert self.is_big == is_big

        palette_indexes = set(image.tobytes())
        assert max(palette_indexes) <= 0xf
        is_8color = max(palette_indexes) <= 7
        if (len(palette_indexes) <= 8 and not is_8color
                and hasattr(image, 'filename')):
            print('Wasteful palette: %s' % image.filename)
        if is_8color:
            self.misc_sprite_pointer |= 0x8000
        else:
            self.misc_sprite_pointer &= 0x7fff
        assert self.is_8color == is_8color

        if transparency is None:
            border = (
                [self.image.getpixel((0, j)) for j in range(height)] +
                [self.image.getpixel((width-1, j)) for j in range(height)] +
                [self.image.getpixel((i, 0)) for i in range(width)] +
                [self.image.getpixel((i, height-1)) for i in range(width)])
            transparency = Counter(border).most_common(1)[0][0]

        palette = self.image.getpalette()
        if transparency != 0:
            data = self.image.tobytes()
            data = data.replace(b'\x00', b'\xff')
            data = data.replace(bytes([transparency]), b'\x00')
            data = data.replace(b'\xff', bytes([transparency]))
            self.image.frombytes(data)
            index = 3 * transparency
            temp = palette[index:index+3]
            assert len(temp) == 3
            palette[index:index+3] = palette[0:3]
            palette[0:3] = temp
        #palette[0:3] = [0, 0, 0]
        self.image.putpalette(palette)
        self._palette = palette[:3*16]
        assert self.palette == palette[:3*16]

        blank_tile = [[0]*8]*8
        new_tiles = []
        stencil = []
        if self.is_big:
            num_tiles_width = 16
        else:
            num_tiles_width = 8

        for jj in range(num_tiles_width):
            stencil_value = 0
            for ii in range(num_tiles_width):
                tile = []
                for j in range(8):
                    row = []
                    for i in range(8):
                        x = (ii*8) + i
                        y = (jj*8) + j
                        try:
                            row.append(self.image.getpixel((x, y)))
                        except IndexError:
                            row.append(0)
                    tile.append(row)
                if tile == blank_tile:
                    pass
                else:
                    new_tiles.append(tile)
                    stencil_value |= (1 << (num_tiles_width-(ii+1)))
            if self.is_big:
                stencil_value = ((stencil_value >> 8) |
                                 ((stencil_value & 0xff) << 8))
            stencil.append(stencil_value)
        self._tiles = new_tiles
        self._stencil = stencil

    def write_data(self, filename):
        self.image

        for mpo in MonsterPaletteObject.new_palettes:
            if mpo.compare_palette(self.palette, is_8color=self.is_8color):
                chosen_palette = mpo
                break
        else:
            chosen_palette = MonsterPaletteObject.get_free()
            chosen_palette.set_from_rgb(self.palette, is_8color=self.is_8color)

        self.misc_palette_index &= 0xFC
        self.misc_palette_index |= (chosen_palette.index >> 8)
        self.low_palette_index = chosen_palette.index & 0xff
        assert self.palette_index == chosen_palette.index

        for mso in MonsterSpriteObject.every:
            if (hasattr(mso, 'written') and mso.written
                    and mso.stencil == self.stencil):
                self.stencil_index = mso.stencil_index
                break
        else:
            if self.is_big:
                mco = MonsterComp16Object.create_new()
            else:
                mco = MonsterComp8Object.create_new()
            mco.stencil = self.stencil
            self.stencil_index = mco.new_index

        if not hasattr(MonsterSpriteObject, 'free_space'):
            MonsterSpriteObject.free_space = addresses.new_monster_graphics

        for mso in MonsterSpriteObject.every:
            if (hasattr(mso, 'written') and mso.written
                    and mso.stencil == self.stencil
                    and mso.tiles == self.tiles):
                self.misc_sprite_pointer = mso.misc_sprite_pointer
                break
        else:
            pointer = (MonsterSpriteObject.free_space -
                       addresses.new_monster_graphics)
            pointer //= 8
            assert 0 <= pointer <= 0x7fff

            self.misc_sprite_pointer &= 0x8000
            self.misc_sprite_pointer |= pointer
            check = (((self.misc_sprite_pointer & 0x7FFF) * 8)
                     + addresses.new_monster_graphics)
            assert check == MonsterSpriteObject.free_space

            f = open(filename, 'r+b')
            f.seek(MonsterSpriteObject.free_space)
            data = bytes([v for tile in self.tiles
                          for v in self.interleave_tile(tile)])
            f.write(data)

            if self.is_8color:
                MonsterSpriteObject.free_space += (len(self.tiles) * 24)
            else:
                MonsterSpriteObject.free_space += (len(self.tiles) * 32)

            assert f.tell() == MonsterSpriteObject.free_space
            f.close()

        super().write_data(filename)
        self.written = True


class MonsterPaletteObject(TableObject):
    after_order = [MonsterSpriteObject]
    new_palettes = []

    @property
    def successor(self):
        return MonsterPaletteObject.get(self.index + 1)

    @property
    def rgb_palette(self):
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

    def compare_palette(self, palette, is_8color):
        if is_8color:
            pal = palette[:24]
        else:
            pal = palette[:48]
        return pal == [v for vs in self.rgb_palette for v in vs][:len(pal)]

    def set_from_rgb(self, rgb_palette, is_8color):
        multiplier = 0x1f / 0xff
        rgb_palette = rgb_palette[:48]
        zipped = zip(rgb_palette[0::3],
                     rgb_palette[1::3],
                     rgb_palette[2::3])
        palette = []
        for (r, g, b) in zipped:
            r = int(round(multiplier * r))
            g = int(round(multiplier * g))
            b = int(round(multiplier * b))
            assert 0 <= r <= 0x1f
            assert 0 <= g <= 0x1f
            assert 0 <= b <= 0x1f
            c = r | (g << 5) | (b << 10)
            palette.append(c)

        assert len(palette) >= 8
        self.colors = palette[:8]
        if not is_8color:
            assert len(palette) == 16
            assert self.successor not in MonsterPaletteObject.new_palettes
            self.successor.colors = palette[8:]
            MonsterPaletteObject.new_palettes.append(self.successor)

    @classmethod
    def get_free(cls):
        for mpo in MonsterPaletteObject.every:
            if mpo not in MonsterPaletteObject.new_palettes:
                MonsterPaletteObject.new_palettes.append(mpo)
                return mpo


class MonsterCompMixin(TableObject):
    @property
    def new_index(self):
        return self.index - self.specs.count


class MonsterComp8Object(MonsterCompMixin):
    after_order = [MonsterSpriteObject]

    def write_data(self, filename):
        if self.new_index >= 0:
            assert self.pointer is None
            self.pointer = addresses.new_comp8_pointer + 4 + (
                self.new_index * len(self.stencil))
            assert (addresses.new_comp8_pointer + 4 <= self.pointer
                    < addresses.new_monster_graphics - len(self.stencil))
        super().write_data(filename)
        self.written = True


class MonsterComp16Object(MonsterCompMixin):
    after_order = [MonsterComp8Object]

    def write_data(self, filename):
        if not hasattr(MonsterComp16Object, 'new_base_address'):
            for mc8 in MonsterComp8Object.every:
                assert mc8.written
            MonsterComp16Object.new_base_address = max(
                [mc8.pointer for mc8 in MonsterComp8Object.every]) + 8

            f = open(filename, 'r+b')
            f.seek(addresses.new_comp8_pointer)
            pointer = MonsterComp8Object.get(0).pointer & 0xffff
            f.write(pointer.to_bytes(2, byteorder='little'))
            f.seek(addresses.new_comp16_pointer)
            pointer = MonsterComp16Object.new_base_address & 0xffff
            f.write(pointer.to_bytes(2, byteorder='little'))
            f.close()

        self.pointer = MonsterComp16Object.new_base_address + (
            self.index * len(self.stencil))
        assert (MonsterComp16Object.new_base_address <= self.pointer
                < addresses.new_monster_graphics - len(self.stencil))

        super().write_data(filename)


def nuke():
    f = open(get_outfile(), 'r+b')
    f.seek(addresses.monster_graphics)
    f.write(b'\x00' * (addresses.end_monster_graphics -
                       addresses.monster_graphics))


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
            mso.load_image(mso.image)
        nuke()

        clean_and_write(ALL_OBJECTS)
        finish_interface()

    except Exception:
        print_exc()
        print('ERROR:', exc_info()[1])
        input('Press Enter to close this program. ')
