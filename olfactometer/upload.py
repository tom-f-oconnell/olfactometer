#!/usr/bin/env python3

from subprocess import Popen, DEVNULL, check_output
import os
from os.path import join, split, splitext, exists, abspath, realpath
import glob
import shutil
import tempfile
import warnings
import sys
import json

import olfactometer
from olfactometer import util


# TODO see note above similar line in util.py as to whether to try replacing
# this w/ pkg_resources
this_package_dir = split(abspath(realpath(__file__)))[0]
sketch_name = 'olfactometer.ino'
sketch_path = join(this_package_dir, 'firmware/olfactometer', sketch_name)
nanopb_dir = join(this_package_dir, 'nanopb')

assert exists(this_package_dir), \
    f'this_package_dir={this_package_dir} does not exist'
assert exists(sketch_path), f'sketch_path={sketch_path} does not exist'
assert exists(nanopb_dir), f'nanopb_dir={nanopb_dir} does not exist'


def generate_nanopb_code(sketch_dir):
    proto_files = glob.glob(join(this_package_dir, '*.proto'))
    assert len(proto_files) == 1, \
        f'len(proto_files) != 1, proto_files={proto_files}'
    proto_file = proto_files[0]

    # Just like protoc, the nanopb generator whines if this isn't passed (if not
    # called from the directory containing the *.proto and *.options files).
    # The the nanopb error message seems wrong (references a --proto_path option
    # that doesn't exist on the nanopb generator. hopefully the -I option they
    # also mention is actually the one parsed by the nanopb generator, and not
    # just something used internally by protoc.)
    proto_path, _ = split(proto_file)

    # (would need to specify in setup.py package_data if we wanted to use this
    # version from our nanopb git submodule)
    #nanopb_generator_cmd = 'python {nanopb_dir}/generator/nanopb_generator.py'

    # This executable is installed when you install nanopb from PyPi.
    nanopb_generator_cmd = 'nanopb_generator'

    nanopb_generator_args = \
        f' --output-dir={sketch_dir} -I {proto_path} {proto_file}'

    full_cmd = nanopb_generator_cmd + nanopb_generator_args
    print(full_cmd)

    # TODO need to check if files that would be outputs of nanopb generator
    # already exist? i assume it would just overwrite them (which is fine)?

    # TODO test this .split() method doesn't break if there are spaces in either
    # the sketch_dir or proto_file path (maybe just use shell=True if so, and
    # don't split()?)
    p = Popen(full_cmd.split(), stdout=DEVNULL)
    p.communicate()

    failure = bool(p.returncode)
    if failure:
        raise RuntimeError('nanopb code generation failed')


def make_arduino_sketch_and_libraries(sketch_dir, arduino_lib_dir,
    use_symlinks=True):

    sketch_dir = abspath(sketch_dir)
    arduino_lib_dir = abspath(arduino_lib_dir)

    if util.in_windows():
        warnings.warn('copying rather than symlinking in sketch + library '
            'creation, because easier on Windows'
        )
        use_symlinks = False

    def copy_or_link(src, dst):
        if use_symlinks:
            os.symlink(src, dst)
        else:
            shutil.copyfile(src, dst)

    # TODO TODO test that in the windows case (where we will be using copying
    # rather than symlinks to avoid having to use elevated permissions / change
    # permissions), the `if not exist(dst)` checks don't lead to these generated
    # files not being updated in some cases where they should!
    # (maybe just always overwrite?)
    # for reference about the windows permission issues, see:
    # https://www.scivision.dev/windows-symbolic-link-permission-enable/
    # https://stackoverflow.com/questions/32877260
    # https://stackoverflow.com/questions/6260149

    ###########################################################################
    # Create the sketch directory
    ###########################################################################
    os.makedirs(sketch_dir, exist_ok=True)
    dest = join(sketch_dir, sketch_name)
    # (if for example, upload is run twice w/ same --build-root argument
    if not exists(dest):
        copy_or_link(sketch_path, dest)
    del dest
    generate_nanopb_code(sketch_dir)

    ###########################################################################
    # Create the Arduino libraries
    ###########################################################################
    os.makedirs(arduino_lib_dir, exist_ok=True)

    nanopb_lib_dir = join(arduino_lib_dir, 'nanopb')
    # exist_ok is a Python 3.2+ feature
    os.makedirs(nanopb_lib_dir, exist_ok=True)

    # These need to be a subset of the *.c and *.h files under nanopb/ or
    # setup.py will not install them correctly (they are now, just noting in
    # case that changes).
    c_and_h_prefixes = ['pb_common', 'pb_encode', 'pb_decode']
    files_to_link = ['pb.h'] + [
        f + s for f in c_and_h_prefixes for s in ('.h','.c')
    ]
    for f in files_to_link:
        dst = join(nanopb_lib_dir, f)
        if not exists(dst):
            src = join(nanopb_dir, f)
            if not exists(src):
                raise IOError(f'required nanopb file {src} not found. try "git '
                    'submodule update --init" from project root (if nanopb or '
                    'nanopb-arduino directories are empty)?'
                )
            copy_or_link(src, dst)

    nanopb_arduino_src_dir = join(this_package_dir, 'nanopb-arduino', 'src')
    nanopb_arduino_lib_dir = join(arduino_lib_dir, 'nanopb-arduino')
    os.makedirs(nanopb_arduino_lib_dir, exist_ok=True)

    files_to_link = glob.glob(join(nanopb_arduino_src_dir, '*'))
    for src in files_to_link:
        dst = join(nanopb_arduino_lib_dir, split(src)[1])
        if not exists(dst):
            copy_or_link(src, dst)


