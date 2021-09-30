from pathlib import Path
from shutil import copy2, rmtree
from subprocess import PIPE, Popen, run
from time import sleep


SOURCE_BASE_DIR = Path('/.snapshots')
TARGET_BASE_DIR = Path('/mnt/backups/qubes4/root/.snapshots')


def mount_target_dir():
    # This should really be done differently
    run(('mount', '/dev/mapper/sda1_crypt', '/mnt/'))


def umount_target_dir():
    # This should really be done differently
    run(('umount', '/mnt/'))


class PathWrapperError(Exception):
    pass


class PathWrapper:

    error_class = PathWrapperError

    def __init__(self, path):
        """
        Base class for classes that center around a path to an existing directory
        """
        path = self._validate_path(path)
        self._path = path

    def _validate_path(self, path):
        if not isinstance(path, (Path, str)):
            raise self.error_class(
                'Cannot create Path from `{}` type argument: '
                '"{}"'.format(type(path), path)
            )
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_dir():
            raise self.error_class(
                'Path "{}" is not a directory!'.format(path)
            )
        # TODO: Test readability
        return path

    @property
    def path(self):
        return self._path


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
            self.error_class('Snapshot argument "{}" is not a Snapshot object!'.format(snapshot))
        self._snapshot = snapshot

    @property
    def command(self):
        parent = ''
        if self._parent_path:
            parent = '-p {} '.format(self._parent_path)
        return 'btrfs send {}{}'.format(parent, self.path)

    def open(self):
        btrfs_send_process = Popen(self.command.split(), stdout=PIPE)
        return btrfs_send_process.communicate()[0]

    @property
    def snapshot(self):
        return self._snapshot


class SnapshotError(Exception):
    pass


class Snapshot(PathWrapper):

    error_class = SnapshotError

    def __init__(self, path, predecessor=None):
        """
        """
        super().__init__(path)
        self._info = self.path / 'info.xml'
        self._snapshot = self.path / 'snapshot'
        if not self._is_snapper_snapshot():
            raise self.error_class(
                'This does not look like a snapper snapshot! '
                'Path: "{}"'.format(path)
            )
        if predecessor and not isinstance(predecessor, Snapshot):
            raise self.error_class(
                'Supplied predecessor argument is not a Snapshot object!'
            )
        self._predecessor = predecessor

    def _is_snapper_snapshot(self):
        try:
            int(self.path.stem)
        except ValueError:
            return False
        # TODO: check whether 'self.snapshot' actually looks like a btrfs snapshot
        return self.snapshot.is_dir() and self.info.is_file()

    def delete(self):
        """
        Delete the entire snapshot
        """
        Popen(('btrfs', 'subvolume', 'delete', '-c', str(self.snapshot)))
        self.info.unlink()
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
            raise self.error_class(
                'This does not look like a snapper snapshot directory! '
                'Path: "{}"'.format(path)
            )

    def _is_snapper_snapshot_directory(self):
        # TODO: Do something with `self._path.glob(…)` and the idea that snapper
        # snapshot directories conform to a well defined tree structure, like:
        # +- 1 +- info.xml 
        # |    +- snapshot +- …
        # |                +- …
        # +- 2 +- info.xml
        # |    +- snapshot +- …
        # |                +- …
        # …
        # +-[n]+- info.xml
        # |    +- snapshot +- …
        # |                +- …
        # …
        return True

    def delete_snapshot(self, number):
        self.get_snapshot(number).delete()

    def get_snapshot(self, number, with_predecessor=True):
        """
        """
        if not isinstance(number, int):
            raise self.error_class(
                'Unable to get snapshot "{}". '
                'Argument must be a number!'.format(number))
        predecessor = None
        if with_predecessor:
            next_lowest_number = max({n for n in self.numbers if n < number})
            predecessor = Snapshot(self.path / str(next_lowest_number))
        try:
            return Snapshot(self.path / str(number), predecessor)
        except SnapshotDirectoryError:
            raise self.error_class(
                'Cannot get snapshot number {}! No such snapshot in this '
                'snapshot directory "{}"?'.format(number, self.path)
            )

    @property
    def numbers(self):
        return {snapshot.number for snapshot in self.snapshots}

    def receive(self, info_path, btrfs_stream, number):
        if not info_path.is_file():
            raise self.error_class('Supplied info path "{}" is not a file!'.format(info_path))
        if not isinstance(btrfs_stream, BtrfsStream):
            raise self.error_class('Supplied argument "{}" is not a BtrfsStream '
                                   'object!'.format(btrfs_stream))
        target_path = self.path / str(number)
        mode = 0o0750
        if btrfs_stream.snapshot:
            mode = btrfs_stream.snapshot.path.stat().st_mode
        # Ensure that the target directory exists
        target_path.mkdir(mode, exist_ok=True)
        # Copy the 'info.xml' file
        copy2(str(info_path), str(target_path))
        # Run the actual send/receive commands
        btrfs_receive_process = Popen(('btrfs', 'receive', str(target_path)), stdin=PIPE)
        btrfs_receive_process.communicate(input=btrfs_stream.open())
        # TODO: There should be some error handling to remove the info.xml and target
        #       directory again, in case something goes wrong here.

    def send_snapshot(self, number):
        snapshot = self.get_snapshot(number)
        return snapshot.send()

    @property
    def snapshots(self):
        predecessor = None
        for path in self.path.iterdir():
            snapshot = Snapshot(path, predecessor)
            yield snapshot
            predecessor = snapshot

def main():
    mount_target_dir()
    source = SnapshotDirectory(SOURCE_BASE_DIR)
    target = SnapshotDirectory(TARGET_BASE_DIR)
    missing_snapshot_numbers = source.numbers - target.numbers
    superfluous_snapshot_numbers = target.numbers - source.numbers
    print('Missing from target: {}'.format(sorted(missing_snapshot_numbers) or 'nothing'))
    print('Superfluous at target: {}'.format(sorted(superfluous_snapshot_numbers) or 'nothing'))
    if missing_snapshot_numbers:
        first_missing_snapshot = source.get_snapshot(min(missing_snapshot_numbers))
        print(
            'First missing snapshot is number {} (predecessor: {})'.format(
                first_missing_snapshot.number,
                first_missing_snapshot.predecessor.number
            )
        )
    for missing_snapshot_number in sorted(missing_snapshot_numbers):
        info, btrfs_stream = source.send_snapshot(missing_snapshot_number)
        target.receive(info, btrfs_stream, missing_snapshot_number)
    for superfluous_snapshot_number in sorted(superfluous_snapshot_numbers):
        target.delete_snapshot(superfluous_snapshot_number)
    umount_target_dir()


if __name__ == '__main__':
    main()
