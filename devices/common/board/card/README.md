# Board card files

The files an operator copies onto the FAT boot partition of a freshly imaged
Alpine Raspberry Pi card, so the board comes up on Wi-Fi with ssh reachable and
the rest of the install can be driven remotely.

Nothing here is generated. These are the files as they land on the card; edit
the marked values in your copy and copy them across.

The whole procedure is: write the card with Raspberry Pi Imager, drop these
files plus the downloaded `headless.apkovl.tar.gz` onto the FAT partition it
leaves mounted, edit three values, boot. The board converts itself to a
persistent sys install and comes up on Wi-Fi with your key on `root`.

## What goes on the card

| File | Source | Edit |
| --- | --- | --- |
| `headless.apkovl.tar.gz` | downloaded, see below | no, used unmodified |
| `wpa_supplicant.conf` | this directory | yes, SSID, passphrase, country |
| `authorized_keys` | this directory | yes, your operator public key |
| `interfaces` | this directory | no, unless the board is wired |
| `unattended.sh` | this directory | yes, `HOSTNAME`; `TIMEZONE` defaults to `Europe/Berlin` |
| `opt-out` | this directory | no, empty file by design |

`headless.apkovl.tar.gz` is downloaded once and reused for every card:

```sh
curl -LO https://github.com/macmpi/alpine-linux-headless-bootstrap/raw/main/headless.apkovl.tar.gz
```

It comes from
[macmpi/alpine-linux-headless-bootstrap](https://github.com/macmpi/alpine-linux-headless-bootstrap)
and is a standard Alpine overlay tarball. It is used as published: there is
nothing to change inside it, and the rest of the configuration is supplied by
the plain files beside it. On first boot it brings up networking, starts sshd,
and reads the files above off the boot partition.

`opt-out` is an empty marker file that disables the bootstrap's internet
telemetry and connection checks. A board on a deployment network should not be
calling out.

## Editing rules that bite

- **LF line endings.** `wpa_supplicant.conf` saved with CRLF is silently
  ignored, and the board comes up with no Wi-Fi. That failure looks exactly like
  a wrong passphrase, so check the line endings first.
- **Public key only** in `authorized_keys`. Without it the bootstrap leaves root
  reachable over ssh with no password.
- **`country=`** must match where the board runs. A wrong regulatory domain can
  disable the channel the access point is on.

These files carry the Wi-Fi passphrase, so keep your edited copies outside the
repository. They carry base OS setup only: no AWS credentials, no daemon
config, and no release material, so a lost card carries no device identity and
no cloud access.

## What happens on first boot

`unattended.sh` runs as root once networking is up. It enables the community
repository, upgrades packages, installs the fixed board runtime-package
baseline, creates the root partition after the boot FAT, runs `setup-alpine`
for the sys install, writes the Wi-Fi configuration and operator key onto the
new root, verifies them, and reboots into it.

It stops after the OS baseline. Release binaries, daemon configuration, and
services remain manual runbook steps over ssh.

The explicit write onto the new root is the point of the script, not an extra:
the overlay is applied to the tmpfs root of the diskless boot and is not applied
again once the board boots from `mmcblk0p2`. The script refuses to reboot unless
the Wi-Fi configuration, the operator key, and the three runlevel links are
present on the new root, because a board that reboots without them needs
physical recovery, while one that stops is still reachable.

Re-running is safe: an existing filesystem on `/dev/mmcblk0p2` makes it refuse to
repartition.

See the Fresh Board Install section of
[the board runbook](../../../../docs/components/board.md).