def get_port_and_fqbn(port=None, fqbn=None, will_upload=True):
    """
    Returns (port, fqbn). Any passed inputs will be returned unchanged.

    If only one of the inputs is passed, only boards matching that input will
    be considered.
    """
    # Don't want any of the IOErrors in this case, because only using this
    # function to get the fqbn here. No need to actually communicate with the
    # board.
    if not will_upload and fqbn is not None:
        # TODO maybe still validate the fqbn here though? (could do via output
        # of 'arduino-cli board listall', if appropriate core is installed)
        return port, fqbn

    # This is because arduino-cli hangs for a while (maybe indefinitely?)
    # if it does not exist.
    # Checking for Windows because it seems it's maybe not a regular file on
    # Windows 7, at least from Git bash. It does work in Git bash though,
    # despite the fact that the `exists` check would fail.
    if port is not None:
        if not exists(port) and not util.in_windows():
            raise IOError(f'port {port} does not exist. '
                'is the Arduino connected?'
            )

        elif fqbn is not None:
            # TODO may still want to check it's in the list below in this case,
            # at least to handle the error message here?
            return port, fqbn

    board_list_cmd = 'arduino-cli board list --format json'
    # This will raise error if command fails.
    boards = json.loads(check_output(board_list_cmd.split()).decode())

    if port is None and fqbn is None:
        match_str = ''
    elif port is not None:
        match_str = f' matching port={port}'
    elif fqbn is not None:
        match_str = f' matching fqbn={fqbn}'
    else:
        match_str = f' matching port={port} and fqbn={fqbn}'

    found_fqbn = None
    found_port = None
    for b in boards:
        # TODO do i want to restrict to 'protocol': 'serial'? not sure what else
        # there is...
        try:
            xs = b['boards']
        except KeyError:
            # 'boards' only defined for stuff that is actually real (that has a
            # FQBN?) it seems. e.g. /dev/ttyS0 on my 18.04 machine doesn't have
            # this.t
            continue

        assert len(xs) == 1
        x = xs[0]
        curr_fqbn = x['FQBN']
        if fqbn is not None and curr_fqbn != fqbn:
            # TODO maybe log here w/ reason for skipping
            continue

        curr_port = b['address']
        if port is not None and curr_port != port:
            # TODO maybe log here w/ reason for skipping
            continue

        if found_port is not None:
            # TODO TODO test this case
            raise IOError(f'found multiple boards{match_str}. ambiguous! '
                'try explicitly specifying -p/-f.'
            )

        found_fqbn = curr_fqbn
        found_port = curr_port

    if found_port is None:
        err_msg = f'no boards found{match_str}'

        if not will_upload:
            err_msg += ('. you may instead specify -f/--fqbn since not '
                'uploading.'
            )

        raise IOError(err_msg)

    print(f'Detected board {found_fqbn} on port {found_port}')

    # TODO maybe also parse list of cores and check core of board is supported
    # (mostly so i could also consider installing the missing core at runtime,
    # right before upload)

    return found_port, found_fqbn


def yes_or_no(question):
    while True:
        reply = str(input(question + ' (y/n): ')).lower().strip()
        if reply[:1] == 'y':
            return True
        elif reply[:1] == 'n':
            return False
        else:
            print('Please answer y/n')


