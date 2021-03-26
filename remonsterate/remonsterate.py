from .randomtools.tablereader import (
    set_table_specs, set_global_output_filename, sort_good_order,
    get_open_file, close_file, TableObject, addresses, write_patch)
from .randomtools.utils import cached_property, utilrandom as random
from .randomtools.interface import get_outfile, set_seed, get_seed
from collections import Counter
from hashlib import md5
from PIL import Image
from math import ceil


VERSION = 1
ALL_OBJECTS = None


def sig_func(c):
    s = '%s%s' % (c.filename, get_seed())
    return (md5(s.encode()).hexdigest(), c.filename)


def reseed(s):
    s = '%s%s' % (get_seed(), s)
    value = int(md5(s.encode('ascii')).hexdigest(), 0x10)
    random.seed(value)


class MouldObject(TableObject):
    # Moulds are templates for what enemy sizes are allowed
    # in an enemy formation. Enemies are generally 4, 8, 12, or 16
    # tiles in a given length/width. Note also that only 256 tiles
    # is the maximum for any mould.

    def read_data(self, filename, pointer):
        super().read_data(filename, pointer)

    @property
    def successor(self):
        try:
            return MouldObject.get(self.index+1)
        except KeyError:
            return None

    def read_dimensions(self):
        if self.successor is None:
            end_pointer = addresses.moulds_end | 0x20000
        else:
            end_pointer = self.successor.mould_pointer | 0x20000

        pointer = self.mould_pointer | 0x20000
        f = get_open_file(self.filename)
        dimensions = []
        while pointer < end_pointer:
            f.seek(pointer)
            data = f.read(4)
            dimensions.append((int(data[2]), int(data[3])))
            pointer += 4
        return dimensions


class FormationObject(TableObject): pass


