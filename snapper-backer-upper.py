from argparse import ArgumentParser
from pathlib import Path
from shutil import copy2, rmtree
from subprocess import DEVNULL, PIPE, Popen, run
from time import sleep
import os


SOURCE_BASE_DIR = Path('/.snapshots')
TARGET_BASE_DIR = Path('/mnt/backups/qubes4/root/.snapshots')
VERBOSE = False


def get_arguments():
    parser = ArgumentParser()
    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='explain what is being done')
    return parser.parse_args()


def output(message):
    if VERBOSE:
        print(message)


def process_arguments():
    arguments = get_arguments()
    global VERBOSE
    VERBOSE = arguments.verbose


class PathWrapperError(Exception):
    pass


class PathWrapper:

    error_class = PathWrapperError

    def __init__(self, path):
        """
        Base class for classes that center around a path to an existing directory

        :param path: path to an existing directory
        :type path: str or Path
        """
        path = self._validate_path(path)
        self._path = path

    def _validate_path(self, path):
        if not isinstance(path, (Path, str)):
            self.error(
                'Cannot create Path from `{}` type argument: '
                '"{}"'.format(type(path), path)
            )
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_dir():
            self.error('Path "{}" is not a directory!'.format(path))
        if not os.access(str(path), os.R_OK):
            self.error('Path "{}" is not readable!'.format(path))
        return path

    @property
    def path(self):
        return self._path

    def error(self, message):
        """
        Raise an exception of the type stored in `self.error_class`
        """
        raise self.error_class(message)


class BtrfsStreamError(Exception):
    pass


class BtrfsStream(PathWrapper):

    error_class = BtrfsStreamError

    def __init__(self, path, parent_path=None, snapshot=None):
        super().__init__(path)
        if parent_path:
            parent_path = self._validate_path(parent_path)
        self._parent_path = parent_path
        if snapshot and not isisintance(snapshot, Snapshot):
            self.error('Snapshot argument "{}" is not a Snapshot object!'.format(snapshot))
        self._snapshot = snapshot

    @property
    def command(self):
        parent = ''
        if self._parent_path:
            parent = '-p {} '.format(self._parent_path)
        return 'btrfs send {}{}'.format(parent, self.path)

    def open(self):
        btrfs_send_process = Popen(self.command.split(), stdout=PIPE, stderr=DEVNULL)
        return btrfs_send_process.communicate()[0]

    @property
    def snapshot(self):
        return self._snapshot


class SnapshotError(Exception):
    pass


class Snapshot(PathWrapper):

    error_class = SnapshotError

    def __init__(self, path, incomplete=False, predecessor=None):
        """
        Snapper snapshot wrapper class

        :param path: path to an existing, numbered snapshot directory
        :type path: str or Path
        :param incomplete: whether this snapshot may be incomplete, defaults to False
        :type incomplete: bool
        :param predecessor: the snapshot preceding this one in the collection.
        :type predecessor: Snapshot
        """
        super().__init__(path)
        self._incomplete = incomplete
        self._info = self.path / 'info.xml'
        self._snapshot = self.path / 'snapshot'
        if not incomplete and not self._is_snapper_snapshot():
            self.error(
                'This does not look like a snapper snapshot! '
                'Path: "{}"'.format(path)
            )
        if predecessor and not isinstance(predecessor, Snapshot):
            self.error(
                'Supplied predecessor argument is not a Snapshot object!'
            )
        self._predecessor = predecessor

    def _is_snapper_snapshot(self):
        try:
            int(self.path.stem)
        except ValueError:
            return False
        if not self.snapshot.is_dir():
            return False
        if Popen(('btrfs', 'subvolume', 'show', str(self.snapshot)), stdout=DEVNULL).wait() != 0:
            return False
        return self.info.is_file()

    def delete(self):
        """
        Delete the entire snapshot
        """
        if self.snapshot.exists():
            # TODO: Generate output for deletion, if verbose
            btrfs_process = Popen(('btrfs', 'subvolume', 'delete', '-c', str(self.snapshot)),
                                  stdout=DEVNULL)
            if btrfs_process.wait() != 0:
                self.error('Cannot delete btrfs subvolume "{}"!'.format(self.snapshot))
        try:
            self.info.unlink()
        except FileNotFoundError:
            pass
        # Sometimes it takes a little while for the files/dirs to actually disappear.
        attempts = 8
        while attempts and (self.info.exists() or self.snapshot.exists()):
            attempts -= 1
            sleep(0.25)
        self.path.rmdir()

    @property
    def info(self):
        return self._info

    @property
    def number(self):
        return int(self.path.stem)

    @property
    def predecessor(self):
        return self._predecessor

    def receive(self, info_path, btrfs_stream):
        """
        Receive Snapper snapshot
        """
        if not info_path.is_file():
            self.error('Supplied info path "{}" is not a file!'.format(info_path))
        if not isinstance(btrfs_stream, BtrfsStream):
            self.error('Supplied argument "{}" is not a BtrfsStream '
                                   'object!'.format(btrfs_stream))
        # Copy the 'info.xml' file
        # TODO: Generate output, if verbose
        # TODO: Check if successful, raise error if not
        copy2(str(info_path), str(self.path))
        # Run the actual send/receive commands
        # TODO: Generate output, if verbose
        # TODO: Check if successful, raise error if not
        btrfs_receive_process = Popen(('btrfs', 'receive', str(self.path)), stdin=PIPE, stdout=DEVNULL, stderr=DEVNULL)
        btrfs_receive_process.communicate(input=btrfs_stream.open())

    def send(self):
        parent_path = None
        if self.predecessor:
            parent_path = self.predecessor.snapshot
        return self.info, BtrfsStream(self.snapshot, parent_path)

    @property
    def snapshot(self):
        return self._snapshot