# TODO maybe copy current dir (w/ git info) to tempfile dir and change that in
# various ways to unit test?
# TODO could also maybe use `hub` cli tool to automate some github side parts of
# the test (if that wouldn't be too crazy...)
def is_repo_current(repo, warn=True):
    """Fetches from remote and checks if local repo is up-to-date.

    Args:
    repo (`git.Repo`): `gitpython` `Repo` object

    Returns True or False.
    """
    # TODO fetch w/ no authentication even if git auth currently set to ssh, if
    # possible (to not need to type in password for key)
    # (possible in case where it's public at least?)
    fetch_info_list = repo.remotes.origin.fetch()

    # TODO test whether the fetch is required here (if actually behind)
    # (and if not, why not?)
    # https://stackoverflow.com/questions/17224134
    commits_behind = list(repo.iter_commits('master..origin/master'))

    up_to_date = len(commits_behind) == 0
    if not up_to_date and warn:
        warnings.warn('Github version has updates available!')

    return up_to_date


no_clean_hash_str = 'no_clean_git_version'
no_version_available_str = 'no_version_available'
# TODO might make more sense to move to util
# TODO TODO TODO maybe i should have another version string which is just a hash
# of all of the code (maybe processed to exclude stuff like comments before
# hashing)? might be much easier to get to work w/ pip installed deployments
# than anything involving git...
def version_str(update_check=False, update_on_prompt=False):
    """Returns either git hash of this repo or a str indicating none was usable.
    """
    # TODO TODO TODO need search_parent_directories in git.Repo call below? or
    # can i get away without it, maybe with some other processing? cause with
    # it, if i have olfactometer installed in a venv contained inside another
    # git repo, this returns the git hash for THAT project! (disabling all the
    # version checking until this is fixed / i have some way to get a sensible
    # version when deploying via pip)
    # (some other TODOs below related to above...)
    return no_version_available_str

    # NOTE: code below here (in this function) is currently unreachable
    raise NotImplementedError

    if update_on_prompt:
        update_check = True

    if not util.in_docker:
        # Need to import this here because otherwise there is an ImportError
        # that complains about lack of git executable (which we don't need in
        # Docker case anyway)
        import git
        # TODO test this import path also works on my ubuntu installations
        from git.exc import InvalidGitRepositoryError

        # TODO TODO fix so this branch can work in case where script is
        # installed via pip (not editable), and in particular on windows.
        # not sure how i didn't seem to have the same issue on ubuntu, even
        # though "olf" should still have been under some site-packages directory
        # or something like that there too...
        # git.exc.InvalidGitRepositoryError: C:\Users\tom\AppData\Local\
        # Packages\PythonSoftwareFoundation.Python.3.8_qbz5n2kfra8p0\
        # LocalCache\local-packages\Python38\site-packages\olfactometer
        try:
            repo = git.Repo(this_package_dir, search_parent_directories=True)
        except InvalidGitRepositoryError:
            # TODO maybe use pip x.y.z version in this case?
            # or have a file w/ version that gets bumped somehow / generated at
            # build time, maybe in a step before pip based setup.py invocation?
            warnings.warn('version_str could not find a version')
            return no_version_available_str

        # TODO check! this was hack to fix update_check undefined error. seems
        # ok tho.
        up_to_date = True
        #
        if update_check:
            up_to_date = is_repo_current(repo)

        if repo.is_dirty():
            if not up_to_date and update_on_prompt:
                raise RuntimeError('can not update because of uncommitted '
                    'changes'
                )

            warnings.warn('repo has uncommitted changes so not checking / '
                'uploading git hash! only use for testing.'
            )
            return no_clean_hash_str
        else:
            if not up_to_date and update_on_prompt:
                do_update = yes_or_no('Pull changes from Github?')
                if do_update:
                    # TODO check this works
                    repo.remotes.origin.pull()
                    print('Changes pulled from Github. Please re-run script.')
                    sys.exit()

        current_hash = repo.head.object.hexsha
        return current_hash
    else:
        if update_check:
            # TODO TODO implement similar thing for docker (check docker hub)
            warnings.warn('update checking not available in docker version')

        # Should be set with a command line argument in docker_build.sh
        gh_var = 'OLFACTOMETER_VERSION_STR'
        assert gh_var in os.environ
        vstr = os.environ[gh_var]
        # TODO maybe further check that it's either no_clean_hash_str or 
        # something that could be a git hash
        assert len(vstr) > 0, f'{gh_var} not set in Docker build!'
        return vstr