class MonsterSpriteObject(TableObject):
    PROTECTED_INDEXES = [0x106] + list(range(0x180, 0x1a0))
    DONE_IMAGES = []

    def __repr__(self):
        if hasattr(self, 'image') and hasattr(self.image, 'filename'):
            return '{0:0>3X} {1}'.format(self.index, self.image.filename)
        else:
            return '{0:0>3X} ---'.format(self.index)

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

    @property
    def is_unseen(self):
        if (self.old_data['misc_sprite_pointer'] & 0x7fff == 0
                and self.index != 0):
            return True
        return False

    @property
    def is_protected(self):
        if self.index in self.PROTECTED_INDEXES:
            return True
        if self.is_unseen:
            return True
        return False

    def deinterleave_tile(self, tile):
        rows = []
        old_bitcount = sum([bin(v).count('1') for v in tile])
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
        new_bitcount = sum([bin(v).count('1') for vs in rows for v in vs])
        assert old_bitcount == new_bitcount
        return rows

    def interleave_tile(self, old_tile):
        if self.is_8color:
            new_tile = [0]*24
        else:
            new_tile = [0]*32

        old_bitcount = sum([bin(v).count('1') for vs in old_tile for v in vs])
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

        new_bitcount = sum([bin(v).count('1') for v in new_tile])

        assert old_bitcount == new_bitcount
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

        f = get_open_file(self.filename)
        tiles = []
        for i in range(self.num_tiles):
            f.seek(self.sprite_pointer + (numbytes*i))
            tiles.append(self.deinterleave_tile(f.read(numbytes)))

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

    @property
    def width_tiles(self):
        if self.is_big:
            def measure(s):
                return bin((s >> 8) | ((s & 0xff) << 8))[2:].rfind('1')
            width = max([measure(s) for s in self.stencil])
        else:
            width = max([bin(s)[2:].rfind('1') for s in self.stencil])
        return width + 1

    @property
    def height_tiles(self):
        height = 0
        for i, s in enumerate(self.stencil):
            if s:
                height = i
        return height + 1

    @cached_property
    def max_width_tiles(self):
        n = 4
        while True:
            if n >= self.width_tiles:
                return max(n, 4)
            n += 4

    @cached_property
    def max_height_tiles(self):
        n = 4
        while True:
            if n >= self.height_tiles:
                return max(n, 4)
            n += 4

    def get_size_compatibility(self, image):
        if not hasattr(self, '_image_scores'):
            self._image_scores = {}

        if image.filename in self._image_scores:
            return self._image_scores[image.filename]

        if isinstance(image, str):
            image = Image.open(image)

        width = ceil(image.width / 8)
        height = ceil(image.height / 8)
        image.close()

        if width > self.max_width_tiles or height > self.max_height_tiles:
            return None

        a, b = max(width, self.width_tiles), min(width, self.width_tiles)
        width_score = b / a
        a, b = max(height, self.height_tiles), min(height, self.height_tiles)
        height_score = b / a

        score = width_score * height_score
        self._image_scores[image.filename] = score

        return self.get_size_compatibility(image)

    def select_image(self, images=None):
        if self.is_protected:
            return

        if images is None:
            images = MonsterSpriteObject.import_images

        candidates = [i for i in images if
                      i.filename not in self.DONE_IMAGES and
                      self.get_size_compatibility(i) is not None
                      ]

        if hasattr(self, 'whitelist') and self.whitelist:
            candidates = [c for c in candidates
                          if hasattr(c, 'tags') and c.tags >= self.whitelist]

        if hasattr(self, 'blacklist') and self.blacklist:
            candidates = [c for c in candidates if not
                          (hasattr(c, 'tags') and c.tags & self.blacklist)]

        if not candidates:
            print('INFO: No more suitable images for sprite %x' % self.index)
            return False

        def sort_func(c):
            return self.get_size_compatibility(c), sig_func(c)

        candidates = sorted(candidates, key=sort_func)
        max_index = len(candidates)-1
        index = random.randint(
            random.randint(random.randint(0, max_index), max_index), max_index)
        chosen = candidates[index]
        self.DONE_IMAGES.append(chosen.filename)
        result = self.load_image(chosen)
        if not result:
            self.select_image(candidates)
        return True

    def remap_palette(self, data, rgb_palette):
        zipped = zip(rgb_palette[0::3],
                     rgb_palette[1::3],
                     rgb_palette[2::3])
        pal = enumerate(zipped)
        pal = sorted(pal, key=lambda x: (x[1], x[0]))
        old_vals = set(data)
        assert all([0 <= v <= 0xf for v in old_vals])
        new_palette = []
        for new, (old, components) in enumerate(pal):
            if new == 0:
                assert new == old
                assert components == (0, 0, 0)
            data = data.replace(bytes([old]), bytes([new | 0x80]))
            new_palette.append(components)
        for value in set(data):
            data = data.replace(bytes([value]), bytes([value & 0x7f]))
        new_palette = [v for vs in new_palette for v in vs]
        new_vals = set(data)
        assert len(old_vals) == len(new_vals)
        assert all([0 <= v <= 0xf for v in new_vals])
        assert set(rgb_palette) == set(new_palette)
        return data, new_palette

    def load_image(self, image, transparency=None):
        if isinstance(image, str):
            image = Image.open(image)
        if hasattr(image, 'filename') and image.fp is None:
            image = Image.open(image.filename)
        if image.mode != 'P':
            filename = image.filename
            image = image.convert(mode='P')
            image.filename = filename

        self._image = image
        assert self.image == image

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
        if max(palette_indexes) > 0xf:
            print('INFO: %s has too many colors.' % image.filename)
            return False

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
        palette[0:3] = [0, 0, 0]
        num_colors = 8 if self.is_8color else 16
        self.image.putpalette(palette)
        self._palette = palette[:3*num_colors]
        assert self.palette == palette[:3*num_colors]

        done_flag = False
        while hasattr(self.image, 'filename'):
            if done_flag:
                break
            for j in range(7,-1,-1):
                if done_flag:
                    break
                for i in range(width):
                    pixel = self.image.getpixel((i, j))
                    if pixel:
                        done_flag = True
                        break
            else:
                if not done_flag:
                    height = self.image.height
                    if height <= 8:
                        raise Exception('Fully transparent image not allowed.')
                    image = self.image.crop(
                        (0, 8, self.image.width, self.image.height))
                    image.filename = self.image.filename
                    self._image = image
                    new_height = self.image.height
                    assert height == new_height + 8

        blank_tile = [[0]*8]*8
        new_tiles = []
        stencil = []
        if self.is_big:
            num_tiles_width = 16
        else:
            num_tiles_width = 8

        data = self.image.tobytes()
        data, self._palette = self.remap_palette(data, self.palette)
        for jj in range(num_tiles_width):
            stencil_value = 0
            for ii in range(num_tiles_width):
                tile = []
                for j in range(8):
                    row = []
                    y = (jj*8) + j
                    for i in range(8):
                        x = (ii*8) + i
                        if x >= self.image.width:
                            row.append(0)
                            continue
                        try:
                            row.append(int(data[(y*self.image.width) + x]))
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

        return True

    def write_data(self, filename):
        self.image

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
            DIVISION_FACTOR = 16
            remainder = MonsterSpriteObject.free_space % DIVISION_FACTOR
            if remainder:
                MonsterSpriteObject.free_space += (DIVISION_FACTOR - remainder)
            assert not MonsterSpriteObject.free_space % DIVISION_FACTOR

            pointer = (MonsterSpriteObject.free_space -
                       addresses.new_monster_graphics)
            pointer //= DIVISION_FACTOR
            assert 0 <= pointer <= 0x7fff

            self.misc_sprite_pointer &= 0x8000
            self.misc_sprite_pointer |= pointer
            check = (((self.misc_sprite_pointer & 0x7FFF) * DIVISION_FACTOR)
                     + addresses.new_monster_graphics)
            assert check == MonsterSpriteObject.free_space
            remainder = MonsterSpriteObject.free_space % DIVISION_FACTOR
            if remainder:
                MonsterSpriteObject.free_space += (DIVISION_FACTOR - remainder)

            f = get_open_file(filename)
            f.seek(MonsterSpriteObject.free_space)
            data = bytes([v for tile in self.tiles
                          for v in self.interleave_tile(tile)])
            f.write(data)

            if self.is_8color:
                MonsterSpriteObject.free_space += (len(self.tiles) * 24)
            else:
                MonsterSpriteObject.free_space += (len(self.tiles) * 32)

            assert f.tell() == MonsterSpriteObject.free_space
            assert MonsterSpriteObject.free_space < addresses.new_comp8_pointer

        super().write_data(filename)
        self.written = True


