This is ReMONSTERate, a utility to import arbitrary monster sprites into FF6.

## Quick-Start Guide for Gamers
1. Download `remonsterate_windows.zip` from the [latest release](https://github.com/abyssonym/remonsterate/releases/latest).
    * If you would rather use the python version, download `remonsterate_source.zip`
2. You will need **a bunch of sprite image files**
    * These image files are **not** included with ReMONSTERate.
    * Consider visiting the [Beyond Chaos Discord](https://discord.com/invite/S3G3UXy) to obtain some sprites.
    * It is recommended to keep the sprites in a separate folder. Put the folder in the folder containing `remonsterate.exe`.
3. You will need a text file that contains **a list of the images** and **where to find them**.
    * See the included text file `images_and_tags.txt` for examples on how to write this list
    * If you downloaded a sprite pack from somewhere else, see if it came with a pre-written list you can use.
    * Put this text file in the folder containing `remonsterate.exe`.
4. You will need another text file that optionally contains **a list of monsters and their tags**.
    * You can use the included `monsters_and_tags.txt` file for this purpose if you don't care about tagging.
    * It's okay for this file to be empty.
    * Put this text file in the folder containing `remonsterate.exe`.
5. You will need a FF6 or Beyond Chaos ROM file to import the sprites into.
    * Make sure that you back up this file by making a copy.
    * For Beyond Chaos, you must randomize the ROM with BC *before* running ReMONSTERate.
6. Run `remonsterate.exe`
    * For the python version, run `run.py`.
7. For `Rom filename`, enter the filename of the ROM from step 5. For `Seed`, enter any numeric value that you wish, or leave it blank if you don't care. For `Images list filename`, enter the filename of the text file from step 3. For `Monster tags filename`, enter the filename of the text file from step 4.
8. After some time, the program will finish running. You can now load the rom in your emulator and play with the randomized sprites. If you encounter any bugs, please contact me or report them in the [Beyond Chaos Discord](https://discord.com/invite/S3G3UXy).

## Important information:
ReMONSTERate expands the rom and makes several ASM edits to relocate sprites to the free space. The space used is from $380000 to $3fffff ($f80000 to $ffffff). The ASM edits are in `tables/monster_expansion_patch.txt` This rom expansion allows every monster to have a unique sprite and a unique palette, without worrying about running out of space.

ReMONSTERate has a randomization feature with a tagging system. See `images_and_tags.txt` for information on how to add sprites to the pool and tag them. See `monsters_and_tags.txt` for information on how to require or block specific tags for specific monsters.

You can import ReMONSTERate to your Python3 project. If you do this, you must have the Python `pillow` module installed to use it. `pillow` is a Python imaging library, and is required to analyze and transform the sprites. It is easiest to install `pillow` with `pip`, the Python package installer.

The simplest way to use ReMONSTERate in your Python project is with the `remonsterate` function.

```python
from remonsterate.remonsterate import remonsterate
remonsterate(rom_filename, seed, images_filename, monsters_filename)
```

This will automatically read the tagged sprites listed in `images_filename` and randomly import them into `rom_filename` based on the restrictions set by `monsters_filename`. Note that the edits to `rom_filename` are immediate - you must back up your rom yourself!

You can also use remonsterate to develop your own randomization process:

```python
from remonsterate.remonsterate import (
    begin_remonster, finish_remonster, MonsterSpriteObject)
from PIL import Image

begin_remonster(MY_ROM_FILENAME, MY_SEED)

images = [Image.open(filename) for filename in MY_IMAGE_FILENAMES]
monster = MonsterSpriteObject.get(MY_MONSTER_INDEX)
monster.select_image(images)

finish_remonster()
```

This will randomly select an image from `images` for your chosen `monster`. If you want even more control:

```python
monster.load_image(image)
finish_remonster()
```

This will allow you to load an image of your choice manually. You can easily break the game this way, for example, by using a large sprite for an enemy that is supposed to be small.

If you have questions or feedback, do not hesitate to contact me.
* https://github.com/abyssonym
* https://twitter.com/abyssonym

SPECIAL THANKS to CtrlxZ for commissioning this utility.