# TODO maybe thread fqbn through args so arduino-cli lookup not always needed
def upload(sketch_dir, arduino_lib_dir, fqbn=None, port=None,
    build_root=None, dry_run=False, show_properties=False,
    arduino_debug_prints=False, verbose=False):

    # TODO maybe just like arduino-cli handle the build + build_cache_path now?
    # (at least, if they'll both be under my root tmpdir anyway...)

    if build_root is None:
        # TODO TODO TODO make sure there are no windows-specific problems with
        # this usage of TemporaryDirectory, as there may have been w/
        # NamedTemp...
        td_tmp_build_dir = tempfile.TemporaryDirectory()
        build_root = td_tmp_build_dir.name
    else:
        td_tmp_build_dir = None

    # This does need to be absolute (tmp_build_dir path is absolute I'm
    # assuming, from behavior of <tempfile.TemporaryDirectory>.name)
    build_path = join(build_root, 'build')
    if exists(build_path):
        shutil.rmtree(build_path)

    # arduino-cli's default seemed to be <sketch_dir>/build for me.
    # might depend on where it was run from though?
    build_cache_path = join(build_root, 'build-cache')
    if exists(build_cache_path):
        shutil.rmtree(build_cache_path)

    port, fqbn = get_port_and_fqbn(port=port, fqbn=fqbn,
        will_upload=not (dry_run or show_properties)
    )

    cmd = (f'arduino-cli compile -b {fqbn} {sketch_dir} '
        f'--libraries {arduino_lib_dir} '
        f'--build-path {build_path} --build-cache-path {build_cache_path}'
    )
    if show_properties:
        # TODO --build-properties is deprecated. this still good?
        cmd += ' --show-properties'

    extra_flag_list = []

    vstr = version_str()
    print(f'Version string being compiled into firmware: {vstr}')

    extra_flag_list.append(f'-DOLFACTOMETER_VERSION_STR={vstr}')

    if arduino_debug_prints:
        extra_flag_list.append('-DDEBUG_PRINTS')

    if len(extra_flag_list) > 0:
        extra_flags = ' '.join(extra_flag_list)
        # Was between this and compiler.c.extra_flags and / or
        # compiler.cpp.extra_flags. I'm assuming this sets both of those?
        # https://github.com/arduino/arduino-cli/issues/210 warns that this can
        # / will override similar flags specified in boards.txt, though I'm not
        # sure that will be an issue we encounter.
        # TODO try to update to (a series of?) --build-property calls, as
        # deprecation warning for --build-properties says
        cmd += f' --build-properties build.extra_flags="{extra_flags}"'

    if verbose:
        cmd += ' -v'
        
    upload_args = f' -u -t -p {port}'
    if not (dry_run or show_properties):
        cmd += upload_args

    print(cmd)

    # TODO add error handling for case when arduino was just plugged in and we
    # are still getting:
    # avrdude: ser_open(): can't open device "/dev/ttyACM0": Device or resource
    # busy
    # ioctl("TIOCMGET"): Inappropriate ioctl for device
    # (some resetting we can do? or just wait?)

    # TODO parse output to check the -t flag indicated successful verification
    # (if returncode is sufficient, no need...)

    # could maybe go back to shell=False if i didn't just cmd.split(), and maybe
    # included all of the portion that needed quoting in one part. switched to
    # shell=True because this is the only way i found (so far) to get both
    # preprocessor defines above (the -D... args) to work together.
    p = Popen(cmd, shell=True)
    p.communicate()

    if td_tmp_build_dir is None:
        if exists(build_path):
            shutil.rmtree(build_path)

        if exists(build_cache_path):
            shutil.rmtree(build_cache_path)
    else:
        # This should delete the contents, as in the if above, without needing
        # to do so explicitly.
        td_tmp_build_dir.cleanup()

    # This p.returncode is set by p.communicate() above.
    failure = bool(p.returncode)
    if failure:
        raise RuntimeError('compilation or upload failed')


def main(port=None, fqbn=None, dry_run=False, show_properties=False,
    arduino_debug_prints=False, build_root=None, use_symlinks=True,
    verbose=False):

    if build_root is None:
        # TODO will this just err if it can't be created?
        # (if not, maybe check exists?)
        td_tmp_build_dir = tempfile.TemporaryDirectory()
        # This should exist for the lifetime of any calling code.
        build_root = td_tmp_build_dir.name
    else:
        td_tmp_build_dir = None
        build_root = abspath(build_root)

    # A temporary directory the .ino will get copied to for build.
    sketch_dir = join(build_root, 'olfactometer')
    arduino_lib_dir = join(build_root, 'libraries')

    # This function will create the folders at the paths in the sketch_dir and
    # arduino_lib_dir arguments.
    make_arduino_sketch_and_libraries(sketch_dir, arduino_lib_dir,
        use_symlinks=use_symlinks
    )

    upload(sketch_dir, arduino_lib_dir, build_root=build_root,
        port=port, fqbn=fqbn, dry_run=dry_run, show_properties=show_properties,
        arduino_debug_prints=arduino_debug_prints, verbose=verbose
    )
    if td_tmp_build_dir is not None:
        td_tmp_build_dir.cleanup()