class SnapshotDirectoryError(Exception):
    pass


class SnapshotDirectory(PathWrapper):

    error_class = SnapshotDirectoryError

    def __init__(self, path):
        super().__init__(path)
        if not self._is_snapper_snapshot_directory():
            self.error(
                'This does not look like a snapper snapshot directory! '
                'Path: "{}"'.format(path)
            )

    def _is_snapper_snapshot_directory(self):
        # Validate that all subdirs are numbers
        # Note that this ignores other files in the snapshot directory!
        try:
            snapshot_numbers = self.numbers
        except self.error_class:
            return False
        # Check that all the numbered subdirs have a 'snapshot' directory
        # Note that we're not checking for the presence of 'info.xml' at this point!
        return all([(self.path / str(number) / 'snapshot').is_dir()
                    for number in snapshot_numbers])

    def _numbers(self):
        for directory in [path for path in self.path.iterdir() if path.is_dir()]:
            try:
                yield int(directory.name)
            except ValueError:
                self.error('Supposed snapshot dir "{}" does not have an integer numerical name!'.format(directory))

    def delete_snapshot(self, number):
        self.get_snapshot(number).delete()

    def get_snapshot(self, number, with_predecessor=True):
        """
        """
        if not isinstance(number, int):
            self.error(
                'Unable to get snapshot "{}". '
                'Argument must be a number!'.format(number)
            )
        predecessor = None
        if with_predecessor:
            next_lowest_number = max({n for n in self.numbers if n < number})
            predecessor = Snapshot(self.path / str(next_lowest_number))
        try:
            return Snapshot(self.path / str(number), predecessor=predecessor)
        except SnapshotDirectoryError:
            self.error(
                'Cannot get snapshot number {}! No such snapshot in this '
                'snapshot directory "{}"?'.format(number, self.path)
            )

    @property
    def numbers(self):
        return {n for n in self._numbers()}

    def receive_snapshot(self, info_path, btrfs_stream, number):
        target_path = self.path / str(number)
        mode = 0o0750
        if btrfs_stream.snapshot:
            mode = btrfs_stream.snapshot.path.stat().st_mode
        # Ensure that the target directory exists
        target_path.mkdir(mode, exist_ok=True)
        # Initialise the target snapshot in incomplete state
        snapshot = Snapshot(target_path, incomplete=True)
        # Delegate actual reception to it
        try:
            snapshot.receive(info_path, btrfs_stream)
        except SnapshotError:
            snapshot.delete()
            raise

    def send_snapshot(self, number):
        snapshot = self.get_snapshot(number)
        return snapshot.send()

    @property
    def snapshots(self):
        predecessor = None
        for path in self.path.iterdir():
            snapshot = Snapshot(path, predecessor=predecessor)
            yield snapshot
            predecessor = snapshot


class ScriptDirectoryError(Exception):
    pass


class ScriptDirectory(PathWrapper):

    error_class = ScriptDirectoryError

    @property
    def scripts(self):
        for path in self.path.iterdir():
            if path.is_file() and os.access(str(path), os.R_OK|os.X_OK):
                yield path


def run_scripts_in(path):
    try:
        script_directory = ScriptDirectory(path)
    except PathWrapperError:
        # No script dir or script dir not readable? No big deal!
        return
    for script in script_directory.scripts:
        output('Running script "{}"…'.format(script))
        run(str(script))


def main():
    source = SnapshotDirectory(SOURCE_BASE_DIR)
    target = SnapshotDirectory(TARGET_BASE_DIR)
    missing_snapshot_numbers = source.numbers - target.numbers
    superfluous_snapshot_numbers = target.numbers - source.numbers
    output('Missing from target: {}'.format(sorted(missing_snapshot_numbers) or 'nothing'))
    output('Superfluous at target: {}'.format(sorted(superfluous_snapshot_numbers) or 'nothing'))
    if missing_snapshot_numbers:
        first_missing_snapshot = source.get_snapshot(min(missing_snapshot_numbers))
        output(
            'First missing snapshot is number {} (predecessor: {})'.format(
                first_missing_snapshot.number,
                first_missing_snapshot.predecessor.number
            )
        )
    for missing_snapshot_number in sorted(missing_snapshot_numbers):
        info, btrfs_stream = source.send_snapshot(missing_snapshot_number)
        target.receive_snapshot(info, btrfs_stream, missing_snapshot_number)
    for superfluous_snapshot_number in sorted(superfluous_snapshot_numbers):
        target.delete_snapshot(superfluous_snapshot_number)


if __name__ == '__main__':
    process_arguments()
    run_scripts_in('/etc/snapplicator/prerun-hooks.d')
    main()
    run_scripts_in('/etc/snapplicator/postrun-hooks.d')
