# Staged issues — mu2edaq-CFOControl

Findings from the September 2026 DAQ mega-review (`mu2e-sept-mega-review`),
2026-10-06.

**Why these are staged rather than filed.** CONTRACT §9.1 says no GitHub write
is attempted from review agents. `Mu2e/mu2edaq-CFOControl` is public with
issues enabled. Each block below is the exact issue body (§6 template),
fingerprint included.

**Dedup.** `gh issue list -R Mu2e/mu2edaq-CFOControl --state all` returned one
issue: #1 (closed), about adding the start/stop scripts. None of the findings
below overlaps it.

**Evidence method.** Protocol claims were checked three ways: against the
client code, against the MacroMaker server source
(`otsdaq-utilities` checkout `69f05f85`, outside `mu2edaq-main`), and by
running `CFOControl.py` against a mock MacroMaker UDP server. The mock splits
each datagram exactly as `MacroMakerSupervisor.cc:541` does.

The draft of this file was left by an agent terminated mid-run. It was
re-verified on 2026-10-06: every server line cited from
`MacroMakerSupervisor.cc` and `ots_mm_udp_interface.cpp` was re-read at
`69f05f85`, and CFO-001, CFO-002 and CFO-004 were reproduced against an
independently written mock (bound to 127.0.0.1 only; no live system touched).

**Fingerprints** are `sha1("Mu2e/mu2edaq-CFOControl:<path>:<rule_id>")[:8]`;
the inputs are tabulated at the end.

8 findings: 3 × S2, 2 × S3, 3 × S4.

---

## CFO-001

**Title:** `[protocol] multi-input FE macros are mis-framed; inputs after the first arrive as the output list`

**Severity:** S2 — production breakage or silent wrong behaviour; workaround exists
**Category:** bug
**Location:** `ots_mm_udp_interface.py:409`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

`run_command` places the input string into the `;`-separated
`RunFrontendMacro` datagram without encoding it. `build_input_string` joins
the name/value pairs with a raw `;`. The MacroMaker splits the whole datagram
on `;`, so for any macro with two or more inputs, input 2 lands in the
output-names field and inputs 3+ and the save flag shift right. `CFO Write`
(`address`, `writeData`) is such a macro.

## Evidence

```
$ sed -n 473,479p ots_mm_udp_interface.py
        pairs = []
        for idx, val in enumerate(values):
            name = self.get_command_input_name(target_fe, command, idx)
            pairs.append(
                f"{encode_uri_component(name)},{encode_uri_component(val)}"
            )
        return ";".join(pairs)

# server (otsdaq-utilities 69f05f85, MacroMakerSupervisor.cc)
541:  StringMacros::getVectorFromString(buffer, {';'});
556:  ... decodeURIComponent(bufferFields[5]);  //two level ;- and ,- separated
558:  ... decodeURIComponent(bufferFields[6]);  //,- separated

# C++ reference client the port was made from (otsdaq-utilities/test/ots_mm_udp_interface.cpp)
1077:  sendMessage += ";" + encodeURIComponent(inputStr);  //double encoded

# CFOControl against a mock MacroMaker that splits the datagram like line 541:
$ python3 CFOControl.py --host 127.0.0.1 --port 15077 --fe CFO0 --cmd "CFO Write" --inputs 0x9100 0x1
RX 9 fields: ['RunFrontendMacro', 'CFOFrontEndInterface', 'CFO0', 'fe', 'CFO%20Write',
              'address,0x9100', 'writeData,0x1', '', '0']
  server view: inputArgs='address,0x9100' outputArgs='writeData,0x1' saveOutputs=False
```

## Why it matters

`CFO Write`, the only register-write macro on the CFO
(`otsdaq-mu2e/.../CFOFrontEndInterfaceImpl.cc:149-156`), receives `address`
but not `writeData`. The macro reads `writeData` with `__GET_ARG_IN__`
(`CFOFrontEndInterfaceImpl.cc:3283`). Whether that throws or substitutes a
default is defined in otsdaq core, which is not on disk; this review did not
verify it. Either the write fails, or it writes a value the operator did not
supply. Every other multi-input macro is affected the same way. Zero- and
one-input macros frame correctly. Workaround: use the MacroMaker web GUI or
the C++ `ots_mm_udp_test`.

## Suggested fix

In `run_command`, send `encode_uri_component(inputs)` in field 5, matching the
reference client. Send `encode_uri_component(",".join(encode_uri_component(n) for n in output_names))`
in field 6. Add a unit test asserting that the datagram always has exactly
8 `;`-separated fields.

## Related

- CFO-002, CFO-003 (same code path)

