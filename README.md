# mu2edaq-CFOControl

Python command-line client for the otsdaq **MacroMaker UDP remote-control
interface**. It lists the front-ends a MacroMaker knows about, lists the FE
macros a front-end registered, and runs one macro with positional inputs.
It is a Python port of otsdaq-utilities' C++ `ots_mm_udp_test`, with YAML
configuration and IPv6 added.

> **Warning: this tool can write to the production timing master.** The macros
> a CFO front-end registers include `CFO Write`, `CFO Halt`, `CFO Hard Reset`
> and `Launch Runplan`. CFOControl has no confirmation prompt, dry-run or
> read-back, and the MacroMaker runs every UDP request as `NO-USER` with full
> permissions. There is also a known defect: a macro with **two or more
> inputs** is mis-framed on the wire, so `CFO Write` does not receive its
> `writeData` argument. Until that is fixed, use the MacroMaker web GUI for
> writes, and confirm every write with `CFO Read`. Details:
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#write-safety-assessment).

## Requirements

- Python 3.9 or later
- PyYAML (`python3 -c 'import yaml'` must succeed)
- network reach to a MacroMaker supervisor started with both
  `OTS_MACROMAKER_UDP_IP` and `OTS_MACROMAKER_UDP_PORT` set in its environment;
  without them the supervisor opens no UDP listener

There is no build step, `requirements.txt` or bootstrap script. The superproject's
`testing/common.sh` deliberately skips venv creation for this package
(`pkg_needs_venv`), so it normally runs on the system `python3`.

## Usage

```bash
cd ~/mu2edaq-main/mu2edaq-CFOControl

# list front-ends
python3 CFOControl.py --host mu2e-cfo-01 --port 5000

# list a front-end's macros, with input/output counts
python3 CFOControl.py --host mu2e-cfo-01 --fe CFO0

# show the input names of one macro
python3 CFOControl.py --host mu2e-cfo-01 --fe CFO0 --cmd "CFO Read" --list-inputs

# run a single-input read
python3 CFOControl.py --host mu2e-cfo-01 --fe CFO0 --cmd "CFO Read" --inputs 0x9100
```

Macro names must match exactly, including spaces; quote them. The docstring
example `--cmd "SetRegister" --inputs 0x9100 0x1` names a macro that does not
exist and targets the CFO Control Register reset bit. Do not copy it.

From the control room, `crs-app start cfocontrol` opens a terminal running
`start-mu2edaq-cfocontrol.sh`. That script passes `--port $CRS_PORT_MACROMAKER`
(default 5000) followed by any arguments you give it:

```bash
./start-mu2edaq-cfocontrol.sh --host mu2e-cfo-01 --fe CFO0
```

`stop-mu2edaq-cfocontrol.sh` is a no-op; there is no persistent process.

## Configuration

`config.yaml`, next to `CFOControl.py`, sets `connection.host`,
`connection.port`, `timeouts.first_packet` (10 s), `timeouts.next_packet`
(0.2 s) and `logging.level`/`logging.verbose_udp`. Command-line options
override it. No environment variable is read by the Python. See
`man 5 config.yaml` (`man/man5/config.yaml.5`).

## Files

| Path | Purpose |
|---|---|
| `CFOControl.py` | CLI |
| `ots_mm_udp_interface.py` | protocol library (`OtsMMUdpInterface`) |
| `config.yaml` | default configuration |
| `start-mu2edaq-cfocontrol.sh`, `stop-mu2edaq-cfocontrol.sh` | control-room wrappers |
| `docs/ARCHITECTURE.md` | design, data flow, write-safety assessment |
| `docs/INTERFACES.md` | MacroMaker UDP wire protocol, CFO macro inventory |
| `docs/ISSUES-PENDING.md` | review findings staged for filing |
| `man/` | `CFOControl.py(1)`, `start-`/`stop-mu2edaq-cfocontrol.sh(1)`, `ots_mm_udp_interface(3)`, `config.yaml(5)` |

Read a man page without installing it:

```bash
man ./man/man1/CFOControl.py.1
```

## Tests

None. See CFO-005 in `docs/ISSUES-PENDING.md`.

## License

MIT; see `LICENSE`.
