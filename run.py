from remonsterate.remonsterate import remonsterate
from sys import argv
from traceback import format_exc
from time import time

if __name__ == '__main__':
    try:
        if len(argv) > 3:
            remonsterate(*argv[1:])
        else:
            print('Make sure to back up your rom first!')
            outfile = input('Rom filename? ')
            seed = input('Seed? ')
            if not seed.strip():
                seed = time()
            images_tags_filename = input('Images list filename? ')
            monsters_tags_filename = input('Monster tags filename? ')
            remonsterate(outfile, seed, images_tags_filename,
                         monsters_tags_filename)
        print('Finished successfully.')

    except Exception:
        print(format_exc())
    input('Press Enter to close this program. ')
