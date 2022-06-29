# Snapplicator

A Python script to duplicate btrfs snaphsot repositories as created by `snapper`.

## What it does

This script duplicates the state of one or several snapper snapshot repositories
(sources) to other btrfs subvolumes (targets). Be aware that the script also
syncs snapshot *removals*, which is why the term "duplication" is used, rather
than "backup".

You can, however, use it to back up your snapper snapshots to other disks, or
even machines, adding some extra resiliency and redundancy in case of disk
failures. Just know that if snapper removes and old snapshot, it will soon be
gone from your backup location, as well.

This is by design, to keep your target subvolumes from ballooning in size.

## Dependencies

Please note that you need Python 3, `btrfs` and `snapper` to use this script.
It has not other dependencies.

## Getting started

### Setup

Before first use, you need to have a dedicated btrfs subvolume prepared as a
target for each snapper snapshot source you wish to duplicate. A target
subvolume may contain other data, but it must not be configured to hold snapper
snapshots of itself, nor must the same target ever be used for more than one
source. Snapplicator will create its own `.snapshots` subvolume within the
target subvolume, but it cannot set up the target itself for you.

Let's assume you have configured `snapper` to make regular snapshots of your
root directory at `/` and you have created a separate btrfs subvolume at
`/backups/root` to serve as target.

### Manual use

To start using `snapplicator` it is a good idea to run it by hand a few times
to make sure everything works.

All you need to start is a config file. This is a YAML file and there is an
example at `examples/config.yml` in the repo. Copy it to your working directory
and edit it to suit your needs.

For our example, we'd make it look like this:

```
config:
    version: 1
duplication_pairs:
  - source: /
    target: /backups/root
```

As you can see from the example, you can add more such stanzas in this file to
let `snapplicator` duplicate serveral snapshot sources at once.

Now run:

```
$ sudo python3 snapplicator -c config.yml -v
```

(The `-c` option tells the script which config to use, the `-v` option lets it
 produce some output to tell you what's going on)

You need root privileges to run the script, since it uses `btrfs` and `snapper`,
both of which require it. Hence the `sudo`.

You should see some output like the following:

```
Missing from target: [22, 23, 24, …]
Superfluous at target: nothing
First missing snapshot is number 22 (predecessor: 21)
```

The numbers will differ, but on first use there should be no superfluous
snapshots at the target.

Once the script has finished (w/o errors), the snapshots have been duplicated
successfully from source to target. Congratulations!

### Configuration

Once you're happy with your config file, you may install it to the system, so
`snapplicator` will find it automatically and you needn't bother with the `-c`
option anymore.

Simply create a directory `/etc/snapplicator` and copy your `config.yml` there
(keeping the name). Snapplicator expects and will look for a config file at
`/etc/snapplicator/config.yml` in the absence of the `-c` option and will us it
if found.

## Automation

Once you have `snapplicator` running correctly when invoked by hand, you may
want to automate it. The repo provides a couple of example `systemd` unit files
to help you do this.

Snapplicator also implements a facility that allows you to run custom scripts
before and/or after execution.

### Service installation

Before using the `systemd` timer and service, you may want to install the
`snapplicator.py` script in a system-wide location, such as
`/usr/local/lib/snapplicator/snapplicator.py` or
`/opt/snapplicator/snapplicator.py`.

For our example, we'll assume `/usr/local/lib/snapplicator/snapplicator.py`.

Snapplicator comes with a `.timer` and `.service` file under `examples/` that
allow it to be run in the background at regular intervals by `systemd`.

Simply copy these to a location where `systemd` will find them, e.g.
`/etc/systemd/system` or `/usr/lib/systemd/system` and adjust the path to the
`snapplicator.py` script file in the ÈxecStart` line in `snapplicator.service`.

For our example, we'll assume the latter.

For intial testing, you may want to add the `-v` flag to the end of the
`ExecStart` line, so you can control the script's output after it's run by the
service.

You may also want to take a peek into the `.timer` file to adjust the timings,
but it's not required. By default, the timer will trigger the service to run 20
minutes after boot (to give `snapper` some time) and then after that at regular
intervals of also 20 minutes. This should be reasonable for most use cases.

After installing the files, `systemd` should list both the timer and the service
as loaded, but dead:

```
$ systemctl status snapplicator.timer snapplicator.service
○ snapplicator.timer - Duplication of Snapper Snapshots
     Loaded: loaded (/usr/lib/systemd/system/snapplicator.timer; disabled; vendor preset: disabled)
     Active: inactive (dead)
    Trigger: n/a
   Triggers: ● snapplicator.service

○ snapplicator.service - Duplication of Snapper Snapshots
     Loaded: loaded (/usr/lib/systemd/system/snapplicator.service; static)
     Active: inactive (dead)
```

The way this works is that the timer triggers individual service runs, so
enabling the service does nothing and starting it merely runs it *once*.

To make the service run regularly, we need to both enable and start the *timer*:

```
> sudo systemctl enable snapplicator.timer
Created symlink /etc/systemd/system/timers.target.wants/snapplicator.timer → /usr/lib/systemd/system/snapplicator.timer.
> sudo systemctl start snapplicator.timer
```

The timer should now be running and it should normally also trigger the first
service run *immediately* (unless it's less than 20 minutes since you booted,
I suppose, but haven't tested).

You can check this with `systemctl status` again, or by looking at the outputs
of `sudo journalctl -u snapplicator.timer` and
`sudo journalctl -u snapplicator.service`.

### Pre- and post-run hooks

Snapplicator looks for two directories:
1. `/etc/snapplicator/prerun-hooks.d`
2. `/etc/snapplicator/postrun-hooks.d`

… and it will run all readable and executable files found within each, in order.

Scripts in the first directory will be run before duplication, those in the
second one after.

This could be used e.g. to mount and unmount the target subvolumes.

Some very simple-minded examples for what could be done with this facility can
be found in `examples/prerun-hooks.d` and `examples/postrun-hooks.d`.