<!-- mega-review-fingerprint: 44c72ffe -->

---

## CFO-002

**Title:** `[protocol] plain-text "Error:" replies from the MacroMaker are reported as success`

**Severity:** S2 — production breakage or silent wrong behaviour; workaround exists
**Category:** bug
**Location:** `ots_mm_udp_interface.py:429`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

The MacroMaker reports failure in two forms. When the FE macro itself fails,
the reply is an XML `<Error value='…'/>` element. When the failure is at
supervisor level, the reply is the plain string `Error: <message>`. Examples
of supervisor-level failures are FE supervisor not configured, unknown FE
UID or type, and malformed request. CFOControl only searches for
`<Error value='`. A plain-text error therefore yields zero outputs and exit
status 0.

## Evidence

```
$ sed -n 428,433p ots_mm_udp_interface.py
        # Check for server-side errors
        err_val, err_pos = extract_xml_field(response, "Error")
        if err_pos != -1:

# server: MacroMakerSupervisor.cc
591:  sock.acknowledge(std::string("Error: ") + e.what(), true /* verbose */);
3744: "The FE Supervisor Index does not exist. Have you configured the state machine properly?"

# C++ reference: ots_mm_udp_interface.cpp
1148: if(runXML.size() == 0 || runXML.find("Error") == 0)

# mock replying exactly "Error: The FE Supervisor Index does not exist. ..."
$ python3 CFOControl.py --host 127.0.0.1 --port 15077 --fe CFO0 --cmd "CFO Write" --inputs 0x9100 0x1
Output from 'CFO0' / 'CFO Write':
$ echo $?
0
```

## Why it matters

`CFO Write` has no outputs, so not even the "expected N outputs" warning
fires. A write against a front-end whose state machine has not been
configured, which is the common case early in a shift, prints a success
banner and returns 0. For macros with outputs, the operator sees
`WARNING: Expected 2 output(s) but received 0` and never sees the server's
actual message.

## Suggested fix

After `_receive_all`, treat `response.lstrip().startswith("Error")` as a
failure and raise `RuntimeError(response)`, as the reference client does.
Keep the XML `<Error>` check.

## Related

- CFO-001, CFO-004

<!-- mega-review-fingerprint: b77780d6 -->

---

## CFO-003

**Title:** `[safety] state-changing CFO macros run with no confirmation, dry-run or read-back`

**Severity:** S2 — production breakage or silent wrong behaviour; workaround exists
**Category:** enhancement
**Location:** `CFOControl.py:249`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

`mode_run_command` sends any macro immediately. There is no confirmation
prompt, `--dry-run` or allow/deny list. There is no read-back after
`CFO Write` (which has no outputs) and no local record of what was sent. The
server adds no protection, because UDP requests run as `NO-USER` with
`allUsers: 255`. The module docstring's example is
`--cmd "SetRegister" --inputs "0x9100" "0x1"`. No macro of that name exists.
The arguments are bit 0 of the CFO Control Register, which otsdaq-mu2e
documents as the reset bit.

## Evidence

```
$ grep -n 'SetRegister' CFOControl.py
20:    python CFOControl.py --fe CFO0 --cmd "SetRegister" --inputs "0x9100" "0x1"

# otsdaq-mu2e/otsdaq-mu2e/CFOandDTCCore/CFOandDTCCoreVInterface.cc
155:  "Executes a soft reset of the " + ... +
156:  " by setting the reset bit (0) to true on the <b>" +
158:  "Control Register</b> (0x9100). "

# otsdaq-utilities MacroMakerSupervisor.cc (UDP path)
560:  std::string username            = "NO-USER";
561:  std::string userGroupPermission = "allUsers: 255";
```

State-changing macros registered on a CFO include `CFO Write`, `CFO Halt`,
`CFO Reset`, `CFO Hard Reset`, `Launch Runplan`, `Shared Run Plan Stop` and
`Shutdown Link Tx` (full list: `docs/INTERFACES.md` §5).

## Why it matters

The CFO is the timing master. One mistyped macro name or argument halts or
resets timing distribution for the whole DAQ. Nothing local or remote stops
it, and no record remains. S2 rather than S1: a register write is
recoverable and destroys no recorded data. The rubric says to take the lower
level when torn.

## Suggested fix

1. Add `--dry-run`, which prints the exact datagram and exits.
2. Keep a small read-only allowlist (`Get *`, `Check *`, `CFO Read`). Any other
   macro requires an interactive `yes` or `--yes`.
3. Add `--readback` for `CFO Write`, which issues `CFO Read` on the same
   address and compares.
4. Log every executed macro (host, user, FE, macro, inputs) to syslog.
5. Replace the docstring example with a read
   (`--cmd "CFO Read" --inputs 0x9100`).

