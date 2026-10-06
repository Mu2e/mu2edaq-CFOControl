# mu2edaq-CFOControl — interfaces

This page documents the one external interface CFOControl uses: the **otsdaq
MacroMaker UDP remote-control protocol**. Before this review the protocol was
documented nowhere except as code. The description below is derived from the
client (`ots_mm_udp_interface.py`). It was then checked against the server,
`MacroMakerSupervisor::RemoteControlWorkLoop` in **otsdaq-utilities**
(`otsdaq-utilities/MacroMaker/MacroMakerSupervisor.cc`, checkout `69f05f85`,
outside `mu2edaq-main`), and against the C++ reference client CFOControl was
ported from (`otsdaq-utilities/test/ots_mm_udp_interface.cpp`).

> **Correction to the review brief.** The brief described the UDP endpoint as
> "served by `otsdaq-mu2e`'s `CFOFrontEndInterface`". It is not. The UDP
> listener is the MacroMaker supervisor (otsdaq-utilities). The MacroMaker
> forwards each request over SOAP to the FE supervisor that owns the target
> front-end. `CFOFrontEndInterface` (otsdaq-mu2e) only *registers the FE
> macros* that end up being run
> (`otsdaq-mu2e/otsdaq-mu2e/FEInterfaces/CFOFrontEndInterfaceImpl.cc:149`,
> `CFOandDTCCore/CFOandDTCCoreVInterface.cc:148`).

## 1. Endpoint and transport

| Property | Value | Source |
|---|---|---|
| Transport | UDP/IPv4 or IPv6, one request datagram per call | `ots_mm_udp_interface.py:111-122` |
| Server address | `$OTS_MACROMAKER_UDP_IP` in the MacroMaker supervisor's environment | `MacroMakerSupervisor.cc:469` |
| Server port | `$OTS_MACROMAKER_UDP_PORT` in the MacroMaker supervisor's environment | `MacroMakerSupervisor.cc:471` |
| Listener enabled | only when **both** variables are set at supervisor start | `MacroMakerSupervisor.cc:128-150` |
| Client default destination | `127.0.0.1:5000` | `config.yaml:11-12`, `CFOControl.py:55-59` |
| Control-room destination port | `$CRS_PORT_MACROMAKER`, default 5000 | `start-mu2edaq-cfocontrol.sh:16` |
| Authentication | **none**. Every request runs as user `NO-USER` with permission `allUsers: 255` | `MacroMakerSupervisor.cc:560-561` |

**Port 5000 is a client-side convention only.** The server binds whatever
`OTS_MACROMAKER_UDP_PORT` says. Nothing in `mu2edaq-main` sets that variable;
the only mention is a usage comment in
`otsdaq-utilities/test/ots_mm_udp_test.cpp:7`. The 5000 in `config.yaml`,
the start script and `mu2edaq-controlroom-setup/config/apps.yaml:133` must be
matched by hand to the MacroMaker's environment (finding CFO-007).

Server polling: the work loop calls `receive()` with a 1 µs timeout and then
sleeps 1 ms (`MacroMakerSupervisor.cc:509-606`). It handles requests strictly
one at a time, so a long-running macro blocks every other UDP client.

## 2. Messages

All requests are UTF-8 text, `;`-separated. The server splits the **whole
datagram** on `;` (`StringMacros::getVectorFromString(buffer, {';'})`,
`MacroMakerSupervisor.cc:541`), so a literal `;` inside any field breaks the
framing. This is the root cause of CFO-001.

### 2.1 `GetFrontendMacroInfo`

Request: the exact string `GetFrontendMacroInfo`, with no arguments
(`ots_mm_udp_interface.py:215`; server match `MacroMakerSupervisor.cc:518`).

Server side effect: it `mkdir`s `MACROS_DB_PATH/NO-USER/` and
`MACROS_HIST_PATH/NO-USER/` before answering.

Reply: one XML document, serialized without whitespace and possibly split
across several datagrams:

```xml
<ROOT><DATA>
  <FEMacros value='<sup>;<lid>;<feType>;<feUID>;<macro>;<macro>;...'/>   <!-- one per FE interface -->
  ...
  <PublicMacro  value='name:1:nIn:in...:nOut:out...'/>                  <!-- stored user macros -->
  <PrivateMacro value='...'/>
</DATA></ROOT>
```

