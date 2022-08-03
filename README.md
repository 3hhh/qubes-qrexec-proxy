# qubes-qrexec-proxy

Intransparent and modular [Qubes OS](https://www.qubes-os.org/) [qrexec](https://www.qubes-os.org/doc/qrexec/) proxy.

[qrexec](https://www.qubes-os.org/doc/qrexec/) is the central inter-VM communication protocol used by [Qubes OS](https://www.qubes-os.org/).
Essentially it is a fully bidirectional protocol where two VMs share a common memory region via [Xen vchan](https://xenbits.xen.org/gitweb/?p=xen.git;a=blob;f=xen/include/public/io/libxenvchan.h;hb=HEAD). After the first initial policy decision Qubes OS `dom0` is no longer involved in the communication in any way. This is done for speed and security reasons.

However this approach results in lack of control of on-going qrexec communication and doesn't e.g. allow one-way communication from one VM to another.

`qrexec-proxy` _partially_ remediates those issues by providing a proxy interface which can be run inside a Qubes OS VM to implement whatever additional restrictions the user desires to impose upon qrexec communication between VMs. Alternatively, additional features can be added to `qrexec`. Some plugins for standard tasks are provided.

Essentially `qrexec-proxy` is a proxy or firewall for `qrexec` communication.

For expert users only.

## Features

- intransparent, i.e. fully manageable via Qubes OS dom0 RPC policies
- modular / plugin-based = easily extensible
- plugins can be combined in chains (`qrexec` traffic first traverses the first plugin, then the second and so on)
- relatively fast (~30-40% speed loss in comparison to native `qrexec`)

## Limitations

- the sender needs to explicitly use the proxy / requires changes to the sender code (1)
- the receiver will see the proxy VM as sender (1)
- only works in Linux VMs
- Python interface only

(1) Upstream [Qubes OS](https://www.qubes-os.org/) RPC policy syntax would need to be extended to support transparent proxying.

## Installation

The below instructions are assumed to be executed inside a template VM or a standalone VM to be used as `qrexec` proxy
unless noted otherwise. For examplary purposes they also assume that you wish to run a proxy VM named `proxy` between
the qrexec communication of the two VMs `src` and `dst`, i.e. `src <--> proxy <--> dst`.

1. Install [python-systemd](https://www.freedesktop.org/software/systemd/python-systemd/).
   E.g. on debian: `apt install python3-systemd`
2. Clone this repository and copy it to a directory of your liking, let's assume `/usr/share/qubes-qrexec-proxy`.
3. Create a `qrexec` symlink: `sudo ln -s /usr/share/qubes-qrexec-proxy/qrexec-proxy /etc/qubes-rpc/qrexec-proxy`.
4. Configure the proxy inside `/usr/share/qubes-qrexec-proxy/plugins/config.json` according to your needs.
   Let's assume that you want to do some basic testing with the `timeout` chain, which loads a single plugin that
   breaks `qrexec` connections after a timeout. The supplied `config.json` already contains that.
5. The below example will also assume that you test with a simple qrexec service that just mirrors incoming data.
   To do this, you'd have to install the [./test/qrexec-mirror](https://github.com/3hhh/qubes-qrexec-proxy/blob/master/test/qrexec-mirror)
   file to the `dst` VM at `/etc/qubes-rpc/qrexec-mirror`.
6. In dom0, configure your RPC policy at e.g. `/etc/qubes/policy.d/12-qrexec-proxy.policy` to allow the proxying.
   For the above `timeout` example you'd have to add the following lines:
   ```
   #allow src <--> proxy
   qrexec-proxy +timeout+dst+qrexec-mirror    src             proxy     allow
   #allow proxy <--> dst
   qrexec-mirror *                            proxy           dst       allow
   ```

## Usage

For the above timeout example you need to execute the following inside the `src` VM:
```
qrexec-client-vm proxy qrexec-proxy+timeout+dst+qrexec-mirror <<< "hello world"
```
It should mirror your `hello world` via the proxy VM.

If you wait for a longer time, it won't be mirrored due to the configured timeout:
```
qrexec-client-vm proxy qrexec-proxy+timeout+dst+qrexec-mirror < <(sleep 3; echo "hello world";)
```
You can check the logs inside the `proxy` VM to see that the timeout was hit: `journalctl -b0`

## Available Plugins

See the [plugins directory](https://github.com/3hhh/qubes-qrexec-proxy/tree/master/plugins). Each plugin has a description at the top of its source code.

## Uninstall

Just remove the directory and symlinks created during the installation. Uninstall `python-systemd`.

## Copyright

© 2022 David Hobach

qubes-qrexec-proxy is released under the GPLv3 license; see `LICENSE` for details.
