from pathlib import Path
from subprocess import run


SOURCE_BASE_DIR = Path('/.snapshots')
TARGET_BASE_DIR = Path('/mnt/backups/qubes4/root/.snapshots')


def mount_target_dir():
    # This should really be done differently
    run(('mount', '/dev/mapper/sda1_crypt', '/mnt/'))


def umount_target_dir():
    # This should really be done differently
    run(('umount', '/mnt/'))


class PathWrapper:

    def __init__(self, path):
        """
        """
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
        self._path = path


class SnapshotError(Exception):
    pass


class Snapshot(PathWrapper):

    error_class = SnapshotError

    def __init__(self, path, predecessor=None):
        """
        """
        super().__init__(path)
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
        # TODO: implement
        return True

    @property
    def number(self):
        # TODO: This could probably be done better…
        # … more robustly, for one.
        return int(self._path.parts[-1])

    @property
    def predecessor(self):
        return self._predecessor


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

    @property
    def path(self):
        return self._path

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
    for snapshot_directory in (source, target):
        print('Snapshots at "{}":'.format(snapshot_directory.path))
        for snapshot in snapshot_directory.snapshots:
            predecessor = ''
            if snapshot.predecessor:
                predecessor = ' (predecessor: {})'.format(snapshot.predecessor.number)
            print('* Snapshot {}{}'.format(snapshot.number, predecessor))
    umount_target_dir()


if __name__ == '__main__':
    main()
