from remonsterate.remonsterate import remonsterate
from sys import argv
from traceback import format_exc

if __name__ == '__main__':
    try:
        if len(argv) > 3:
            remonsterate(*argv[1:])
        else:
            outfile = input('Output filename? ')
            seed = input('Seed? ')
            images_tags_filename = input('Images list filename? ')
            monsters_tags_filename = input('Monster tags filename? ')
            remonsterate(outfile, seed, images_tags_filename,
                         monsters_tags_filename)
        print('Finished successfully.')

    except Exception:
        print(format_exc())
    input('Press Enter to close this program. ')