## Related

- CFO-001, CFO-002
- Upstream (otsdaq-utilities, outside this review): the UDP remote-control path
  bypasses MacroMaker user permissions entirely.

<!-- mega-review-fingerprint: 448332ce -->

---

## CFO-004

**Title:** `[protocol] truncated multi-datagram replies are not detected and exit 0`

**Severity:** S3 — correctness or maintainability risk, no current outage
**Category:** bug
**Location:** `ots_mm_udp_interface.py:186`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

`_receive_all` concatenates datagrams until one inter-datagram gap exceeds
`timeouts.next_packet` (0.2 s). It never checks that the result is a complete
XML document. A delayed or lost fragment truncates the reply silently. The
consequences:

- for `RunFrontendMacro`, missing outputs produce only a warning, and exit 0;
- for `GetFrontendMacroInfo`, a cut inside an `<FEMacros …/>` element drops
  that front-end and all later ones with no message;
- the source address of a reply is never checked, so on a reused
  `OtsMMUdpInterface` a late fragment is read as the start of the next reply.

## Evidence

```
$ sed -n 186,200p ots_mm_udp_interface.py   # loop ends on first timeout, no completeness check

# mock sends a two-output reply in two datagrams 0.5 s apart
$ python3 CFOControl.py --host 127.0.0.1 --port 15077 --fe CFO0 --cmd "Get Status"
WARNING: Expected 2 output(s) but received 1.
Output from 'CFO0' / 'Get Status':
  Link Status: OK
$ echo $?
0
```

## Why it matters

Under load the result silently loses outputs and still exits 0. Scripts that
check only the exit status act on partial data. S3 rather than S2: a warning
is printed, the behaviour is inherited from the C++ reference, and 0.2 s is
long on a local network.

## Suggested fix

After receiving, require the reply to start with `Error` or to end with
`</ROOT>`. If it does not, keep reading up to `first_packet` before giving up
with a `RuntimeError`. Make an output-count mismatch exit non-zero. Discard
datagrams whose source is not `self._dest_addr`.

## Related

- CFO-002

<!-- mega-review-fingerprint: 71e05912 -->

---

## CFO-005

**Title:** `[tests] no tests and no CI for a tool that writes production timing registers`

**Severity:** S3 — correctness or maintainability risk, no current outage
**Category:** enhancement
**Location:** `CFOControl.py:1`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

The repository has no tests, no test directory and no `.github/workflows`.
`testing/common.sh:55` in the superproject excludes the package from venv
creation, so the suite-wide harness does not exercise it either.

## Evidence

```
$ git ls-files
.gitignore  CFOControl.py  LICENSE  config.yaml  ots_mm_udp_interface.py
start-mu2edaq-cfocontrol.sh  stop-mu2edaq-cfocontrol.sh
```

## Why it matters

CFO-001 and CFO-002 are both regressions against the C++ client this was
ported from. A 40-line mock UDP server catches both, and the review used
exactly that.

## Suggested fix

Add `tests/` with a pytest fixture that runs a mock MacroMaker on an
ephemeral UDP port. Cover datagram field count for 0, 1 and 2 inputs, the
plain-text `Error:` reply, the XML `<Error>` reply, fragmented replies, and
`FEMacros` parsing with tooltips. Add a GitHub Actions workflow running it on
Python 3.9.

## Related

- CFO-001, CFO-002, CFO-004

<!-- mega-review-fingerprint: 2ea23c9b -->

---

## CFO-006

**Title:** `[cli] --refresh is a no-op because the macro cache is per-process`

**Severity:** S4 — cosmetic, stale, hygiene
**Category:** bug
**Location:** `CFOControl.py:173`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

`--refresh` is documented as "Force a fresh query of frontend macro info
(ignore cache)". The only cache is `OtsMMUdpInterface._full_xml`, an instance
attribute that starts empty in every process, so the first query is always
fresh. The flag adds one redundant `GetFrontendMacroInfo` round-trip and
nothing else.

## Evidence

```
$ grep -n '_full_xml' ots_mm_udp_interface.py
172:        self._full_xml: str = ""
212:        if self._full_xml and not force_refresh:
```

## Why it matters

Operators may believe a stale on-disk cache exists and use `--refresh` to
work around a problem that has another cause.

## Suggested fix

Remove the option, or document it as a no-op kept for compatibility with
`ots_mm_udp_test`.

## Related

- none

<!-- mega-review-fingerprint: 1fe565d5 -->

---

## CFO-007

**Title:** `[config] config.yaml port is overridden by the start script and 5000 is an unenforced convention`