Each `FEMacros` value is `;`-separated:

| Index | Content |
|---|---|
| 0 | parent supervisor name |
| 1 | parent supervisor LID |
| 2 | FE interface type (plugin class), e.g. `CFOFrontEndInterface` |
| 3 | FE interface UID, e.g. `CFO0` |
| 4… | repeated macro records |

Each macro record is
`name ; permissions ; tooltip ; nIn ; in_1 … in_nIn ; nOut ; out_1 … out_nOut`.
Names may be URI-encoded; CFOControl decodes them before comparing
(`ots_mm_udp_interface.py:297`). Parsing is `_iter_commands`
(`ots_mm_udp_interface.py:262-288`). The tooltip position agrees with the C++
reference parser (`ots_mm_udp_interface.cpp:596-618`). The reference's own
format comment at `:516`, which omits the tooltip, is stale.

CFOControl ignores the `permissions` field. The server would ignore it too,
because the UDP path grants permission 255.

> **Cross-package observation (not verified).**
> `mu2edaq-commandline-tools/src/mu2edaq_commandline_tools/otsdaq/client.py:291`
> parses the `FEMacros` value from the HTTP `getFEMacroList` request as
> `:`-separated with **no** tooltip field. Both the HTTP and the UDP path are
> produced by the same `MacroMakerSupervisor::getFEMacroList`
> (`MacroMakerSupervisor.cc:3886`), which copies the FE supervisor's string
> verbatim. The two clients therefore cannot both be right. The string is
> built by otsdaq core, which is not on disk, so this review does not say
> which one is. Flagged for the commandline-tools reviewer.

### 2.2 `RunFrontendMacro`

Request, built at `ots_mm_udp_interface.py:409-419`:

```
RunFrontendMacro;<feType>;<feUID>;fe;<enc(macroName)>;<inputs>;<outputs>;<save>
  field:  0         1        2     3        4             5        6       7
```

Server interpretation (`MacroMakerSupervisor.cc:541-561`):

| Field | Server use |
|---|---|
| < 8 fields | rejected with `Error: Missing input arguments…` |
| 1 | FE type; `""` means all types |
| 2 | FE UID; CSV multi-select allowed; `""` means `*` (all) |
| 3 | `fe`, `public` or `private`; CFOControl always sends `fe` |
| 4 | macro name, URI-decoded once |
| 5 | input arguments, URI-decoded **once**, then parsed as `name,value;name,value` |
| 6 | output names, URI-decoded once, `,`-separated |
| 7 | `1` writes the outputs to a file instead of returning them; CFOControl sends `0` |
| > 8 fields | **silently ignored** |

What the C++ reference sends in field 5 is
`encodeURIComponent( enc(name1) "," value1 ";" enc(name2) "," value2 … )`. It
is "double encoded" (`ots_mm_udp_interface.cpp:1077`), so the inner `;` and
`,` travel as `%3B` and `%2C`. Field 6 is likewise
`encodeURIComponent(join(enc(name), ","))` (`:1092`).

What CFOControl sends in field 5 is `enc(name1),enc(value1);enc(name2),enc(value2)`.
The pairs are joined with a **raw** `;` (`build_input_string`,
`ots_mm_udp_interface.py:473-479`). As a result, for any macro with two or more
inputs:

- input 1 arrives in field 5;
- input 2 arrives in field 6 and is taken as the output-name list;
- the remaining inputs, the real output list and the save flag shift into
  fields ≥ 7. Field 7 is no longer `0` or `1`, so `saveOutputs` is false.

Verified with a mock MacroMaker during this review (re-run 2026-10-06 with an
independent mock; identical field split). The server-side view is
printed by splitting the datagram exactly as `MacroMakerSupervisor.cc:541` does:

```
$ CFOControl.py --host 127.0.0.1 --port 15077 --fe CFO0 --cmd "CFO Write" --inputs 0x9100 0x1
RX 9 fields: ['RunFrontendMacro', 'CFOFrontEndInterface', 'CFO0', 'fe', 'CFO%20Write',
              'address,0x9100', 'writeData,0x1', '', '0']
  server view: inputArgs='address,0x9100' outputArgs='writeData,0x1' saveOutputs=False
```