class MonsterPaletteObject(TableObject):
    after_order = [MonsterSpriteObject]
    new_palettes = []

    @property
    def successor(self):
        return MonsterPaletteObject.get(self.index + 1)

    @cached_property
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
            max_index = 23
        else:
            max_index = 47

        index = 0
        for vs in self.rgb_palette:
            for v in vs:
                if v != palette[index]:
                    return False
                if index >= max_index:
                    return True
                index += 1

    def set_from_rgb(self, rgb_palette, is_8color):
        if 'rgb_palette' in self._property_cache:
            del(self._property_cache['rgb_palette'])

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
        if not hasattr(MonsterPaletteObject, 'last_index'):
            MonsterPaletteObject.last_index = -1
        index = MonsterPaletteObject.last_index
        while True:
            index += 1
            mpo = MonsterPaletteObject.get(index)
            if mpo not in MonsterPaletteObject.new_palettes:
                MonsterPaletteObject.last_index = mpo.index
                MonsterPaletteObject.new_palettes.append(mpo)
                return mpo

    def write_data(self, filename):
        if (self.index < addresses.previous_max_palettes
                or self in self.new_palettes):
            new_pointer = (addresses.new_palette_pointer
                           + (self.index * len(self.colors) * 2))
            assert (new_pointer + (len(self.colors)*2)
                        < addresses.new_code_pointer)
            super().write_data(filename, pointer=new_pointer)


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
                    < addresses.new_palette_pointer - len(self.stencil))
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

            f = get_open_file(filename)
            f.seek(addresses.new_comp8_pointer)
            pointer = MonsterComp8Object.get(0).pointer & 0xffff
            f.write(pointer.to_bytes(2, byteorder='little'))
            f.seek(addresses.new_comp16_pointer)
            pointer = MonsterComp16Object.new_base_address & 0xffff
            f.write(pointer.to_bytes(2, byteorder='little'))

        if self.new_index >= 0:
            self.pointer = MonsterComp16Object.new_base_address + (
                self.new_index * len(self.stencil) * 2)
            assert (MonsterComp16Object.new_base_address <= self.pointer
                    < addresses.new_palette_pointer - len(self.stencil))

        super().write_data(filename)


