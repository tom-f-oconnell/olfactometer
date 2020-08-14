#!/usr/bin/env python3

from os.path import split, join

from olfactometer import load


# TODO probably just refactor write_test_files.py stuff in here (ideally w/ no
# files on desk, especially non-tmp ones)
# TODO use the hypothesis package or something like that to more exhaustively
# add test cases?

this_script_path = split(__file__)[0]

def test_load():
    fh_from_json = load(join(this_script_path, 'fh.json'))
    fh_from_yaml = load(join(this_script_path, 'fh.yaml'))
    assert fh_from_json == fh_from_yaml

    fh_from_us_json = load(join(this_script_path, 'fh_underscore.json'))
    fh_from_us_yaml = load(join(this_script_path, 'fh_underscore.yaml'))
    assert fh_from_us_json == fh_from_us_yaml

    assert fh_from_json == fh_from_us_json


def main():
    test_load()


if __name__ == '__main__':
    main()