`CFO Write` declares inputs `address`, `writeData`
(`CFOFrontEndInterfaceImpl.cc:152`). It therefore receives only `address`.
Its body reads `writeData` with `__GET_ARG_IN__`
(`CFOFrontEndInterfaceImpl.cc:3283`). Whether that throws or defaults is
defined in otsdaq core, which is not on disk; this review did not verify it.
Single-input and zero-input macros frame correctly. Finding CFO-001.

The output-name field differs too. CFOControl encodes the joined list once
(`encode_uri_component(",".join(names))`, `ots_mm_udp_interface.py:405`), so
after the server's single decode the FE receives plain names such as
`Link Status,Temp`. The reference encodes each name and then the list, so the
FE receives `Link%20Status,Temp`. How the FE supervisor matches these names is
in otsdaq core, which is not on disk, so the effect on names containing spaces
was not verified.

### 2.3 Replies to `RunFrontendMacro`

| Outcome | Wire form | Detected by CFOControl? |
|---|---|---|
| Success | `<ROOT><DATA><feMacroExec value='name'><exec_time…/><fe_uid…/><fe_type…/><fe_context…/><fe_supervisor…/><fe_hostname…/><outputArgs_name value='…'/><outputArgs_value value='…'/>…</feMacroExec></DATA></ROOT>` | yes; values extracted in order (`ots_mm_udp_interface.py:436-443`) |
| FE macro threw | `<Error value='Attempted FE Macro Failed…'/>` inside the XML (`MacroMakerSupervisor.cc:3815`) | yes (`ots_mm_udp_interface.py:429-433`) → exit 1 |
| Supervisor-level exception: unknown FE UID or type, FE supervisor not configured, bad framing, unknown command | **plain text** `Error: <message>`, not XML (`MacroMakerSupervisor.cc:591`, `:598`) | **no** → zero outputs, exit 0 (CFO-002) |

The reference client treats any reply that starts with `Error` as a failure
(`ots_mm_udp_interface.cpp:1148`). The Python port lost that check. Concrete
server messages that take the plain-text path include
`The FE Supervisor Index does not exist. Have you configured the state machine
properly?` (`MacroMakerSupervisor.cc:3744`) and `… was not found in the list of
front ends` (`:3729`).

Output values are URI-encoded on the wire. CFOControl decodes them for display
(`CFOControl.py:294`).

## 3. Framing, timing and truncation

| Property | Behaviour | Source |
|---|---|---|
| Fragmentation | One logical reply may span several datagrams; the client concatenates in arrival order. There is no length prefix, sequence number or terminator. | `ots_mm_udp_interface.py:186-200` |
| End of reply | Inferred when no datagram arrives within `timeouts.next_packet` (default 0.2 s) | `ots_mm_udp_interface.py:191` |
| First datagram | Waits up to `timeouts.first_packet` (default 10 s) | `config.yaml:18` |
| Max datagram | `recvfrom(5000)`; a larger datagram is truncated by the kernel without an error | `ots_mm_udp_interface.py:19`, `:132` |
| Source check | None; any datagram arriving at the ephemeral port is accepted | `ots_mm_udp_interface.py:132` |
| Retries | None | — |

Consequences, all verified against the mock:

- **Truncated reply.** If a fragment is delayed by more than 0.2 s or lost, the
  reply is cut short silently. For `RunFrontendMacro` CFOControl prints the
  outputs it found, logs `WARNING: Expected N output(s) but received M` and
  **exits 0**. A test with a 0.5 s gap between two fragments printed only
  `Link Status: OK` and exited 0. For `GetFrontendMacroInfo` a cut inside an
  `FEMacros` element drops that front-end and every later one. No warning is
  printed; the visible symptom is `Frontend UID 'X' not found`. (CFO-004)
- **Slow macro.** A macro that takes longer than `first_packet` to answer
  produces `Empty response when executing command…` and exit 1. The macro is
  **not cancelled** on the server and may already have run. Re-issuing it runs
  it again.
- **Reused socket.** One `OtsMMUdpInterface` object keeps one socket. A late
  fragment of reply *n* is read as the first datagram of reply *n+1*. The
  one-shot CLI is unaffected because it exits after one macro. Library callers
  that issue several macros are affected.

## 4. URI encoding