def nuke():
    f = get_open_file(get_outfile())
    f.seek(addresses.monster_graphics)
    f.write(b'\x00' * (addresses.end_monster_graphics -
                       addresses.monster_graphics))


def begin_remonster(outfile, seed):
    global ALL_OBJECTS
    set_seed(seed)
    random.seed(seed)
    set_global_output_filename(outfile)
    set_table_specs('tables_list.txt')

    ALL_OBJECTS = sort_good_order(
        [g for g in globals().values()
         if isinstance(g, type) and issubclass(g, TableObject)
         and g not in [TableObject]])

    for o in ALL_OBJECTS:
        o.every
    for o in ALL_OBJECTS:
        o.ranked

    for index in MonsterSpriteObject.PROTECTED_INDEXES:
        MonsterSpriteObject.get(index).image

    write_patch(outfile, 'monster_expansion_patch.txt')


def finish_remonster():
    for o in ALL_OBJECTS:
        o.write_all(o.get(0).filename)
    close_file(MonsterSpriteObject.get(0).filename)

    seed = get_seed()
    f = open('remonster.{0}.txt'.format(seed), 'w+')
    f.write('ROM: {0}\n'.format(MonsterSpriteObject.get(0).filename))
    f.write('Seed: {0}\n'.format(get_seed()))
    for mso in MonsterSpriteObject.every:
        f.write('{0}\n'.format(mso))
    f.close()


def remonsterate(outfile, seed, images_tags_filename,
                 monsters_tags_filename=None):
    seed = int(seed)
    begin_remonster(outfile, seed)

    images = []
    for line in open(images_tags_filename):
        if '#' in line:
            line, comment = line.split('#', 1)
        line = line.strip()
        if not line:
            continue
        if ':' in line:
            image_filename, tags = line.split(':')
            tags = tags.split(',')
            tags = {t for t in tags if t.strip()}
        else:
            image_filename, tags = line, set([])
        image = Image.open(image_filename)
        image.tags = tags
        image.close()
        images.append(image)

    if monsters_tags_filename is not None:
        for line in open(monsters_tags_filename):
            if '#' in line:
                line, comment = line.split('#', 1)
            line = line.strip()
            if ':' not in line:
                continue
            index, tags = line.split(':')
            index = int(index, 0x10)
            tags = tags.split(',')
            tags = {t for t in tags if t.strip()}
            whitelist = {t for t in tags if not t.startswith('!')}
            blacklist = {t[1:] for t in tags if t.startswith('!')}
            MonsterSpriteObject.get(index).whitelist = whitelist
            MonsterSpriteObject.get(index).blacklist = blacklist

    MonsterSpriteObject.import_images = sorted(images,
                                               key=lambda i: i.filename)

    msos = list(MonsterSpriteObject.every)
    random.shuffle(msos)
    for mso in msos:
        result = mso.select_image()
        if not result:
            mso.load_image(mso.image)

    finish_remonster()