**Severity:** S4 — cosmetic, stale, hygiene
**Category:** bug
**Location:** `config.yaml:12`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

`start-mu2edaq-cfocontrol.sh` always passes `--port "$CRS_PORT_MACROMAKER"`
(default 5000), so `connection.port` in `config.yaml` never takes effect on the
control-room path. The host has no environment override. On the server
side, the MacroMaker binds whatever `OTS_MACROMAKER_UDP_PORT` says, and
nothing in `mu2edaq-main` sets it. The 5000 in three places is a client-side
assumption.

## Evidence

```
$ grep -n 'CRS_PORT_MACROMAKER' start-mu2edaq-cfocontrol.sh
16:CRS_PORT_MACROMAKER="${CRS_PORT_MACROMAKER:-5000}"
21:exec "$PY" CFOControl.py --port "$CRS_PORT_MACROMAKER" "$@"
$ grep -rn 'OTS_MACROMAKER_UDP_PORT' ~/mu2edaq-main --include='*' 2>/dev/null | wc -l
0
# otsdaq-utilities MacroMakerSupervisor.cc:471  atoi(__ENV__("OTS_MACROMAKER_UDP_PORT"))
```

## Why it matters

Editing `config.yaml` to change the port has no effect when CFOControl is
launched the standard way. There is also no single place that records which
port the MacroMaker actually listens on.

## Suggested fix

Have the start script pass `--port` only when `CRS_PORT_MACROMAKER` is set.
Add `CFOCONTROL_HOST`/`CFOCONTROL_PORT` environment overrides in
`load_config`. Record the MacroMaker's `OTS_MACROMAKER_UDP_PORT` next to the
otsdaq-mu2e configuration that sets it.

## Related

- CFO-008

<!-- mega-review-fingerprint: a624ab28 -->

---

## CFO-008

**Title:** `[packaging] no requirements.txt or bootstrap; .gitignore copied from the dashboard`

**Severity:** S4 — cosmetic, stale, hygiene
**Category:** enhancement
**Location:** `start-mu2edaq-cfocontrol.sh:19`
**Found by:** mega-review (`mu2e-sept-mega-review`), 2026-10-06

## What

The start script uses `./venv/bin/python` if it exists, but nothing creates
that venv, and there is no `requirements.txt` naming PyYAML. The superproject
explicitly skips venv creation for this package (`testing/common.sh:55`), so
in practice it runs on the system `python3`. `.gitignore` begins with
"Dashboard runtime state / dashboard.log / messages.db", copied from
mu2edaq-dashboard.

## Evidence

```
$ sed -n 53,56p ../testing/common.sh
pkg_needs_venv() {
  case "$1" in
    mu2edaq-CFOControl|mu2edaq-kpp-scripts|mu2edaq-shifter-tools|mu2edaq-trigger-scalers) return 1 ;;
$ sed -n 6,9p .gitignore
# Dashboard runtime state
dashboard.log
messages.db
```

## Why it matters

On a host whose system Python lacks PyYAML, the first control-room launch
fails with `PyYAML is required`. Low impact, since AL9 normally ships
`python3-pyyaml`.

## Suggested fix

Add `requirements.txt` (`PyYAML>=5.4`) and a `bootstrap.sh` that creates
`venv/`. Trim `.gitignore` to the Python entries.

## Related

- CFO-007

<!-- mega-review-fingerprint: 1a87e32a -->

---

## Fingerprint inputs

| ID | Input to `sha1(...)[:8]` | Fingerprint |
|---|---|---|
| CFO-001 | `Mu2e/mu2edaq-CFOControl:ots_mm_udp_interface.py:macro-input-framing` | 44c72ffe |
| CFO-002 | `Mu2e/mu2edaq-CFOControl:ots_mm_udp_interface.py:error-reply-undetected` | b77780d6 |
| CFO-003 | `Mu2e/mu2edaq-CFOControl:CFOControl.py:no-write-guard` | 448332ce |
| CFO-004 | `Mu2e/mu2edaq-CFOControl:ots_mm_udp_interface.py:udp-truncation-undetected` | 71e05912 |
| CFO-005 | `Mu2e/mu2edaq-CFOControl:CFOControl.py:no-tests` | 2ea23c9b |
| CFO-006 | `Mu2e/mu2edaq-CFOControl:CFOControl.py:refresh-noop` | 1fe565d5 |
| CFO-007 | `Mu2e/mu2edaq-CFOControl:config.yaml:config-port-dead` | a624ab28 |
| CFO-008 | `Mu2e/mu2edaq-CFOControl:start-mu2edaq-cfocontrol.sh:no-requirements` | 1a87e32a |