| Function | Behaviour | Source |
|---|---|---|
| `encode_uri_component` | Keeps Unicode letters and digits (`str.isalpha()`/`isdigit()`). Every other character becomes `%XX` per UTF-8 byte. This is stricter than JavaScript's `encodeURIComponent`, which keeps ``-_.!~*'()``. | `ots_mm_udp_interface.py:28-37` |
| `decode_uri_component` | `%XX` → `chr(0xXX)`, one byte at a time, so a multi-byte UTF-8 sequence decodes as Latin-1 mojibake. Malformed escapes are passed through. | `ots_mm_udp_interface.py:40-55` |

The asymmetry does not matter for current CFO/DTC macro names, which are ASCII.
It would matter for non-ASCII output values.

## 5. Macros a CFO front-end exposes

Registered by otsdaq-mu2e at the reviewed commit. Names are exact and must be
quoted on the command line. The classification is by name only; macro bodies
were not reviewed (Tier B).

| Likely read-only | State-changing |
|---|---|
| `Get Firmware Version`, `Get Status`, `Get Simple Status`, `Check Firefly Temperature`, `Check Firefly Loss-of-Light`, `Check FPGA Temperature`, `Get Device Index`, `CFO Read`, `Get CFO Counters`, `Shared Run Plan Get Status`, `Runplan Subrun Config Read` | `CFO Soft Reset`, `CFO Hard Reset`, `Reset PCIe`, `Flash LEDs`, `Jitter Attenuator Setup`, `Reset Link Rx`, `Shutdown Link Tx`, `Startup Link Tx`, `Shutdown Firefly Tx`, `Startup Firefly Tx`, `CFO Reset`, `Clock Marker Enable/Disable`, `CFO Halt`, **`CFO Write`** (`address`, `writeData`; no outputs), `Loopback Test`, `Test Loopback marker`, `Reset Runplan`, `Compile Runplan`, `Set Runplan`, `Launch Runplan`, the two `Compile, Set, and Launch … Template Run Plan` macros, `Shared Run Plan Start/Stop/Join/Single-shot Join/Leave`, `Configure for Timing Chain`, `Super Orchestration Start/End`, `Super Orchestration`, `Buffer Test Detached`, `Runplan Subrun Config Setup`, `Loopback Topology Discovery`, `Temporary Diagnostic Test` |

Sources: `CFOFrontEndInterfaceImpl.cc:115-587` `registerFEMacroFunction` calls and
`CFOandDTCCoreVInterface.cc:131-310`. Use `CFOControl.py --fe CFO0` to obtain
the authoritative list from a running system.

There is **no** macro named `SetRegister`. The usage example in
`CFOControl.py:20` (`--cmd "SetRegister" --inputs "0x9100" "0x1"`) would fail
with `Command 'SetRegister' not found`. Its arguments are the reset bit:
`CFOandDTCCoreVInterface.cc:155-158` describes bit 0 of `0x9100` as the CFO
Control Register reset bit. See CFO-003.

## 6. Python API (`ots_mm_udp_interface`)

Documented in full in `man/man3/ots_mm_udp_interface.3`. In brief:

```python
from ots_mm_udp_interface import OtsMMUdpInterface
with OtsMMUdpInterface("mu2e-cfo-01", 5000, timeout_first=10.0, timeout_next=0.2) as mm:
    mm.get_frontend_list()                       # ['CFO0', 'DTC0', ...]
    mm.get_command_list("CFO0")                  # macro names
    mm.get_command_input_count("CFO0", "CFO Read")
    s = mm.build_input_string("CFO0", "CFO Read", ["0x9100"])
    mm.run_command("CFO0", "CFO Read", s)        # list of URI-encoded output values
```

All failures raise `RuntimeError`, except name resolution and socket errors,
which raise `OSError`.

## 7. Other interfaces

| Interface | Detail |
|---|---|
| Control room | `crs-app start cfocontrol` runs `start-mu2edaq-cfocontrol.sh` in a terminal (`mu2edaq-controlroom-setup/config/apps.yaml:127-135`, `terminal: true`) and exports `CRS_PORT_MACROMAKER`. |
| Discovery | None. CFOControl is a one-shot client and announces nothing (`DAQ-ControlRoom-Testing.md:271`). |
| Superproject test harness | `testing/common.sh:55` (`pkg_needs_venv`) excludes CFOControl from venv creation, so it runs on whatever `python3` is on `PATH` and needs PyYAML installed there. |
